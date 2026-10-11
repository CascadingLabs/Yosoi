use super::EXECUTION_CONTEXT_WAIT;
use super::Page;
use super::TabInstrumentationState;
use super::shared::event_listener_config;
use super::validation::event_overflow;
use crate::internal::browser::environment::BrowserCaptureCapabilities;
use crate::internal::browser::environment::BrowserEnvironmentSnapshot;
use crate::internal::browser::environment::ControllerVersion;
use crate::internal::browser::environment::ENVIRONMENT_SNAPSHOT_JS;
use crate::internal::browser::environment::InstrumentationSnapshot;
use crate::internal::browser::environment::RendererVersion;
use crate::internal::browser::environment::rendering_environment;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::vendor::chromiumoxide::CdpMode;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::browser::GetVersionParams;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::network::EnableParams as NetworkEnableParams;
use crate::internal::browser::vendor::chromiumoxide::cdp::js_protocol::runtime::EventExecutionContextCreated;
use crate::internal::browser::vendor::chromiumoxide::listeners::EventDelivery;
use crate::internal::browser::vendor::chromiumoxide::listeners::EventOverflowPolicy;
use futures::StreamExt;
use serde_json::Value;
use std::sync::atomic::Ordering;
use tokio::time;

impl Page {
    pub(super) async fn wait_for_main_execution_context(&self) -> Result<()> {
        let mut created = self
            .inner
            .event_listener::<EventExecutionContextCreated>(event_listener_config(
                16,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        time::timeout(EXECUTION_CONTEXT_WAIT, async {
            loop {
                if self
                    .inner
                    .execution_context()
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
                    .is_some()
                {
                    return Ok(());
                }
                match created.next().await {
                    Some(EventDelivery::Event(_)) => {}
                    Some(EventDelivery::Lagged { .. }) => {
                        return Err(event_overflow("wait_for_main_execution_context"));
                    }
                    None => return Err(VoidCrawlError::BrowserClosed),
                }
            }
        })
        .await
        .map_err(|_| VoidCrawlError::Timeout("main execution context was not ready".into()))?
    }

    /// Observe the effective browser environment and active VoidCrawl capture
    /// primitives for this page.
    ///
    /// Representation-affecting values are read from the page's main world;
    /// they are not copied from requested launch configuration. The result is
    /// owned, secret-safe provider data and contains no live CDP handles,
    /// profile paths, cookies, credentials, or request headers.
    pub async fn environment_snapshot(&self) -> Result<BrowserEnvironmentSnapshot> {
        let renderer = self
            .inner
            .execute(GetVersionParams::default())
            .await
            .map(|response| RendererVersion::from(response.result))
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        // A newly created headful target can be visible before its main world
        // exists. Normal mode receives Runtime execution-context events, so
        // wait for one instead of timing a retry. Minimal deliberately leaves
        // Runtime disabled; it receives no such events, while `evaluate` can
        // issue its one-shot main-world command without a cached context.
        if matches!(self.cdp_mode, CdpMode::Normal) {
            self.wait_for_main_execution_context().await?;
        }
        let result = self
            .inner
            .evaluate(ENVIRONMENT_SNAPSHOT_JS)
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?;
        let value = result.value().cloned().unwrap_or(Value::Null);
        let instrumentation = InstrumentationSnapshot::for_page(
            self.cdp_mode,
            self.network_enabled.load(Ordering::Relaxed),
            self.runtime_enabled.load(Ordering::Relaxed),
            self.pre_navigation_stealth.load(Ordering::Relaxed),
            self.attached_browser,
        );
        let capabilities = BrowserCaptureCapabilities::from_instrumentation(instrumentation);

        Ok(BrowserEnvironmentSnapshot {
            controller: ControllerVersion::current(),
            renderer,
            mode: self.browser_mode.clone(),
            rendering: rendering_environment(&value),
            instrumentation,
            capabilities,
        })
    }

    /// Snapshot this tab's instrumentation state for routing/debugging.
    pub fn instrumentation_state(&self) -> TabInstrumentationState {
        let network_enabled = self.network_enabled.load(Ordering::Relaxed);
        let runtime_enabled = self.runtime_enabled.load(Ordering::Relaxed);
        let pre_navigation_stealth = self.pre_navigation_stealth.load(Ordering::Relaxed);
        TabInstrumentationState {
            low_cdp: !(network_enabled || runtime_enabled),
            network_enabled,
            runtime_enabled,
            utility_world_enabled: false,
            pre_navigation_stealth,
        }
    }

    pub(super) async fn ensure_network_enabled(&self) -> Result<()> {
        if !self.network_enabled.load(Ordering::Relaxed) {
            self.inner
                .execute(NetworkEnableParams::default())
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            self.network_enabled.store(true, Ordering::Relaxed);
        }
        Ok(())
    }

    pub(super) async fn ensure_runtime_enabled(&self) -> Result<()> {
        if !self.runtime_enabled.load(Ordering::Relaxed) {
            self.inner
                .enable_runtime()
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            self.runtime_enabled.store(true, Ordering::Relaxed);
        }
        Ok(())
    }
}
