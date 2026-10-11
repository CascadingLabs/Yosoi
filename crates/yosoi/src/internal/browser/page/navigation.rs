use super::Page;
use super::document::selector_wait_status;
use super::shared::event_listener_config;
use super::validation::event_overflow;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::observation::ObservationOptions;
use crate::internal::browser::observation::ObservationScope;
use crate::internal::browser::response::ResponseCapture;
use crate::internal::browser::response::ResponseCaptureLimits;
use chromiumoxide::cdp::browser_protocol::page::EventLifecycleEvent;
use chromiumoxide::cdp::browser_protocol::page::StopLoadingParams;
use chromiumoxide::cdp::js_protocol::runtime::EvaluateParams;
use chromiumoxide::listeners::EventDelivery;
use chromiumoxide::listeners::EventOverflowPolicy;
use futures::StreamExt;
use std::time::Duration;
use tokio::time;

impl Page {
    /// Arm bounded, secret-safe CDP lifecycle observation before navigation.
    ///
    /// Requested event listeners are registered before this method returns, so
    /// a subsequent [`Page::navigate`] cannot race the initial document
    /// request or synchronous first-script console/runtime events. Artifact
    /// payload collectors are deliberately separate from this lifecycle scope.
    /// Renderer crashes wake the scope in normal CDP mode, where stable
    /// `Target.targetCrashed` events are enabled by target discovery. Minimal
    /// mode does not enable discovery and remains bounded by its deadline or a
    /// disconnect signal.
    pub async fn arm_observation(&self, options: ObservationOptions) -> Result<ObservationScope> {
        self.ensure_active().await?;
        let options = options.validate()?;
        if options.collect_network {
            self.ensure_network_enabled().await?;
        }
        if options.collect_console || options.collect_exceptions {
            self.ensure_runtime_enabled().await?;
        }
        ObservationScope::arm(self.inner.clone(), options).await
    }

    /// Arm a passive response-body capture before performing a triggering
    /// action. Every `(name, pattern)` must be fulfilled once.
    pub async fn expect_responses(
        &self,
        patterns: Vec<(String, String)>,
        timeout: Duration,
        limits: ResponseCaptureLimits,
    ) -> Result<ResponseCapture> {
        ResponseCapture::arm(self.inner.clone(), patterns, timeout, limits).await
    }

    // ── Navigation ──────────────────────────────────────────────────────

    /// Stop an in-progress document load.
    pub async fn stop_loading(&self) -> Result<()> {
        self.inner
            .execute(StopLoadingParams::default())
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        Ok(())
    }

    /// Navigate to `url` and wait for the CDP response.
    pub async fn navigate(&self, url: &str) -> Result<()> {
        self.ensure_active().await?;
        self.inner
            .goto(url)
            .await
            .map_err(|e| VoidCrawlError::NavigationFailed(e.to_string()))?;
        let identity = self.top_level_document_identity().await?;
        self.observe_document_identity(&identity, true)?;
        Ok(())
    }

    /// Wait for the in-flight navigation to finish.
    pub async fn wait_for_navigation(&self) -> Result<()> {
        self.inner
            .wait_for_navigation()
            .await
            .map_err(|e| VoidCrawlError::NavigationFailed(e.to_string()))?;
        Ok(())
    }

    /// Event-driven wait for the network to become idle.
    ///
    /// Subscribes to `Page.lifecycleEvent` and waits for one of these
    /// events (in priority order):
    ///
    /// 1. **`networkIdle`** — 0 in-flight requests for 500 ms (best signal)
    /// 2. **`networkAlmostIdle`** — ≤ 2 in-flight requests for 500 ms (fallback
    ///    when analytics / long-polls prevent true idle)
    ///
    /// Returns the name of the lifecycle event that resolved the wait
    /// (`"networkIdle"` or `"networkAlmostIdle"`), or `None` if the
    /// timeout was reached without either event firing.
    ///
    /// This is fully async and event-driven — **no polling**.
    pub async fn wait_for_network_idle(&self, timeout: Duration) -> Result<Option<String>> {
        self.ensure_network_enabled().await?;
        let mut events = self
            .inner
            .event_listener::<EventLifecycleEvent>(event_listener_config(
                256,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        let deadline = time::sleep(timeout);
        tokio::pin!(deadline);

        // Track the best event we've seen so far
        let mut got_almost_idle = false;

        loop {
            tokio::select! {
                biased;
                maybe_event = events.next() => {
                    match maybe_event {
                        Some(EventDelivery::Event(event)) => {
                            match event.name.as_str() {
                                "networkIdle" => return Ok(Some("networkIdle".into())),
                                "networkAlmostIdle" => { got_almost_idle = true; }
                                _ => {} // DOMContentLoaded, load, etc — ignore
                            }
                        }
                        Some(EventDelivery::Lagged { .. }) => {
                            return Err(event_overflow("wait_for_network_idle"));
                        }
                        None => break, // stream closed
                    }
                }
                () = &mut deadline => break,
            }
        }

        // Timeout reached — return best fallback
        if got_almost_idle {
            Ok(Some("networkAlmostIdle".into()))
        } else {
            Ok(None)
        }
    }

    /// Wait until `document.querySelector(selector)` matches an element,
    /// driven by a `MutationObserver` inside the page — no Rust-side polling.
    /// Resolves immediately if the element is already present. The in-page
    /// promise returns a typed timeout status after `timeout`; CDP/JS failures
    /// remain [`VoidCrawlError::JsEvalError`].
    pub async fn wait_for_selector(&self, selector: &str, timeout: Duration) -> Result<()> {
        let sel_lit = serde_json::to_string(selector)
            .map_err(|e| VoidCrawlError::Other(format!("selector encode: {e}")))?;
        let timeout_ms = u64::try_from(timeout.as_millis()).unwrap_or(u64::MAX);
        let js = format!(
            "new Promise((resolve) => {{\
              const sel = {sel_lit};\
              if (document.querySelector(sel)) return resolve(true);\
              const root = document.documentElement || document.body;\
              const obs = new MutationObserver(() => {{\
                if (document.querySelector(sel)) {{\
                  obs.disconnect();\
                  clearTimeout(t);\
                  resolve(true);\
                }}\
              }});\
              obs.observe(root, {{ childList: true, subtree: true }});\
              const t = setTimeout(() => {{\
                obs.disconnect();\
                resolve(false);\
              }}, {timeout_ms});\
            }})"
        );
        let params = EvaluateParams::builder()
            .expression(js)
            .return_by_value(true)
            .await_promise(true)
            .build()
            .map_err(VoidCrawlError::JsEvalError)?;
        let result = self
            .inner
            .evaluate_expression(params)
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?;
        selector_wait_status(result.value(), selector, timeout_ms)
    }
}
