//! Shared all-operation control over the existing per-tab navigation gate.

use super::{BrowserExecutionManagerError, RuntimeBrowserTabLease};
use crate::browser as browser_config;
use crate::internal::browser::controller as provider;
use serde_json::Value;
use std::fmt;
use std::str as std_str;
use std::sync as std_sync;
use std::{sync::Arc, time::Duration};
use thiserror::Error;
use tokio::time as tokio_time;
use tokio::{
    sync::OwnedMutexGuard,
    time::{Instant, timeout_at},
};
use tokio_util::sync::CancellationToken;

#[derive(Debug, Error)]
pub enum BrowserControlError {
    #[error("browser tab ownership failed")]
    Ownership(#[from] BrowserExecutionManagerError),
    #[error("browser provider operation failed")]
    Provider(#[from] provider::VoidCrawlError),
    #[error("browser operation cancelled")]
    Cancelled,
    #[error("browser operation deadline elapsed")]
    Deadline,
    #[error("browser capture was incomplete")]
    IncompleteCapture,
    #[error("invalid bounded browser input")]
    InvalidInput,
    #[error("native typing target is detached or no longer focused before keyboard dispatch")]
    InputTargetLost,
    #[error("browser control waiter capacity exhausted")]
    Capacity,
    #[error("parked condition observation was interrupted or invalidated")]
    ConditionWaitLost,
}

impl BrowserControlError {
    /// Explicit script execution returns bounded exception diagnostics to its caller.
    /// Other provider failures retain the provider's safe public summary.
    pub fn execution_message(&self) -> String {
        let message = match self {
            Self::Provider(provider::VoidCrawlError::JsEvalError(message)) => message.clone(),
            Self::Provider(error @ provider::VoidCrawlError::NavigationFailed(reason)) => {
                format!(
                    "{} [{}; {}]",
                    error.safe_message(),
                    error.code(),
                    navigation_failure_kind(reason)
                )
            }
            Self::Provider(error) => format!("{} [{}]", error.safe_message(), error.code()),
            _ => self.to_string(),
        };
        message.chars().take(4096).collect()
    }
    pub const fn requires_fence(&self) -> bool {
        matches!(
            self,
            Self::Cancelled
                | Self::Deadline
                | Self::Ownership(_)
                | Self::ConditionWaitLost
                | Self::Provider(
                    provider::VoidCrawlError::Timeout(_)
                        | provider::VoidCrawlError::NavigationTimeout { .. }
                        | provider::VoidCrawlError::NavigationStateUncertain
                        | provider::VoidCrawlError::BrowserClosed
                        | provider::VoidCrawlError::RendererCrashed
                )
        )
    }
}

fn input_provider_error(error: provider::VoidCrawlError) -> BrowserControlError {
    match error {
        provider::VoidCrawlError::InvalidInput {
            operation: "resolve_input",
            ..
        } => BrowserControlError::InvalidInput,
        error => error.into(),
    }
}

/// Classify only fixed provider messages; arbitrary diagnostics may contain URLs or secrets.
fn navigation_failure_kind(reason: &str) -> &'static str {
    match reason {
        "Request timed out." => "provider_timeout",
        "Received no response from the chromium instance." => "provider_no_response",
        "The CDP session owning the requested frame detached." => "provider_session_detached",
        "net::ERR_ABORTED" => "network_aborted",
        "net::ERR_CONNECTION_RESET" => "network_connection_reset",
        "net::ERR_TIMED_OUT" => "network_timeout",
        "net::ERR_NAME_NOT_RESOLVED" => "network_name_not_resolved",
        "net::ERR_CONNECTION_CLOSED" => "network_connection_closed",
        _ => "provider_navigation_failure",
    }
}

/// Held control on a concrete tab. Provider handles remain inside the capture crate.
pub struct RuntimeBrowserControl {
    page: Arc<provider::Page>,
    authority: Arc<ControlAuthority>,
    closing: CancellationToken,
}
impl fmt::Debug for RuntimeBrowserControl {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RuntimeBrowserControl")
            .field("closing", &self.closing.is_cancelled())
            .finish_non_exhaustive()
    }
}

pub(super) struct ControlAuthority {
    guard: std_sync::Mutex<Option<OwnedMutexGuard<()>>>,
}
impl ControlAuthority {
    pub(super) fn revoke(&self) {
        if let Ok(mut guard) = self.guard.lock() {
            let _ = guard.take();
        }
    }
    fn active(&self) -> bool {
        self.guard.lock().is_ok_and(|guard| guard.is_some())
    }
}

impl RuntimeBrowserTabLease {
    /// Uses the same gate as scheduled navigation and tab close.
    pub async fn control_before(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<RuntimeBrowserControl, BrowserControlError> {
        let parts = self.navigation_parts().await?;
        let _waiting = parts
            .control_waiters
            .try_acquire()
            .map_err(|_| BrowserControlError::Capacity)?;
        let guard = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(BrowserControlError::Cancelled),
            () = parts.closing.cancelled() => return Err(BrowserControlError::Ownership(BrowserExecutionManagerError::TabReleased)),
            guard = timeout_at(deadline, parts.gate.lock_owned()) => guard.map_err(|_| BrowserControlError::Deadline)?,
        };
        // Revalidate after waiting; a second handle may have closed the tab.
        let page = self.page().await?;
        let authority = Arc::new(ControlAuthority {
            guard: std_sync::Mutex::new(Some(guard)),
        });
        let resource = self
            .resource
            .upgrade()
            .ok_or(BrowserExecutionManagerError::TabReleased)?;
        let mut state = resource.state.lock().await;
        if state.releasing || state.release_result.is_some() {
            return Err(BrowserExecutionManagerError::TabReleased.into());
        }
        let tab = state
            .tabs
            .get_mut(&self.id)
            .ok_or(BrowserExecutionManagerError::TabReleased)?;
        if tab.closing || !tab.open {
            return Err(BrowserExecutionManagerError::TabReleased.into());
        }
        tab.control = Some(Arc::downgrade(&authority));
        drop(state);
        Ok(RuntimeBrowserControl {
            page,
            authority,
            closing: parts.closing,
        })
    }
}

impl RuntimeBrowserControl {
    /// Immutable admitted/reported provenance remains readable after fencing;
    /// it grants no live browser authority or claim about current availability.
    pub fn execution_identity(&self) -> Option<browser_config::BrowserExecutionIdentity> {
        self.page.execution_identity()
    }
    /// Checks the watch's original frame and loader-derived epoch against a
    /// fresh browser frame-tree read, including after worker admission.
    pub async fn observation_scope_is_current(
        &self,
        watch: &provider::ObservationWatch,
    ) -> Result<bool, BrowserControlError> {
        self.check_authority()?;
        let current = self.page.document_scope().await?;
        let original = watch.start_scope();
        Ok(current.frame_id == original.frame_id
            && current.epoch == original.epoch
            && current.frame == original.frame)
    }

    /// Returns only after the observer has been installed on this owned tab.
    pub async fn start_condition_wait(
        &self,
        expression: &str,
        maximum: Duration,
    ) -> Result<provider::page::ConditionWait, BrowserControlError> {
        self.check_authority()?;
        Ok(self.page.start_condition_wait(expression, maximum).await?)
    }

    /// Arm all selected subscriptions before the caller performs an action.
    pub async fn start_observation_watch(
        &self,
        options: provider::ObservationWatchOptions,
    ) -> Result<provider::ObservationWatch, BrowserControlError> {
        self.check_authority()?;
        let watch = self.page.start_observation_watch(options).await?;
        self.check_authority()?;
        Ok(watch)
    }

    /// Park on an already-armed event stream without issuing browser commands.
    /// Completed response candidates retain their provider request-start wall
    /// time in Unix microseconds, along with the watched frame/loader IDs.
    pub async fn next_observation(
        &self,
        watch: &mut provider::ObservationWatch,
    ) -> Result<provider::ObservationChange, BrowserControlError> {
        self.check_authority()?;
        let closing = self.closing.clone();
        let change = tokio::select! {
            biased;
            () = closing.cancelled() => {
                return Err(BrowserExecutionManagerError::TabReleased.into());
            }
            result = watch.next() => result.map_err(|_| BrowserControlError::ConditionWaitLost)?,
        };
        self.check_authority()?;
        Ok(change)
    }

    /// Fetch a candidate response body while the caller holds worker capacity.
    /// Incomplete bodies cannot satisfy a response assertion.
    pub async fn capture_response_body(
        &self,
        candidate: &provider::CompletedResponseCandidate,
        max_bytes: usize,
    ) -> Result<Vec<u8>, BrowserControlError> {
        self.check_authority()?;
        let captured = self
            .page
            .capture_observation_response_body(candidate, max_bytes)
            .await?;
        self.check_authority()?;
        if !captured.complete {
            return Err(BrowserControlError::IncompleteCapture);
        }
        Ok(captured.bytes().to_vec())
    }

    /// Query the browser-computed AX tree by exact accessible name and optional
    /// role. The serialized result must fit the caller's byte budget.
    pub async fn query_accessibility(
        &self,
        name: &str,
        role: Option<&str>,
        max_bytes: usize,
    ) -> Result<Value, BrowserControlError> {
        self.check_authority()?;
        if max_bytes == 0 {
            return Err(BrowserControlError::InvalidInput);
        }
        // queryAXTree is deferred to a renderer lifecycle update and can remain
        // pending on background tabs. A fresh root-frame AX snapshot forces the
        // browser-computed tree to update without activating or polling the tab.
        let snapshot = self.page.get_full_ax_tree(None).await?;
        let nodes = snapshot
            .as_array()
            .ok_or(BrowserControlError::IncompleteCapture)?;
        let tree = Value::Array(
            nodes
                .iter()
                .filter(|node| {
                    node.get("ignored").and_then(Value::as_bool) == Some(false)
                        && node
                            .get("name")
                            .and_then(|name| name.get("value"))
                            .and_then(Value::as_str)
                            == Some(name)
                        && role.is_none_or(|role| {
                            node.get("role")
                                .and_then(|role| role.get("value"))
                                .and_then(Value::as_str)
                                == Some(role)
                        })
                })
                .cloned()
                .collect(),
        );
        self.check_authority()?;
        let encoded =
            serde_json::to_vec(&tree).map_err(|_| BrowserControlError::IncompleteCapture)?;
        if encoded.len() > max_bytes {
            return Err(BrowserControlError::IncompleteCapture);
        }
        Ok(tree)
    }

    /// Acknowledge observer teardown while this control still owns the tab.
    pub async fn settle_observation_watch(
        &self,
        watch: &mut provider::ObservationWatch,
    ) -> Result<(), BrowserControlError> {
        self.check_authority()?;
        watch.settle().await?;
        self.check_authority()?;
        Ok(())
    }

    pub fn check_authority(&self) -> Result<(), BrowserControlError> {
        if self.closing.is_cancelled() || !self.authority.active() {
            return Err(BrowserExecutionManagerError::TabReleased.into());
        }
        Ok(())
    }
    pub fn closing(&self) -> CancellationToken {
        self.closing.clone()
    }

    /// Deny further control after an unresolved dispatch without releasing its gate.
    pub fn fence(&self) {
        self.closing.cancel();
    }

    pub(in crate::internal::web_capture) fn page(&self) -> &provider::Page {
        &self.page
    }

    pub async fn document_epoch(&self) -> Result<u64, BrowserControlError> {
        self.check_authority()?;
        match self.page.document_scope().await?.epoch {
            provider::DocumentEpoch::Known(epoch) => Ok(epoch),
            provider::DocumentEpoch::UnavailableForAttachedPage => {
                Err(BrowserControlError::IncompleteCapture)
            }
        }
    }
    pub async fn url(&self) -> Result<Option<String>, BrowserControlError> {
        self.check_authority()?;
        Ok(self.page.url().await?)
    }

    pub async fn navigate(&self, url: &str, timeout: Duration) -> Result<(), BrowserControlError> {
        self.check_authority()?;
        // Stateful work must leave page loading/rendering intact. The Request
        // capture recipe separately retains its DOM-checkpoint finalization.
        if let Ok(result) = tokio_time::timeout(timeout, self.page.navigate(url)).await {
            result?;
        } else {
            self.fence();
            return Err(BrowserControlError::Deadline);
        }
        Ok(())
    }

    pub async fn evaluate_json(&self, source: &str) -> Result<Value, BrowserControlError> {
        self.check_authority()?;
        Ok(self.page.evaluate_js(source).await?)
    }

    pub async fn unique_frame(&self, pattern: &str) -> Result<bool, BrowserControlError> {
        self.check_authority()?;
        Ok(self
            .page
            .frame_urls()
            .await?
            .iter()
            .filter(|url| url.contains(pattern))
            .count()
            == 1)
    }
    pub async fn evaluate_json_in(
        &self,
        source: &str,
        frame: Option<&str>,
    ) -> Result<Value, BrowserControlError> {
        self.check_authority()?;
        match frame {
            Some(pattern) => Ok(self.page.evaluate_js_in_frame(pattern, source).await?),
            None => self.evaluate_json(source).await,
        }
    }

    /// Evaluate in the main-world context anchored by an armed observation.
    pub async fn evaluate_in_observation_scope(
        &self,
        source: &str,
        watch: &provider::ObservationWatch,
    ) -> Result<Value, BrowserControlError> {
        self.check_authority()?;
        let result = self
            .page
            .evaluate_js_in_observation_scope(source, watch)
            .await;
        self.check_authority()?;
        Ok(result?)
    }

    pub async fn wait_condition(
        &self,
        expression: &str,
        timeout: Duration,
    ) -> Result<bool, BrowserControlError> {
        self.check_authority()?;
        Ok(self.page.wait_for_expression(expression, timeout).await?)
    }

    pub async fn click(&self, selector: &str) -> Result<(), BrowserControlError> {
        self.check_authority()?;
        self.page
            .click_unique_element(selector)
            .await
            .map_err(input_provider_error)?;
        Ok(())
    }

    pub async fn click_in_observation_scope(
        &self,
        selector: &str,
        watch: &provider::ObservationWatch,
    ) -> Result<(), BrowserControlError> {
        self.check_authority()?;
        let result = self.page.click_element_in_scope(selector, watch).await;
        self.check_authority()?;
        result.map_err(input_provider_error)?;
        Ok(())
    }

    pub async fn enter_text(&self, selector: &str, text: &str) -> Result<(), BrowserControlError> {
        self.check_authority()?;
        match self.page.type_into_unique_element(selector, text).await {
            Err(provider::VoidCrawlError::InvalidInput {
                operation: "resolve_input",
                ..
            }) => Err(BrowserControlError::InvalidInput),
            Err(provider::VoidCrawlError::InvalidInput {
                operation: "type_into",
                reason: "target_lost_before_typing",
            }) => Err(BrowserControlError::InputTargetLost),
            result => {
                result?;
                Ok(())
            }
        }
    }

    pub async fn enter_text_in_observation_scope(
        &self,
        selector: &str,
        text: &str,
        watch: &provider::ObservationWatch,
    ) -> Result<(), BrowserControlError> {
        self.check_authority()?;
        let result = self.page.type_into_in_scope(selector, text, watch).await;
        self.check_authority()?;
        match result {
            Err(provider::VoidCrawlError::InvalidInput {
                operation: "resolve_input",
                ..
            }) => Err(BrowserControlError::InvalidInput),
            Err(provider::VoidCrawlError::InvalidInput {
                operation: "type_into",
                reason: "target_lost_before_typing",
            }) => Err(BrowserControlError::InputTargetLost),
            result => {
                result?;
                Ok(())
            }
        }
    }

    pub async fn dom(&self, max_bytes: usize) -> Result<(String, u64), BrowserControlError> {
        self.check_authority()?;
        let captured = self.page.rendered_dom_snapshot(max_bytes).await?;
        if captured.state != provider::SnapshotState::Complete {
            return Err(BrowserControlError::IncompleteCapture);
        }
        let epoch = match captured.scope.epoch {
            provider::DocumentEpoch::Known(value) => value,
            provider::DocumentEpoch::UnavailableForAttachedPage => {
                return Err(BrowserControlError::IncompleteCapture);
            }
        };
        let html = std_str::from_utf8(captured.bytes())
            .map_err(|_| BrowserControlError::IncompleteCapture)?
            .to_owned();
        Ok((html, epoch))
    }

    pub async fn screenshot(&self) -> Result<Vec<u8>, BrowserControlError> {
        self.check_authority()?;
        Ok(self.page.screenshot_png().await?)
    }
}

#[cfg(test)]
mod navigation_diagnostic_tests {
    use super::{BrowserControlError, provider};

    #[test]
    fn reports_network_abort_without_exposing_arbitrary_provider_text() {
        let aborted = BrowserControlError::Provider(provider::VoidCrawlError::NavigationFailed(
            "net::ERR_ABORTED".to_owned(),
        ));
        assert!(aborted.execution_message().contains("network_aborted"));
        let private = BrowserControlError::Provider(provider::VoidCrawlError::NavigationFailed(
            "https://example.test/?access_token=private-token".to_owned(),
        ));
        let message = private.execution_message();
        assert!(message.contains("provider_navigation_failure"));
        assert!(!message.contains("private-token"));
        assert!(!message.contains("example.test"));
    }
}
