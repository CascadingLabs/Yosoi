use crate::internal::direct_http as yosoi_web_capture_direct_http;

use std::time::Instant;

use crate::internal::types::ReasonCode;

use crate::internal::direct_http::{
    CaptureOffset, ControllerStopReason, InterruptionEvidence, InterruptionInitiator, LifecycleStop,
};

use super::{BodyTerminal, ResponseBodyError};

pub(super) fn current_offset(
    boundary: yosoi_web_capture_direct_http::AttemptBoundary,
) -> Result<CaptureOffset, ResponseBodyError> {
    boundary
        .bounded_offset_at(Instant::now())
        .map_err(ResponseBodyError::AttemptBoundary)
}

pub(super) const fn maximum_offset(
    boundary: yosoi_web_capture_direct_http::AttemptBoundary,
) -> CaptureOffset {
    CaptureOffset::from_microseconds(boundary.maximum_elapsed().as_microseconds())
}

pub(super) fn stop(
    lifecycle: &mut yosoi_web_capture_direct_http::BoundedAcquisitionLifecycle,
    terminal: BodyTerminal,
    offset: CaptureOffset,
) -> Result<(), ResponseBodyError> {
    if lifecycle.termination().is_some() {
        return Ok(());
    }
    let action = match terminal {
        BodyTerminal::Complete => LifecycleStop::Completed(ControllerStopReason::GoalSatisfied),
        BodyTerminal::Cancelled => LifecycleStop::Interrupted(InterruptionEvidence::new(
            InterruptionInitiator::Caller,
            reason("web_capture.direct_http.body_cancelled")?,
        )),
        _ => LifecycleStop::Interrupted(InterruptionEvidence::new(
            InterruptionInitiator::Provider,
            reason("web_capture.direct_http.body_incomplete")?,
        )),
    };
    lifecycle
        .stop(offset, action)
        .map_err(|error| ResponseBodyError::Lifecycle(error.into()))
}

fn reason(value: &'static str) -> Result<ReasonCode, ResponseBodyError> {
    ReasonCode::new(value)
        .map_err(yosoi_web_capture_direct_http::LifecycleError::Reason)
        .map_err(ResponseBodyError::Lifecycle)
}
