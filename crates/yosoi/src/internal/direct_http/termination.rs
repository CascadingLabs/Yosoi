#[cfg(test)]
use crate::internal::direct_http as yosoi_web_capture_direct_http;

use crate::internal::types::ReasonCode;

use crate::internal::direct_http::{
    BoundedAcquisitionLifecycle, CaptureOffset, CaptureResolution, InterruptionEvidence,
    InterruptionInitiator, LifecycleStop, ResolvedDirectHttpCaptureSpec,
};

use super::{DirectHttpFailure, DirectHttpTerminationFailure, DirectHttpTransportError};

pub(super) fn provider(
    spec: ResolvedDirectHttpCaptureSpec,
    lifecycle: BoundedAcquisitionLifecycle,
    offset: CaptureOffset,
    resolution: Option<CaptureResolution>,
    error: DirectHttpTransportError,
) -> DirectHttpFailure {
    interrupted(
        spec,
        lifecycle,
        offset,
        None,
        resolution,
        error,
        InterruptionInitiator::Provider,
        "web_capture.direct_http.provider_failure",
    )
}

pub(super) fn caller(
    spec: ResolvedDirectHttpCaptureSpec,
    lifecycle: BoundedAcquisitionLifecycle,
    offset: CaptureOffset,
    resolution: Option<CaptureResolution>,
    error: DirectHttpTransportError,
) -> DirectHttpFailure {
    interrupted(
        spec,
        lifecycle,
        offset,
        None,
        resolution,
        error,
        InterruptionInitiator::Caller,
        "web_capture.direct_http.cancelled",
    )
}

pub(super) fn redirect(
    spec: ResolvedDirectHttpCaptureSpec,
    lifecycle: BoundedAcquisitionLifecycle,
    offset: CaptureOffset,
    response: wreq::Response,
    resolution: CaptureResolution,
    error: DirectHttpTransportError,
) -> DirectHttpFailure {
    interrupted(
        spec,
        lifecycle,
        offset,
        Some(response),
        Some(resolution),
        error,
        InterruptionInitiator::Provider,
        "web_capture.direct_http.redirect_policy",
    )
}

pub(super) fn protocol(
    spec: ResolvedDirectHttpCaptureSpec,
    lifecycle: BoundedAcquisitionLifecycle,
    offset: CaptureOffset,
    response: wreq::Response,
    resolution: Option<CaptureResolution>,
    error: DirectHttpTransportError,
) -> DirectHttpFailure {
    interrupted(
        spec,
        lifecycle,
        offset,
        Some(response),
        resolution,
        error,
        InterruptionInitiator::Provider,
        "web_capture.direct_http.protocol_failure",
    )
}

#[allow(
    clippy::too_many_arguments,
    reason = "terminal evidence is kept explicit"
)]
fn interrupted(
    spec: ResolvedDirectHttpCaptureSpec,
    mut lifecycle: BoundedAcquisitionLifecycle,
    offset: CaptureOffset,
    response: Option<wreq::Response>,
    resolution: Option<CaptureResolution>,
    error: DirectHttpTransportError,
    initiator: InterruptionInitiator,
    reason: &'static str,
) -> DirectHttpFailure {
    let termination_failure = match ReasonCode::new(reason) {
        Ok(reason) => {
            let evidence = InterruptionEvidence::new(initiator, reason);
            lifecycle
                .stop(offset, LifecycleStop::Interrupted(evidence))
                .err()
                .map(Into::into)
                .map(DirectHttpTerminationFailure::Lifecycle)
        }
        Err(reason_error) => Some(DirectHttpTerminationFailure::InvalidReason(reason_error)),
    };
    DirectHttpFailure {
        spec: Box::new(spec),
        lifecycle: Box::new(lifecycle),
        error,
        response: response.map(Box::new),
        resolution: resolution.map(Box::new),
        termination_failure,
    }
}

pub(super) fn deadline(
    spec: ResolvedDirectHttpCaptureSpec,
    mut lifecycle: BoundedAcquisitionLifecycle,
    resolution: Option<CaptureResolution>,
    error: DirectHttpTransportError,
) -> DirectHttpFailure {
    let deadline = CaptureOffset::from_microseconds(spec.maximum_elapsed().as_microseconds());
    let termination_failure = if lifecycle.termination().is_some() {
        None
    } else {
        lifecycle
            .observe_through(deadline)
            .err()
            .map(Into::into)
            .map(DirectHttpTerminationFailure::Lifecycle)
    };
    DirectHttpFailure {
        spec: Box::new(spec),
        lifecycle: Box::new(lifecycle),
        error,
        response: None,
        resolution: resolution.map(Box::new),
        termination_failure,
    }
}

#[cfg(test)]
mod tests {
    use chrono::DateTime;

    use super::*;
    use crate::internal::direct_http::{lifecycle, tests::spec};

    #[test]
    fn stop_failure_is_secondary_and_preserves_primary_classification() {
        let started_at = DateTime::from_timestamp(1_700_000_000, 0).unwrap();
        let spec = spec("http://example.com/");
        let mut lifecycle = lifecycle::start(&spec, started_at);
        let reason = ReasonCode::new("web_capture.test.previously_stopped").unwrap();
        lifecycle
            .stop(
                CaptureOffset::from_microseconds(1),
                LifecycleStop::Interrupted(InterruptionEvidence::new(
                    InterruptionInitiator::Caller,
                    reason,
                )),
            )
            .unwrap();

        let redirect_kind = super::super::DirectHttpRedirectErrorKind::Loop;
        let failure = interrupted(
            spec,
            lifecycle,
            CaptureOffset::from_microseconds(2),
            None,
            None,
            DirectHttpTransportError::redirect(redirect_kind),
            InterruptionInitiator::Provider,
            "web_capture.direct_http.redirect_policy",
        );

        assert_eq!(
            failure.error().kind(),
            super::super::DirectHttpTransportErrorKind::Redirect(redirect_kind)
        );
        assert!(matches!(
            failure.termination_failure(),
            Some(DirectHttpTerminationFailure::Lifecycle(
                yosoi_web_capture_direct_http::LifecycleError::AlreadyStopped
            ))
        ));
        assert_eq!(
            failure.to_string(),
            "redirect traversal detected a repeated resource"
        );
    }
}
