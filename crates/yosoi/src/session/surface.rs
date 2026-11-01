//! Trusted Surface adapters reuse Work admission without granting authored JavaScript.
use super::{ActionKind, SessionError, Work, capture::ScreenshotRegion};
use crate::internal::browser::{
    controller::NetworkObservationSubscription, page::ObservationResponseBody,
};
use crate::{automation_record::OperationReceipt, internal::browser::page::SurfaceInput};
use serde_json::{Value, json};
use std::time::Duration;
use tokio_util::sync::CancellationToken;

const SCRIPT: &str = include_str!("../surface/browser/extract.js");

impl Work {
    pub(crate) fn surface_session_cancellation(&self) -> CancellationToken {
        self.session.inner.backend.cancellation()
    }

    pub(crate) fn surface_authority_cancellation(&self) -> CancellationToken {
        self.control.closing()
    }

    pub(crate) fn surface_authority_active(&self) -> bool {
        self.control.authority_active()
    }

    pub(crate) async fn surface_start_network_subscription(
        &self,
        max_events: usize,
        max_buffered_events: usize,
    ) -> Result<NetworkObservationSubscription, SessionError> {
        let _operation = self.operation()?;
        self.call(
            self.control
                .start_network_observation_subscription(max_events, max_buffered_events),
        )
        .await
    }

    pub(crate) async fn surface_capture_network_body(
        &self,
        request_id: &str,
        max_bytes: usize,
    ) -> Result<ObservationResponseBody, SessionError> {
        let _operation = self.operation()?;
        self.call(
            self.control
                .capture_network_response_body(request_id, max_bytes),
        )
        .await
    }

    pub(crate) fn surface_authorize(
        &self,
        kind: ActionKind,
        input: &str,
    ) -> Result<(), SessionError> {
        self.authorize(kind, input)
    }

    pub(crate) fn surface_identity(&self) -> (String, String) {
        (self.session.inner.backend.id(), self.tab_id.clone())
    }

    pub(crate) fn surface_observation_limit(&self) -> usize {
        self.observation_limit()
    }

    pub(crate) async fn surface_script(
        &self,
        operation: &str,
        input: Value,
    ) -> Result<Value, SessionError> {
        let _operation = self.operation()?;
        if !self.session.settings().dom {
            return Err(SessionError::Denied);
        }
        if serde_json::to_vec(&input)
            .map_err(|_| SessionError::InvalidInput)?
            .len()
            > self.session.settings().maximum_input_bytes
        {
            return Err(SessionError::InvalidInput);
        }
        let value = if operation == "watch" {
            self.authorize(ActionKind::Wait, "")?;
            self.surface_wait(input).await?
        } else {
            self.call(self.control.surface_script(operation, &input))
                .await?
        };
        let limit = if operation == "capture" {
            self.observation_limit()
        } else {
            self.session.settings().maximum_result_bytes
        };
        if serde_json::to_vec(&value)
            .map_err(|_| SessionError::InvalidInput)?
            .len()
            > limit
        {
            return Err(SessionError::ResultLimit { maximum: limit });
        }
        Ok(value)
    }

    async fn surface_wait(&self, input: Value) -> Result<Value, SessionError> {
        let requested = input
            .get("timeout_ms")
            .and_then(Value::as_u64)
            .unwrap_or(15000);
        let timeout = Duration::from_millis(requested).min(self.timeout());
        if timeout.is_zero() {
            return Err(SessionError::Deadline);
        }
        let epoch = self.call(self.control.document_epoch()).await?;
        let expression = format!(
            "Boolean((function(){{{SCRIPT}}}).apply(null,{}))",
            json!(["condition", input])
        );
        let mut wait = self
            .call(self.control.start_condition_wait(&expression, timeout))
            .await?;
        let yielded = self.session.settings().yield_on_wait;
        let _parked = self.session.inner.execution.condition_wait(yielded);
        let matched = self
            .call_with_capacity(async { wait.finish().await.map_err(Into::into) }, !yielded)
            .await?;
        let navigation = matches!(
            input.get("kind").and_then(Value::as_str),
            Some("navigation" | "article")
        );
        if !navigation && epoch != self.call(self.control.document_epoch()).await? {
            self.control.fence();
            return Err(SessionError::Unknown);
        }
        if matched {
            self.call(self.control.surface_script("condition", &input))
                .await
        } else {
            Ok(json!({"state":"timeout"}))
        }
    }

    pub(crate) async fn surface_input(
        &self,
        input: &SurfaceInput,
        capture_epoch: u64,
    ) -> Result<OperationReceipt, SessionError> {
        let work_operation = self.operation()?;
        let (kind, operation_kind, authored) = match input {
            SurfaceInput::Click { .. } => (ActionKind::Click, "surface.click", ""),
            SurfaceInput::Fill { text, .. } => {
                (ActionKind::EnterText, "surface.fill", text.as_str())
            }
            SurfaceInput::Key { key, .. } => (ActionKind::EnterText, "surface.key", key.as_str()),
            SurfaceInput::Scroll { .. } => (ActionKind::Scroll, "surface.scroll", ""),
        };
        self.authorize(kind, authored)?;
        let node_id = match input {
            SurfaceInput::Click { node }
            | SurfaceInput::Fill { node, .. }
            | SurfaceInput::Key { node, .. } => Some(*node),
            SurfaceInput::Scroll { .. } => None,
        };
        super::evidence::capture_surface_before(self, work_operation.id(), node_id, capture_epoch)
            .await;
        let result = self
            .call(self.control.surface_input(input))
            .await
            .map(|()| json!({"native_surface":true}));
        super::evidence::capture_surface_after(
            self,
            work_operation.id(),
            node_id,
            capture_epoch,
            result.is_err(),
        )
        .await;
        self.receipt_with_id_without_auto_evidence_after(
            work_operation.id().to_owned(),
            operation_kind,
            result,
        )
        .await
    }

    /// Resolves a current capture-bound Surface node into a safe screenshot rectangle.
    ///
    /// This does not acquire Work's operation lock; callers already own it. The provider checks
    /// the capture epoch, document, URL, node liveness, visibility, and retained signature before
    /// returning page coordinates. The returned native epoch protects the later pixel capture.
    pub(crate) async fn surface_target_region_unlocked(
        &self,
        node_id: u64,
        capture_epoch: u64,
    ) -> Result<(ScreenshotRegion, u64), SessionError> {
        let input = json!({"id":node_id,"expected_epoch":capture_epoch});
        let value = self
            .call(self.control.surface_script("target_region", &input))
            .await?;
        if value.get("valid") != Some(&Value::Bool(true))
            || value.get("coordinate_space").and_then(Value::as_str) != Some("page")
        {
            return Err(SessionError::EvidenceUnavailable);
        }
        let coordinate = |field: &str| {
            value
                .get(field)
                .and_then(Value::as_u64)
                .and_then(|number| u32::try_from(number).ok())
                .ok_or(SessionError::EvidenceUnavailable)
        };
        let x = coordinate("x")?;
        let y = coordinate("y")?;
        let width = coordinate("width")?;
        let height = coordinate("height")?;
        if width == 0 || height == 0 {
            return Err(SessionError::EvidenceUnavailable);
        }
        let native_epoch = value
            .get("native_document_epoch")
            .and_then(Value::as_u64)
            .ok_or(SessionError::EvidenceUnavailable)?;
        Ok((
            ScreenshotRegion::BoundingBox {
                x,
                y,
                width,
                height,
            },
            native_epoch,
        ))
    }

    pub(crate) async fn surface_ax(&self, depth: usize) -> Result<Value, SessionError> {
        let _operation = self.operation()?;
        if !self.session.settings().dom {
            return Err(SessionError::Denied);
        }
        let depth = i64::try_from(depth).map_err(|_| SessionError::InvalidInput)?;
        let value = self.call(self.control.surface_ax(Some(depth))).await?;
        if serde_json::to_vec(&value)
            .map_err(|_| SessionError::InvalidInput)?
            .len()
            > self.observation_limit()
        {
            return Err(SessionError::InvalidInput);
        }
        Ok(value)
    }
}
