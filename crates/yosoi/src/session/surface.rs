//! Trusted Surface adapters reuse Work admission without granting authored JavaScript.
use super::{ActionKind, SessionError, Work};
use crate::{automation_record::OperationReceipt, internal::browser::page::SurfaceInput};
use serde_json::{Value, json};
use std::time::Duration;

const SCRIPT: &str = include_str!("../surface/browser/extract.js");

impl Work {
    pub(crate) fn surface_session_cancellation(&self) -> tokio_util::sync::CancellationToken {
        self.session.inner.backend.cancellation()
    }

    pub(crate) async fn surface_start_network_subscription(
        &self,
        max_events: usize,
        max_buffered_events: usize,
        max_resource_buffer_bytes: usize,
        max_total_buffer_bytes: usize,
    ) -> Result<crate::internal::browser::controller::NetworkObservationSubscription, SessionError>
    {
        let _operation = self.operation()?;
        self.call(
            self.control
                .start_network_observation_subscription(
                    max_events,
                    max_buffered_events,
                    max_resource_buffer_bytes,
                    max_total_buffer_bytes,
                ),
        )
        .await
    }

    pub(crate) async fn surface_capture_network_body(
        &self,
        request_id: &str,
        max_bytes: usize,
    ) -> Result<crate::internal::browser::page::ObservationResponseBody, SessionError> {
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
            .map_or(15000, |value| value);
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
    ) -> Result<OperationReceipt, SessionError> {
        let _operation = self.operation()?;
        let (kind, operation, authored) = match input {
            SurfaceInput::Click { .. } => (ActionKind::Click, "surface.click", ""),
            SurfaceInput::Fill { text, .. } => {
                (ActionKind::EnterText, "surface.fill", text.as_str())
            }
            SurfaceInput::Key { key, .. } => (ActionKind::EnterText, "surface.key", key.as_str()),
            SurfaceInput::Scroll { .. } => (ActionKind::Scroll, "surface.scroll", ""),
        };
        self.authorize(kind, authored)?;
        let result = self
            .call(self.control.surface_input(input))
            .await
            .map(|()| json!({"native_surface":true}));
        self.receipt(operation, result).await
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
