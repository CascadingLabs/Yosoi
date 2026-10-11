use crate::internal::direct_http as yosoi_web_capture_direct_http;

use tokio::time::{Instant, timeout_at};
use tokio_util::sync::CancellationToken;
use wreq::header::USER_AGENT;

use super::boundary_offset;
use crate::internal::direct_http::{
    AttemptBoundary, BoundedAcquisitionLifecycle, CaptureOffset, DirectHttpExecutionIdentity,
    DirectHttpFailure, DirectHttpRedirectErrorKind, DirectHttpRedirectPolicy,
    DirectHttpRedirectTargetPolicy, DirectHttpResponseFacts, DirectHttpTransportError,
    DirectHttpTransportErrorKind, EventAdmission, LifecycleEvent, PendingDirectHttpResponse,
    RedirectHop, ResolvedDirectHttpCaptureSpec, redirect, termination,
};

#[allow(
    clippy::too_many_arguments,
    reason = "the request loop keeps its validated attempt context explicit"
)]
pub(super) async fn execute(
    spec: ResolvedDirectHttpCaptureSpec,
    mut lifecycle: BoundedAcquisitionLifecycle,
    boundary: AttemptBoundary,
    identity: DirectHttpExecutionIdentity,
    client: wreq::Client,
    cancellation: &CancellationToken,
    redirect_target_policy: DirectHttpRedirectTargetPolicy,
) -> Result<PendingDirectHttpResponse, DirectHttpFailure> {
    let deadline = Instant::from_std(boundary.deadline());
    let initial = spec.target().as_resolved();
    let mut current = initial.clone();
    let mut visited = vec![current.clone()];
    let mut redirects = Vec::<RedirectHop>::new();

    loop {
        // Before the first response there is no resolution evidence: the
        // requested target is intent, not an observed final URL. After a
        // followed redirect, the current URL and hop chain are observed facts
        // even if acquiring that current URL later fails.
        let prior_resolution = if redirects.is_empty() {
            None
        } else {
            match redirect::resolution(&current, redirects.clone()) {
                Ok(resolution) => Some(resolution),
                Err(error) => {
                    return Err(provider_at_boundary(
                        spec,
                        lifecycle,
                        boundary,
                        None,
                        DirectHttpTransportError::resolution(error),
                    ));
                }
            }
        };
        let request = client.get(current.as_str());
        let request = match spec.strategy().user_agent() {
            Some(user_agent) => request.header(USER_AGENT, user_agent.as_str()),
            None => request,
        }
        .send();
        let response = tokio::select! {
            biased;
            () = cancellation.cancelled() => {
                let offset = match boundary_offset(boundary) {
                    Ok(offset) => offset,
                    Err(error) => return Err(termination::provider(
                        spec,
                        lifecycle,
                        CaptureOffset::from_microseconds(0),
                        prior_resolution,
                        error,
                    )),
                };
                return Err(termination::caller(
                    spec,
                    lifecycle,
                    offset,
                    prior_resolution,
                    DirectHttpTransportError::cancelled(),
                ));
            },
            result = timeout_at(deadline, request) => match result {
                Ok(Ok(response)) => response,
                Ok(Err(error)) => {
                    let error = DirectHttpTransportError::from_wreq(error);
                    if error.kind() == DirectHttpTransportErrorKind::Timeout {
                        return Err(termination::deadline(spec, lifecycle, prior_resolution, error));
                    }
                    return Err(provider_at_boundary(
                        spec,
                        lifecycle,
                        boundary,
                        prior_resolution,
                        error,
                    ));
                }
                Err(_) => return Err(termination::deadline(
                    spec,
                    lifecycle,
                    prior_resolution,
                    DirectHttpTransportError::timeout(),
                )),
            }
        };

        let resolution = match redirect::resolution(&current, redirects.clone()) {
            Ok(resolution) => resolution,
            Err(error) => {
                return Err(termination::protocol(
                    spec,
                    lifecycle,
                    CaptureOffset::from_microseconds(0),
                    response,
                    prior_resolution,
                    DirectHttpTransportError::resolution(error),
                ));
            }
        };

        let offset = match boundary_offset(boundary) {
            Ok(offset) => offset,
            Err(error) => {
                return Err(termination::provider(
                    spec,
                    lifecycle,
                    CaptureOffset::from_microseconds(0),
                    Some(resolution),
                    error,
                ));
            }
        };
        if let Err(error) = admit_response_head(&mut lifecycle, offset) {
            if lifecycle.termination().is_some() {
                return Err(DirectHttpFailure {
                    spec: Box::new(spec),
                    lifecycle: Box::new(lifecycle),
                    error,
                    response: Some(Box::new(response)),
                    resolution: Some(Box::new(resolution)),
                    termination_failure: None,
                });
            }
            return Err(termination::protocol(
                spec,
                lifecycle,
                offset,
                response,
                Some(resolution),
                error,
            ));
        }
        let Some(status) = redirect::status(&response) else {
            return pending_response(
                response, spec, lifecycle, identity, boundary, resolution, offset,
            );
        };
        if matches!(spec.redirects(), DirectHttpRedirectPolicy::Disabled) {
            return pending_response(
                response, spec, lifecycle, identity, boundary, resolution, offset,
            );
        }
        let max_hops = match spec.redirects() {
            DirectHttpRedirectPolicy::Follow { max_hops } => max_hops.get(),
            DirectHttpRedirectPolicy::Disabled => 0,
        };
        let hop_limit_reached =
            usize::try_from(max_hops).map_or(true, |max_hops| redirects.len() >= max_hops);
        if hop_limit_reached {
            return Err(termination::redirect(
                spec,
                lifecycle,
                offset,
                response,
                resolution,
                DirectHttpTransportError::redirect(DirectHttpRedirectErrorKind::HopLimit),
            ));
        }
        let target = match redirect::target(&response, &current) {
            Ok(target) => target,
            Err(kind) => {
                return Err(termination::redirect(
                    spec,
                    lifecycle,
                    offset,
                    response,
                    resolution,
                    DirectHttpTransportError::redirect(kind),
                ));
            }
        };
        if !redirect::allowed(redirect_target_policy, &initial, &target) {
            return Err(termination::redirect(
                spec,
                lifecycle,
                offset,
                response,
                resolution,
                DirectHttpTransportError::redirect(DirectHttpRedirectErrorKind::TargetRefused),
            ));
        }
        if redirect::repeated(&visited, &target) {
            return Err(termination::redirect(
                spec,
                lifecycle,
                offset,
                response,
                resolution,
                DirectHttpTransportError::redirect(DirectHttpRedirectErrorKind::Loop),
            ));
        }
        redirects.push(redirect::hop(current, target.clone(), status));
        visited.push(target.clone());
        current = target;
    }
}

fn provider_at_boundary(
    spec: ResolvedDirectHttpCaptureSpec,
    lifecycle: BoundedAcquisitionLifecycle,
    boundary: AttemptBoundary,
    resolution: Option<yosoi_web_capture_direct_http::CaptureResolution>,
    error: DirectHttpTransportError,
) -> DirectHttpFailure {
    match boundary_offset(boundary) {
        Ok(offset) => termination::provider(spec, lifecycle, offset, resolution, error),
        Err(boundary_error) => termination::provider(
            spec,
            lifecycle,
            CaptureOffset::from_microseconds(0),
            resolution,
            boundary_error,
        ),
    }
}

#[allow(
    clippy::too_many_arguments,
    reason = "pending response construction retains the complete attempt context"
)]
fn pending_response(
    response: wreq::Response,
    spec: ResolvedDirectHttpCaptureSpec,
    lifecycle: BoundedAcquisitionLifecycle,
    identity: DirectHttpExecutionIdentity,
    boundary: AttemptBoundary,
    resolution: yosoi_web_capture_direct_http::CaptureResolution,
    offset: CaptureOffset,
) -> Result<PendingDirectHttpResponse, DirectHttpFailure> {
    let facts = match DirectHttpResponseFacts::observe(spec.target(), &response) {
        Ok(facts) => facts,
        Err(error) => {
            return Err(termination::protocol(
                spec,
                lifecycle,
                offset,
                response,
                Some(resolution),
                error,
            ));
        }
    };
    Ok(PendingDirectHttpResponse::new(
        response, spec, facts, resolution, lifecycle, identity, boundary,
    ))
}

fn admit_response_head(
    lifecycle: &mut BoundedAcquisitionLifecycle,
    offset: CaptureOffset,
) -> Result<(), DirectHttpTransportError> {
    let head = LifecycleEvent::new(
        offset,
        yosoi_web_capture_direct_http::ByteCount::new(0),
        yosoi_web_capture_direct_http::ByteCount::new(0),
        true,
    )
    .map_err(DirectHttpTransportError::lifecycle_event)?;
    match lifecycle
        .admit(head)
        .map_err(|error| DirectHttpTransportError::lifecycle(error.into()))?
    {
        EventAdmission::Admitted(_) => Ok(()),
        EventAdmission::AdmittedAndStopped { .. } | EventAdmission::NotAdmittedAndStopped(_) => {
            Err(DirectHttpTransportError::timeout())
        }
    }
}
