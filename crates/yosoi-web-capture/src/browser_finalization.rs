//! Provider-neutral publication of validated browser adapter facts.

mod artifacts;
mod references;
mod resolution;
mod termination;

use chrono::{DateTime, TimeDelta, Utc};
use thiserror::Error;

use crate::{
    AccessibilityTreeArtifact, AcquisitionFinalizationError, AcquisitionFinalizationPlan,
    BrowserAdapterResult, ByteAccounting, ByteCount, CaptureBundle, CaptureBundleError,
    CaptureEnvironment, CookieArtifact, LayoutArtifact, NetworkArtifact, RenderedDomArtifact,
    RuntimeDiagnosticsArtifact, SourceArtifact, StorageArtifact, VisualArtifact,
    WebArtifactManifest, WebArtifactResults, finalize_acquisition,
};

use self::{
    artifacts::{decoded_source_result, family_result, loss_bytes, source_representation_result},
    references::web_reference,
    resolution::derive_resolution,
    termination::{activity_outcome, convert_termination},
};

#[derive(Clone, Debug)]
pub struct BrowserFinalizationInput {
    pub finished_at: DateTime<Utc>,
    pub resource_origin: crate::Observation<crate::ObservedWebOrigin>,
    pub initiator_origin: crate::Observation<crate::ObservedWebOrigin>,
}

#[derive(Debug, Error)]
pub enum BrowserFinalizationError {
    #[error("browser finalization wall-clock anchors do not cover the observed interval")]
    InvalidWallClock,
    #[error("browser artifact timestamp falls outside the certified capture window")]
    ArtifactTimestampOutsideWindow,
    #[error("browser artifact timestamps are not monotonically ordered")]
    ArtifactTimestampsUnordered,
    #[error("browser adapter result is missing its live acquisition lifecycle")]
    MissingLifecycle,
    #[error("browser network URL facts contradict the supplied resolution")]
    ResolutionMismatch,
    #[error("discarded staging lacks a durable artifact descriptor")]
    DiscardedMetadataUnavailable,
    #[error("browser byte-domain termination lacks its exact configured domain bound")]
    ByteDomainLimitMismatch,
    #[error("browser finalization invariant failed: {0}")]
    Invariant(&'static str),
    #[error(transparent)]
    Bundle(#[from] CaptureBundleError),
}

/// Feeds real terminal browser aggregates into the lifecycle created at attempt start.
pub fn adopt_browser_accounting(
    lifecycle: &mut crate::BoundedAcquisitionLifecycle,
    terminal: &crate::BrowserAdapterTerminal,
    facts: &crate::BrowserAdapterFacts,
) -> Result<(), BrowserFinalizationError> {
    let termination = convert_termination(terminal, facts.spec(), facts.settlement())?;
    let bytes = facts.bytes();
    let bytes = ByteAccounting::new(
        ByteCount::new(bytes.observed()),
        ByteCount::new(bytes.retained()),
        loss_bytes(bytes.lost())?,
    )
    .map_err(|_| BrowserFinalizationError::Invariant("byte accounting"))?;
    let state = crate::TerminalObservationState::new(
        facts.observed_through(),
        facts.events().clone(),
        bytes,
        facts.terminal_in_flight(),
    );
    lifecycle
        .adopt_accounting(&state, &termination)
        .map_err(|_| BrowserFinalizationError::Invariant("capture lifecycle accounting"))
}

pub fn finalize_browser_capture(
    result: BrowserAdapterResult,
    input: BrowserFinalizationInput,
) -> Result<CaptureBundle, BrowserFinalizationError> {
    let (_state, terminal, facts, lifecycle, browser_execution) = result.into_finalization_parts();
    let lifecycle = lifecycle.ok_or(BrowserFinalizationError::MissingLifecycle)?;
    let started_at = lifecycle.started_at();
    let parts = facts.into_parts();
    let elapsed = i64::try_from(parts.observed_through.as_microseconds())
        .map_err(|_| BrowserFinalizationError::InvalidWallClock)?;
    let expected_finished = started_at
        .checked_add_signed(TimeDelta::microseconds(elapsed))
        .ok_or(BrowserFinalizationError::InvalidWallClock)?;
    if input.finished_at < expected_finished {
        return Err(BrowserFinalizationError::InvalidWallClock);
    }
    let resolution = derive_resolution(
        &parts.spec,
        &parts.staging,
        input.resource_origin,
        input.initiator_origin,
    )?;
    let payloads: Vec<_> = parts
        .staging
        .slots()
        .iter()
        .filter_map(|slot| {
            slot.envelope().map(|envelope| {
                (
                    web_reference(slot.family(), envelope.reference()),
                    envelope.bytes().to_vec(),
                )
            })
        })
        .collect();

    let source_representation_evidence = parts
        .staging
        .source_representation()
        .and_then(crate::BrowserStagingSlot::envelope)
        .and_then(|envelope| crate::SourceRepresentationEvidence::from_json(envelope.bytes()).ok());
    let mut slots = parts.staging.into_parts().into_iter();
    let source = family_result(slots.next(), SourceArtifact::new, started_at)?;
    let source_representation = source_representation_result(slots.next(), started_at)?;
    let decoded_source = decoded_source_result(
        slots.next(),
        source_representation_evidence.as_ref(),
        started_at,
    )?;
    let rendered_dom = family_result(slots.next(), RenderedDomArtifact::new, started_at)?;
    let accessibility = family_result(slots.next(), AccessibilityTreeArtifact::new, started_at)?;
    let network = family_result(slots.next(), NetworkArtifact::new, started_at)?;
    let cookies = family_result(slots.next(), CookieArtifact::new, started_at)?;
    let storage = family_result(slots.next(), StorageArtifact::new, started_at)?;
    let layout = family_result(slots.next(), LayoutArtifact::new, started_at)?;
    let visual = family_result(slots.next(), VisualArtifact::new, started_at)?;
    let diagnostics = family_result(slots.next(), RuntimeDiagnosticsArtifact::new, started_at)?;
    let results = WebArtifactResults::new_with_derived_source(
        source,
        source_representation,
        decoded_source,
        rendered_dom,
        accessibility,
        network,
        cookies,
        storage,
        layout,
        visual,
        diagnostics,
    );
    let results_complete = results.all_complete_or_not_requested();
    let manifest = WebArtifactManifest::new(parts.spec.artifacts(), results)
        .map_err(|_| BrowserFinalizationError::Invariant("artifact manifest"))?;
    let has_preserved_evidence = !manifest.results().all_artifacts().is_empty();
    let termination = convert_termination(&terminal, &parts.spec, parts.settlement.as_ref())?;
    if lifecycle.termination() != Some(&termination) {
        return Err(BrowserFinalizationError::Invariant(
            "adapter terminal contradicts acquisition lifecycle",
        ));
    }
    let bytes = parts.bytes;
    let byte_accounting = ByteAccounting::new(
        ByteCount::new(bytes.observed()),
        ByteCount::new(bytes.retained()),
        loss_bytes(bytes.lost())?,
    )
    .map_err(|_| BrowserFinalizationError::Invariant("byte accounting"))?;
    let (outcome, signal) = activity_outcome(&terminal, results_complete, has_preserved_evidence)?;
    finalize_acquisition(AcquisitionFinalizationPlan {
        request: parts.spec.request().clone(),
        operation: parts.spec.operation().clone(),
        producer: parts.spec.producer().clone(),
        lifecycle,
        finished_at: input.finished_at,
        terminal_offset: parts.observed_through,
        events: parts.events,
        bytes: byte_accounting,
        in_flight: parts.terminal_in_flight,
        resolution,
        environment: CaptureEnvironment::Browser(Box::new(parts.environment)),
        capabilities: parts.spec.capabilities().profile().clone(),
        manifest,
        artifact_timestamp_order: crate::ArtifactTimestampOrder::IndependentFamilies,
        relationships: Vec::new(),
        payloads,
        activity_result: Some(crate::AcquisitionActivityResult::new(outcome, signal)),
        browser_execution,
        browser_challenge: Some(parts.challenge),
    })
    .map_err(map_acquisition_finalization_error)
}

const fn map_acquisition_finalization_error(
    error: AcquisitionFinalizationError,
) -> BrowserFinalizationError {
    match error {
        AcquisitionFinalizationError::ActivityOutcomeMismatch => {
            BrowserFinalizationError::Invariant("activity outcome")
        }
        AcquisitionFinalizationError::ActivityReason(_) => {
            BrowserFinalizationError::Invariant("activity reason")
        }
        AcquisitionFinalizationError::LifecycleNotStopped
        | AcquisitionFinalizationError::TerminalOffsetBehind { .. }
        | AcquisitionFinalizationError::TerminalOffsetMismatch
        | AcquisitionFinalizationError::Observation(_)
        | AcquisitionFinalizationError::Lifecycle(_) => {
            BrowserFinalizationError::Invariant("capture observation")
        }
        AcquisitionFinalizationError::ObservationWindow(_) => {
            BrowserFinalizationError::InvalidWallClock
        }
        AcquisitionFinalizationError::ArtifactTimestampOutsideWindow => {
            BrowserFinalizationError::ArtifactTimestampOutsideWindow
        }
        AcquisitionFinalizationError::ArtifactTimestampsUnordered => {
            BrowserFinalizationError::ArtifactTimestampsUnordered
        }
        AcquisitionFinalizationError::AcquisitionRecord(_) => {
            BrowserFinalizationError::ResolutionMismatch
        }
        AcquisitionFinalizationError::Bundle(error) => BrowserFinalizationError::Bundle(error),
        AcquisitionFinalizationError::ActivityReceipt(_) => {
            BrowserFinalizationError::Invariant("activity receipt")
        }
        AcquisitionFinalizationError::CaptureReceipt(_) => {
            BrowserFinalizationError::Invariant("capture receipt")
        }
        AcquisitionFinalizationError::WebCapture(_) => {
            BrowserFinalizationError::Invariant("web capture")
        }
    }
}
