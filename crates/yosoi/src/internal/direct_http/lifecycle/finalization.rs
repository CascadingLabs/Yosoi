use crate::internal::direct_http as yosoi_web_capture_direct_http;
use crate::internal::web_capture as yosoi_web_capture;

use super::LifecycleError;
use crate::internal::direct_http::LifecycleFinalizationInput;
use crate::internal::direct_http::{
    AcquisitionFinalizationError, AcquisitionFinalizationPlan, ByteAccounting, ByteCount,
    CaptureBundle, EventAccounting, EventCount, ResolvedDirectHttpCaptureSpec, WebArtifactManifest,
    finalize_acquisition,
};

#[allow(
    clippy::needless_pass_by_value,
    reason = "finalization consumes lifecycle ownership"
)]
pub(super) fn finalize(
    spec: ResolvedDirectHttpCaptureSpec,
    lifecycle: yosoi_web_capture_direct_http::BoundedAcquisitionLifecycle,
    input: LifecycleFinalizationInput,
) -> Result<CaptureBundle, LifecycleError> {
    if input.manifest.requests() != &spec.artifacts() {
        return Err(LifecycleError::ManifestMismatch);
    }
    validate_output_schemas(&spec, &input.manifest)?;
    let events = EventAccounting::new(
        EventCount::new(lifecycle.admitted_events()),
        EventCount::new(lifecycle.retained_events()),
        input.dropped_events,
    )
    .map_err(LifecycleError::EventAccounting)?;
    let bytes = ByteAccounting::new(
        ByteCount::new(lifecycle.admitted_bytes()),
        ByteCount::new(lifecycle.retained_bytes()),
        input.dropped_bytes,
    )
    .map_err(LifecycleError::ByteAccounting)?;
    finalize_acquisition(AcquisitionFinalizationPlan {
        lifecycle,
        request: spec.request().clone(),
        operation: spec.operation().clone(),
        producer: spec.producer().clone(),
        finished_at: input.finished_at,
        terminal_offset: input.terminal_offset,
        events,
        bytes,
        in_flight: input.in_flight,
        resolution: input.resolution,
        environment: input.environment,
        capabilities: input.capabilities,
        manifest: input.manifest,
        artifact_timestamp_order: yosoi_web_capture::ArtifactTimestampOrder::ManifestOrder,
        relationships: input.relationships,
        payloads: input.payloads.into_entries(),
        activity_result: None,
        browser_execution: None,
        browser_challenge: None,
    })
    .map_err(map_finalization_error)
}

const fn map_finalization_error(error: AcquisitionFinalizationError) -> LifecycleError {
    match error {
        AcquisitionFinalizationError::LifecycleNotStopped => LifecycleError::StillRunning,
        AcquisitionFinalizationError::TerminalOffsetBehind { terminal, observed } => {
            LifecycleError::TerminalOffsetBehind { terminal, observed }
        }
        AcquisitionFinalizationError::TerminalOffsetMismatch => {
            LifecycleError::TerminalOffsetMismatch
        }
        AcquisitionFinalizationError::ActivityOutcomeMismatch => {
            LifecycleError::ActivityOutcomeMismatch
        }
        AcquisitionFinalizationError::ActivityReason(error) => LifecycleError::Reason(error),
        AcquisitionFinalizationError::Lifecycle(error) => {
            LifecycleError::AcquisitionObservation(error)
        }
        AcquisitionFinalizationError::ArtifactTimestampOutsideWindow => {
            LifecycleError::ArtifactTimestampOutsideWindow
        }
        AcquisitionFinalizationError::ArtifactTimestampsUnordered => {
            LifecycleError::ArtifactTimestampsUnordered
        }
        AcquisitionFinalizationError::ObservationWindow(error) => {
            LifecycleError::ObservationWindow(error)
        }
        AcquisitionFinalizationError::Observation(error) => LifecycleError::Observation(error),
        AcquisitionFinalizationError::ActivityReceipt(error) => {
            LifecycleError::ActivityReceipt(error)
        }
        AcquisitionFinalizationError::CaptureReceipt(error) => {
            LifecycleError::CaptureReceipt(error)
        }
        AcquisitionFinalizationError::AcquisitionRecord(error) => {
            LifecycleError::AcquisitionRecord(error)
        }
        AcquisitionFinalizationError::WebCapture(error) => LifecycleError::WebCapture(error),
        AcquisitionFinalizationError::Bundle(error) => LifecycleError::Bundle(error),
    }
}

fn validate_output_schemas(
    spec: &ResolvedDirectHttpCaptureSpec,
    manifest: &WebArtifactManifest,
) -> Result<(), LifecycleError> {
    let schemas = spec.output_schemas();
    if let Some(artifacts) = manifest.results().source().artifacts()
        && artifacts
            .iter()
            .any(|artifact| artifact.metadata().provenance().schema() != schemas.source())
    {
        return Err(LifecycleError::SchemaMismatch {
            family: yosoi_web_capture_direct_http::WebArtifactFamily::Source,
        });
    }
    if let Some(artifacts) = manifest.results().decoded_source().artifacts() {
        let expected = schemas.unicode_view();
        if !matches!(
            spec.retention(),
            yosoi_web_capture_direct_http::SourceRetentionPolicy::RepresentationAndUnicodeView
        ) || artifacts.iter().any(|artifact| {
            expected.is_none_or(|schema| artifact.metadata().provenance().schema() != schema)
        }) {
            return Err(LifecycleError::SchemaMismatch {
                family: yosoi_web_capture_direct_http::WebArtifactFamily::DecodedSource,
            });
        }
    }
    if let Some(artifacts) = manifest.results().network().artifacts() {
        let expected = schemas.network();
        if artifacts.iter().any(|artifact| {
            expected.is_none_or(|schema| artifact.metadata().provenance().schema() != schema)
        }) {
            return Err(LifecycleError::SchemaMismatch {
                family: yosoi_web_capture_direct_http::WebArtifactFamily::Network,
            });
        }
    }
    Ok(())
}
