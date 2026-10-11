use super::Page;
use super::PageResponse;
use super::navigation_response::MAX_ENDPOINTS;
use super::navigation_response::finalize_endpoints;
use super::navigation_response::flatten_headers;
use super::navigation_response::{ENDPOINT_SANITIZER_VERSION, safe_endpoint};
use super::shared::event_listener_config;
use super::validation::event_overflow;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::navigation_capture::NavigationCapture;
use crate::internal::browser::navigation_capture::NavigationCaptureOptions;
use chromiumoxide::cdp::browser_protocol::network::EventRequestWillBeSent;
use chromiumoxide::cdp::browser_protocol::network::EventResponseReceived;
use chromiumoxide::cdp::browser_protocol::network::ResourceType;
use chromiumoxide::cdp::browser_protocol::page::EventLifecycleEvent;
use chromiumoxide::listeners::EventDelivery;
use chromiumoxide::listeners::EventOverflowPolicy;
use futures::StreamExt;
use std::collections::HashSet;
use std::future;
use std::time::Duration;
use std::time::Instant;
use tokio::time;

impl Page {
    /// Arm bounded main-document source and resource-graph capture before
    /// navigation.
    pub async fn arm_navigation_capture(
        &self,
        options: NavigationCaptureOptions,
    ) -> Result<NavigationCapture> {
        self.ensure_active().await?;
        let options = options.validate()?;
        self.ensure_network_enabled().await?;
        NavigationCapture::arm(self.inner.clone(), options).await
    }

    /// Navigate to `url` and wait for network idle, returning a
    /// [`PageResponse`].
    ///
    /// Subscribes to both `Page.lifecycleEvent` and `Network.responseReceived`
    /// **before** navigation starts so that no events are missed.  The
    /// `networkIdle` terminates the wait; reaching the deadline raises a
    /// structured navigation timeout.
    ///
    /// Equivalent to Playwright's `page.goto(url, wait_until='networkidle')`.
    pub async fn goto_and_wait_for_idle(
        &self,
        url: &str,
        timeout: Duration,
    ) -> Result<PageResponse> {
        self.goto_and_wait_for_idle_with_capture(url, timeout, false)
            .await
    }

    /// Like [`Page::goto_and_wait_for_idle`], but when `capture_endpoints` is
    /// `true` also records the page's data-plane network endpoint set (XHR +
    /// Fetch request URLs) onto [`PageResponse::endpoints`].
    ///
    /// Capture is **opt-in** so the default fetch path pays no extra cost: the
    /// `Network.requestWillBeSent` listener is only subscribed when requested.
    /// It is passive (listen-only — no request interception, invisible to the
    /// site) and the endpoints are PII-stripped at the source via
    /// [`safe_endpoint`]. The listener is function-local and dropped on return,
    /// so nothing leaks into a later navigation.
    #[allow(
        clippy::cognitive_complexity,
        reason = "a single navigate select-loop reads more clearly inline than split across helpers"
    )]
    pub async fn goto_and_wait_for_idle_with_capture(
        &self,
        url: &str,
        timeout: Duration,
        capture_endpoints: bool,
    ) -> Result<PageResponse> {
        self.ensure_active().await?;
        self.ensure_network_enabled().await?;
        let started = Instant::now();
        // Subscribe to ALL event streams BEFORE navigation so no events slip
        // through the gap between goto() and the listener setup.
        let mut lifecycle = self
            .inner
            .event_listener::<EventLifecycleEvent>(event_listener_config(
                256,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        let mut network = self
            .inner
            .event_listener::<EventResponseReceived>(event_listener_config(
                1_024,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        // Request listener is gated on the opt-in so the wire/decode cost is
        // only paid when a caller wants the endpoint set.
        let mut requests = if capture_endpoints {
            Some(
                self.inner
                    .event_listener::<EventRequestWillBeSent>(event_listener_config(
                        1_024,
                        EventOverflowPolicy::Close,
                    ))
                    .await
                    .map_err(|e| VoidCrawlError::PageError(e.to_string()))?,
            )
        } else {
            None
        };

        // Start navigation (non-blocking CDP command)
        self.inner
            .goto(url)
            .await
            .map_err(|e| VoidCrawlError::NavigationFailed(e.to_string()))?;

        let deadline = time::sleep(timeout);
        tokio::pin!(deadline);

        let mut status_code: Option<u16> = None;
        let mut redirect_count: u32 = 0;
        // Headers of the final (non-redirect) Document response. Overwritten if
        // a later navigation supersedes it, mirroring `status_code`.
        let mut headers: Vec<(String, String)> = Vec::new();
        // Deduped data-plane endpoint set (only populated when capturing).
        let mut endpoints: HashSet<String> = HashSet::new();
        let mut endpoints_truncated = false;

        loop {
            tokio::select! {
                biased;
                maybe_lifecycle = lifecycle.next() => {
                    match maybe_lifecycle {
                        Some(EventDelivery::Event(event)) if event.name == "networkIdle" => break,
                        Some(EventDelivery::Event(_)) => {}
                        Some(EventDelivery::Lagged { .. }) => {
                            return Err(event_overflow("goto_and_wait_for_idle"));
                        }
                        None => break,
                    }
                }
                maybe_network = network.next() => {
                    if let Some(EventDelivery::Event(event)) = maybe_network {
                        // Only the Document response carries the page's actual
                        // status code. Sub-resources (images, scripts, XHRs)
                        // are ignored so a 404 favicon doesn't overwrite a 200
                        // document status.
                        if event.r#type == ResourceType::Document {
                            // Status is i64 in the CDP spec. Ignore malformed
                            // out-of-range provider values rather than truncating.
                            let Ok(code) = u16::try_from(event.response.status) else {
                                continue;
                            };
                            if (300..400).contains(&code) {
                                // Redirect in the navigation chain.
                                redirect_count = redirect_count.saturating_add(1);
                            } else if code != 0 {
                                // Chrome emits 0 for cancelled/intercepted
                                // requests — treat as "no network response".
                                status_code = Some(code);
                                headers = flatten_headers(event.response.headers.inner());
                            }
                        }
                    } else if matches!(maybe_network, Some(EventDelivery::Lagged { .. })) {
                        return Err(event_overflow("goto_and_wait_for_idle"));
                    }
                }
                // Endpoint capture — only polled when capturing (guard ensures
                // `requests` is Some). Sits BELOW lifecycle so a chatty request
                // stream can never starve the networkIdle break.
                //
                // select! evaluates every branch's future expression even when
                // its `if` guard is false, so the `None` branch must still yield
                // a same-typed future that never resolves — pending() parks it
                // harmlessly (it's unreachable in practice: requests is Some iff
                // capture_endpoints).
                maybe_request = async {
                    match requests.as_mut() {
                        Some(s) => s.next().await,
                        None => future::pending().await,
                    }
                }, if capture_endpoints => {
                    match maybe_request {
                        Some(EventDelivery::Event(event))
                            if matches!(event.r#type, Some(ResourceType::Xhr | ResourceType::Fetch)) =>
                        {
                            if let Some(ep) = safe_endpoint(&event.request.url) {
                                // A duplicate (already counted) applies no cap
                                // pressure; only a NEW endpoint past the cap
                                // flips the truncated flag.
                                if endpoints.len() < MAX_ENDPOINTS {
                                    endpoints.insert(ep);
                                } else if !endpoints.contains(&ep) {
                                    endpoints_truncated = true;
                                }
                            }
                        }
                        Some(EventDelivery::Lagged { .. }) => {
                            return Err(event_overflow("goto_and_wait_for_idle"));
                        }
                        Some(EventDelivery::Event(_)) | None => {}
                    }
                }
                () = &mut deadline => {
                    return Err(VoidCrawlError::NavigationTimeout {
                        url: url.to_string(),
                        wait_phase: "networkidle".to_string(),
                        timeout_secs: timeout.as_secs_f64(),
                        elapsed_secs: started.elapsed().as_secs_f64(),
                    });
                }
            }
        }

        let html = self.content().await?;
        let final_url = self.url().await?.unwrap_or_default();
        let identity = self.top_level_document_identity().await?;
        self.observe_document_identity(&identity, true)?;
        Ok(PageResponse {
            html,
            url: final_url,
            status_code,
            redirected: redirect_count > 0,
            headers,
            endpoints: finalize_endpoints(&endpoints, capture_endpoints),
            endpoints_truncated,
            endpoint_sanitizer_version: capture_endpoints.then_some(ENDPOINT_SANITIZER_VERSION),
        })
    }
}
