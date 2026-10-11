use std::time::SystemTime;

use chrono::{DateTime, Utc};
use tokio_util::sync::CancellationToken;

use crate::internal::direct_http::{
    ActivityCount, ArtifactFamilyResult, BoundedAcquisitionLifecycle, ByteCount,
    CaptureEnvironment, CaptureOffset, CaptureResolution, DirectHttpExecutionIdentity,
    DirectHttpRedirectTargetPolicy, DirectHttpResponseFacts, EventCount, InFlightActivity,
    LifecycleFinalizationInput, MeasuredCount, ResolvedDirectHttpCaptureSpec, ResponseBodyOutcome,
    WebArtifactManifest, WebArtifactResults, WebProviderCapabilityProfile, consume_response_body,
    execute_direct_http_at, execute_direct_http_at_with_redirect_policy,
    finalize_direct_http_attempt,
};
#[cfg(test)]
use wreq::Client;

use super::{
    DirectHttpCapture, DirectHttpCaptureError, DirectHttpCaptureEvidence,
    DirectHttpConstructionError,
};

#[cfg(test)]
use crate::internal::direct_http::{
    body::{PayloadSink, consume_with_sink, consume_with_sink_forced_invariant_failure},
    execute_direct_http_with_client_at,
};

/// Explicit wall-clock samples used by deterministic orchestration tests.
#[derive(Clone, Debug)]
#[allow(
    clippy::struct_field_names,
    reason = "timestamp names preserve the existing capture contract"
)]
pub struct DirectHttpCaptureTimestamps {
    pub started_at: DateTime<Utc>,
    pub source_generated_at: DateTime<Utc>,
    pub decoded_generated_at: DateTime<Utc>,
    pub finished_at: DateTime<Utc>,
}

/// Executes, processes, classifies, constructs, and publishes one capture bundle.
pub async fn capture_direct_http(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
) -> Result<DirectHttpCapture, DirectHttpCaptureError> {
    capture_direct_http_with_redirect_policy(
        spec,
        cancellation,
        DirectHttpRedirectTargetPolicy::AllowHttpAndHttps,
    )
    .await
}

/// Executes a full bounded attempt while applying the policy-selected redirect target rule.
pub async fn capture_direct_http_with_redirect_policy(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
    redirect_target_policy: DirectHttpRedirectTargetPolicy,
) -> Result<DirectHttpCapture, DirectHttpCaptureError> {
    let started_at: DateTime<Utc> = SystemTime::now().into();
    Box::pin(capture_direct_http_at_with_redirect_policy(
        spec,
        cancellation,
        started_at,
        redirect_target_policy,
    ))
    .await
}

/// Deterministic wall-clock seam; the monotonic absolute deadline remains transport-owned.
pub async fn capture_direct_http_at(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
    started_at: DateTime<Utc>,
) -> Result<DirectHttpCapture, DirectHttpCaptureError> {
    capture_direct_http_at_with_redirect_policy(
        spec,
        cancellation,
        started_at,
        DirectHttpRedirectTargetPolicy::AllowHttpAndHttps,
    )
    .await
}

/// Deterministic start-time seam with an explicit redirect target policy.
pub async fn capture_direct_http_at_with_redirect_policy(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
    started_at: DateTime<Utc>,
    redirect_target_policy: DirectHttpRedirectTargetPolicy,
) -> Result<DirectHttpCapture, DirectHttpCaptureError> {
    let pending = execute_direct_http_at_with_redirect_policy(
        spec.clone(),
        cancellation,
        started_at,
        redirect_target_policy,
    )
    .await
    .map_err(DirectHttpCaptureError::Transport)?;
    let (body, lifecycle, response, resolution, identity) =
        Box::pin(consume_response_body(pending, cancellation))
            .await
            .map_err(DirectHttpCaptureError::Body)?;
    // Wall-clock completion is sampled at the artifact/finalization boundary; monotonic
    // lifecycle offsets remain the authority for elapsed-time accounting.
    let source_generated_at: DateTime<Utc> = SystemTime::now().into();
    let decoded_generated_at: DateTime<Utc> = SystemTime::now().into();
    let finished_at: DateTime<Utc> = SystemTime::now().into();
    finish_capture(
        spec,
        body,
        lifecycle,
        response,
        resolution,
        identity,
        source_generated_at,
        decoded_generated_at,
        finished_at,
    )
}

#[cfg(test)]
pub(in crate::internal::direct_http) async fn capture_direct_http_with_client_at(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
    started_at: DateTime<Utc>,
    client: Client,
) -> Result<DirectHttpCapture, DirectHttpCaptureError> {
    let pending = execute_direct_http_with_client_at(
        spec.clone(),
        cancellation,
        started_at,
        client,
        DirectHttpRedirectTargetPolicy::AllowHttpAndHttps,
    )
    .await
    .map_err(DirectHttpCaptureError::Transport)?;
    let (body, lifecycle, response, resolution, identity) =
        Box::pin(consume_response_body(pending, cancellation))
            .await
            .map_err(DirectHttpCaptureError::Body)?;
    finish_capture(
        spec, body, lifecycle, response, resolution, identity, started_at, started_at, started_at,
    )
}

#[cfg(test)]
pub(in crate::internal::direct_http) async fn capture_direct_http_with_sink_at(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
    started_at: DateTime<Utc>,
    sink: Box<dyn PayloadSink>,
    force_invariant_failure: bool,
) -> Result<DirectHttpCapture, DirectHttpCaptureError> {
    let pending = execute_direct_http_at(spec.clone(), cancellation, started_at)
        .await
        .map_err(DirectHttpCaptureError::Transport)?;
    let consumed = if force_invariant_failure {
        Box::pin(consume_with_sink_forced_invariant_failure(
            pending,
            cancellation,
            sink,
        ))
        .await
    } else {
        Box::pin(consume_with_sink(pending, cancellation, sink)).await
    };
    let (body, lifecycle, response, resolution, identity) =
        consumed.map_err(DirectHttpCaptureError::Body)?;
    finish_capture(
        spec, body, lifecycle, response, resolution, identity, started_at, started_at, started_at,
    )
}

#[allow(
    clippy::too_many_arguments,
    reason = "keeps timing and response lifecycle evidence explicit at finalization"
)]
fn finish_capture(
    spec: ResolvedDirectHttpCaptureSpec,
    body: ResponseBodyOutcome,
    lifecycle: BoundedAcquisitionLifecycle,
    response: DirectHttpResponseFacts,
    resolution: CaptureResolution,
    identity: DirectHttpExecutionIdentity,
    source_generated_at: DateTime<Utc>,
    decoded_generated_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
) -> Result<DirectHttpCapture, DirectHttpCaptureError> {
    let terminal_offset = lifecycle.observed_through();
    let environment = identity.environment().clone();
    let capabilities = identity.capabilities().clone();
    let result = construct(
        spec,
        body,
        lifecycle,
        response,
        resolution,
        environment,
        capabilities,
        identity,
        source_generated_at,
        decoded_generated_at,
        finished_at,
        terminal_offset,
    );
    result.map_err(|(source, evidence)| DirectHttpCaptureError::Finalization {
        source,
        evidence: Box::new(evidence),
    })
}

/// Deterministic construction-time seam. Transport deadlines remain monotonic.
pub async fn capture_direct_http_with_clock(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
    timestamps: DirectHttpCaptureTimestamps,
) -> Result<DirectHttpCapture, DirectHttpCaptureError> {
    let pending = execute_direct_http_at(spec.clone(), cancellation, timestamps.started_at)
        .await
        .map_err(DirectHttpCaptureError::Transport)?;
    let (body, lifecycle, response, resolution, identity) =
        Box::pin(consume_response_body(pending, cancellation))
            .await
            .map_err(DirectHttpCaptureError::Body)?;
    finish_capture(
        spec,
        body,
        lifecycle,
        response,
        resolution,
        identity,
        timestamps.source_generated_at,
        timestamps.decoded_generated_at,
        timestamps.finished_at,
    )
}

#[allow(
    clippy::too_many_arguments,
    reason = "constructs one bundle from independently bounded evidence and lifecycle facts"
)]
#[allow(
    clippy::result_large_err,
    reason = "construction failure returns its typed error with retained capture evidence"
)]
fn construct(
    spec: ResolvedDirectHttpCaptureSpec,
    body: ResponseBodyOutcome,
    lifecycle: BoundedAcquisitionLifecycle,
    response: DirectHttpResponseFacts,
    resolution: CaptureResolution,
    environment: CaptureEnvironment,
    capabilities: WebProviderCapabilityProfile,
    identity: DirectHttpExecutionIdentity,
    source_generated_at: DateTime<Utc>,
    decoded_generated_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
    terminal_offset: CaptureOffset,
) -> Result<DirectHttpCapture, (DirectHttpConstructionError, DirectHttpCaptureEvidence)> {
    let unicode_limit = spec.content_limits().unicode_utf8_bytes().get();
    let mut evidence = DirectHttpCaptureEvidence {
        response: Some(response.clone()),
        resolution: Some(resolution.clone()),
        body: None,
        source_facts: None,
    };
    let built = build_artifacts(
        &spec,
        &body,
        &response,
        source_generated_at,
        decoded_generated_at,
    );
    let (
        source_result,
        source_representation_result,
        decoded_result,
        network_result,
        payloads,
        facts,
    ) = match built {
        Ok(value) => value,
        Err(error) => {
            if let DirectHttpConstructionError::UnsupportedSource { facts } = &error {
                evidence.source_facts = Some((**facts).clone());
            }
            evidence.body = Some(body);
            return Err((error, evidence));
        }
    };
    evidence.source_facts = facts;
    evidence.body = Some(body);
    let results = WebArtifactResults::new_with_derived_source(
        source_result,
        source_representation_result,
        decoded_result,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        network_result,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
    );
    let manifest = match WebArtifactManifest::new(spec.artifacts(), results) {
        Ok(value) => value,
        Err(error) => return Err((DirectHttpConstructionError::Manifest(error), evidence)),
    };
    let in_flight = match InFlightActivity::new(ActivityCount::new(0), ActivityCount::new(0)) {
        Ok(value) => value,
        Err(error) => return Err((DirectHttpConstructionError::InFlight(error), evidence)),
    };
    let (dropped_events, dropped_bytes) = lifecycle.dropped_counts();
    let input = LifecycleFinalizationInput {
        finished_at,
        terminal_offset,
        dropped_events: MeasuredCount::Known(EventCount::new(dropped_events)),
        dropped_bytes: MeasuredCount::Known(ByteCount::new(dropped_bytes)),
        in_flight,
        resolution,
        environment,
        capabilities,
        manifest,
        relationships: Vec::new(),
        payloads,
    };
    let source_facts = evidence.source_facts.clone();
    let bundle = finalize_direct_http_attempt(spec, lifecycle, input)
        .map_err(|e| (DirectHttpConstructionError::Lifecycle(e), evidence))?;
    Ok(DirectHttpCapture {
        bundle,
        response,
        source_facts,
        identity,
        unicode_limit,
    })
}

use super::artifacts::build_artifacts;
