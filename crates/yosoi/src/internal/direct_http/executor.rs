use crate::internal::direct_http as yosoi_web_capture_direct_http;

mod request_loop;

use chrono::{DateTime, Utc};
use std::time::{Duration, Instant, SystemTime};
use tokio_util::sync::CancellationToken;
use wreq::redirect::Policy;

use crate::internal::direct_http::{
    AttemptBoundary, BoundedAcquisitionLifecycle, CaptureOffset, DirectHttpFailure,
    DirectHttpRedirectTargetPolicy, DirectHttpTransportError, DirectHttpTransportProfile,
    HttpSessionUse, PendingDirectHttpResponse, ResolvedDirectHttpCaptureSpec, identity, lifecycle,
    termination,
};

/// Executes one validated standard-profile request through receipt of its response head.
///
/// Redirect behavior follows the resolved specification. The returned boundary owns the final
/// unconsumed content-coded body, complete resolution, lifecycle, and absolute deadline for the
/// bounded body stage. Character decoding and final capture construction remain later stages.
pub async fn execute_direct_http(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
) -> Result<PendingDirectHttpResponse, DirectHttpFailure> {
    let started_at: DateTime<Utc> = SystemTime::now().into();
    execute_direct_http_at(spec, cancellation, started_at).await
}

/// Executes with an explicitly injected wall-clock boundary for deterministic callers/tests.
pub async fn execute_direct_http_at(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
    started_at: DateTime<Utc>,
) -> Result<PendingDirectHttpResponse, DirectHttpFailure> {
    execute_direct_http_at_with_redirect_policy(
        spec,
        cancellation,
        started_at,
        DirectHttpRedirectTargetPolicy::AllowHttpAndHttps,
    )
    .await
}

/// Executes with an explicit redirect-target policy.
pub async fn execute_direct_http_at_with_redirect_policy(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
    started_at: DateTime<Utc>,
    redirect_target_policy: DirectHttpRedirectTargetPolicy,
) -> Result<PendingDirectHttpResponse, DirectHttpFailure> {
    let client = match hardened_client(Duration::from_micros(
        spec.maximum_elapsed().as_microseconds(),
    )) {
        Ok(client) => client,
        Err(error) => {
            let lifecycle = lifecycle::start(&spec, started_at);
            return Err(termination::provider(
                spec,
                lifecycle,
                CaptureOffset::from_microseconds(0),
                None,
                DirectHttpTransportError::from_wreq(error),
            ));
        }
    };
    execute_direct_http_with_client_at(
        spec,
        cancellation,
        started_at,
        client,
        redirect_target_policy,
    )
    .await
}

fn hardened_client(timeout: Duration) -> Result<wreq::Client, wreq::Error> {
    wreq::Client::builder()
        .redirect(Policy::none())
        .referer(false)
        .no_gzip()
        .no_brotli()
        .no_deflate()
        .no_zstd()
        .timeout(timeout)
        .build()
}

/// Testable adapter seam. Callers cannot use it to alter the stable capture specification.
pub async fn execute_direct_http_with_client_at(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
    started_at: DateTime<Utc>,
    client: wreq::Client,
    redirect_target_policy: DirectHttpRedirectTargetPolicy,
) -> Result<PendingDirectHttpResponse, DirectHttpFailure> {
    let started = Instant::now();
    let lifecycle = lifecycle::start(&spec, started_at);
    let boundary = match AttemptBoundary::new(started, spec.maximum_elapsed().duration()) {
        Ok(boundary) => boundary,
        Err(error) => {
            return Err(termination::provider(
                spec,
                lifecycle,
                CaptureOffset::from_microseconds(0),
                None,
                DirectHttpTransportError::identity(error),
            ));
        }
    };
    if let Err(error) = validate_strategy(&spec) {
        return Err(termination::provider(
            spec,
            lifecycle,
            CaptureOffset::from_microseconds(0),
            None,
            error,
        ));
    }
    let actual_producer = match identity::wreq_adapter_producer() {
        Ok(producer) => producer,
        Err(error) => return Err(provider_at_boundary(spec, lifecycle, boundary, error)),
    };
    if spec.producer() != &actual_producer {
        return Err(provider_at_boundary(
            spec,
            lifecycle,
            boundary,
            DirectHttpTransportError::producer_mismatch(),
        ));
    }
    let identity = match yosoi_web_capture_direct_http::DirectHttpExecutionIdentity::new(
        spec.strategy().user_agent(),
    ) {
        Ok(identity) => identity,
        Err(error) => return Err(provider_at_boundary(spec, lifecycle, boundary, error)),
    };
    request_loop::execute(
        spec,
        lifecycle,
        boundary,
        identity,
        client,
        cancellation,
        redirect_target_policy,
    )
    .await
}

fn provider_at_boundary(
    spec: ResolvedDirectHttpCaptureSpec,
    lifecycle: BoundedAcquisitionLifecycle,
    boundary: AttemptBoundary,
    error: DirectHttpTransportError,
) -> DirectHttpFailure {
    match boundary_offset(boundary) {
        Ok(offset) => termination::provider(spec, lifecycle, offset, None, error),
        Err(boundary_error) => termination::provider(
            spec,
            lifecycle,
            CaptureOffset::from_microseconds(0),
            None,
            boundary_error,
        ),
    }
}

const fn validate_strategy(
    spec: &ResolvedDirectHttpCaptureSpec,
) -> Result<(), DirectHttpTransportError> {
    if !matches!(
        spec.strategy().transport_profile(),
        DirectHttpTransportProfile::Standard
    ) {
        return Err(DirectHttpTransportError::unsupported_profile());
    }
    if !matches!(spec.strategy().session(), HttpSessionUse::Isolated) {
        return Err(DirectHttpTransportError::unsupported_session());
    }
    Ok(())
}

pub(super) fn boundary_offset(
    boundary: AttemptBoundary,
) -> Result<CaptureOffset, DirectHttpTransportError> {
    boundary
        .bounded_offset_at(Instant::now())
        .map_err(DirectHttpTransportError::identity)
}
