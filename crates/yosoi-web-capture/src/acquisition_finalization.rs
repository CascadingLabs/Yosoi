//! Provider-neutral, atomic publication of one completed acquisition attempt.

use chrono::{DateTime, Utc};
use thiserror::Error;
use yosoi_types::{
    ActivityOutcome, ActivityReceipt, ActivityReceiptError, ActivitySignal, ArtifactRecord,
    CaptureReceipt, CaptureReceiptError, NamespacedIdError, OperationId, Producer, ReasonCode,
    RetryDisposition,
};

use crate::{
    AcquisitionObservationError, BoundedAcquisitionLifecycle, BrowserChallengeFact,
    BrowserExecutionReceipt, CaptureBundle, CaptureBundleError, CaptureEnvironment,
    CaptureObservationError, CaptureOffset, CaptureResolution, CaptureTermination, EventAccounting,
    InFlightActivity, InterruptionInitiator, ObservationWindowError, WebAcquisitionRecord,
    WebAcquisitionRecordError, WebArtifactManifest, WebArtifactRef, WebArtifactRelationship,
    WebCapture, WebCaptureError, WebCaptureRequest, WebProviderCapabilityProfile,
};

/// All already-validated provider facts needed to publish a capture atomically.
///
/// Transports retain ownership of collection, cancellation, redaction, and artifact staging.
/// This value centralizes only the provider-neutral receipt and aggregate boundary.
#[derive(Debug)]
pub struct AcquisitionFinalizationPlan {
    pub request: WebCaptureRequest,
    pub operation: OperationId,
    pub producer: Producer,
    pub lifecycle: BoundedAcquisitionLifecycle,
    pub finished_at: DateTime<Utc>,
    pub terminal_offset: CaptureOffset,
    pub events: EventAccounting,
    pub bytes: crate::ByteAccounting,
    pub in_flight: InFlightActivity,
    pub resolution: CaptureResolution,
    pub environment: CaptureEnvironment,
    pub capabilities: WebProviderCapabilityProfile,
    pub manifest: WebArtifactManifest,
    pub artifact_timestamp_order: ArtifactTimestampOrder,
    pub relationships: Vec<WebArtifactRelationship>,
    pub payloads: Vec<(WebArtifactRef, Vec<u8>)>,
    /// Optional transport-specific receipt result. When absent, the shared kernel derives one.
    pub activity_result: Option<AcquisitionActivityResult>,
    pub browser_execution: Option<BrowserExecutionReceipt>,
    pub browser_challenge: Option<BrowserChallengeFact>,
}

/// Defines whether manifest traversal is also meaningful capture chronology.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactTimestampOrder {
    /// Artifact families are produced in manifest order and must remain chronological.
    ManifestOrder,
    /// Families are independent; only the shared attempt window is authoritative.
    IndependentFamilies,
}

/// Validated receipt outcome requested by a transport with more specific terminal semantics.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AcquisitionActivityResult {
    outcome: ActivityOutcome,
    signal: Option<ActivitySignal>,
}

impl AcquisitionActivityResult {
    pub const fn new(outcome: ActivityOutcome, signal: Option<ActivitySignal>) -> Self {
        Self { outcome, signal }
    }

    pub const fn outcome(&self) -> ActivityOutcome {
        self.outcome
    }

    pub const fn signal(&self) -> Option<&ActivitySignal> {
        self.signal.as_ref()
    }

    pub fn into_parts(self) -> (ActivityOutcome, Option<ActivitySignal>) {
        (self.outcome, self.signal)
    }
}

#[derive(Debug, Error)]
pub enum AcquisitionFinalizationError {
    #[error("acquisition lifecycle must be stopped before publication")]
    LifecycleNotStopped,
    #[error("terminal offset {terminal} precedes lifecycle offset {observed}")]
    TerminalOffsetBehind { terminal: u64, observed: u64 },
    #[error("terminal offset does not agree with the stopped acquisition lifecycle")]
    TerminalOffsetMismatch,
    #[error("activity outcome contradicts the capture termination")]
    ActivityOutcomeMismatch,
    #[error("activity reason is invalid")]
    ActivityReason(#[source] NamespacedIdError),
    #[error("artifact generation timestamp is outside the observation window")]
    ArtifactTimestampOutsideWindow,
    #[error("artifact generation timestamps are not ordered")]
    ArtifactTimestampsUnordered,
    #[error("wall-clock observation window is invalid")]
    ObservationWindow(#[source] ObservationWindowError),
    #[error("capture observation is invalid")]
    Observation(#[source] CaptureObservationError),
    #[error("acquisition lifecycle completion is inconsistent")]
    Lifecycle(#[source] AcquisitionObservationError),
    #[error("activity receipt is invalid")]
    ActivityReceipt(#[source] ActivityReceiptError),
    #[error("capture receipt is invalid")]
    CaptureReceipt(#[source] CaptureReceiptError),
    #[error("acquisition record is invalid")]
    AcquisitionRecord(#[source] WebAcquisitionRecordError),
    #[error("web capture is invalid")]
    WebCapture(#[source] WebCaptureError),
    #[error("capture payload bundle is invalid")]
    Bundle(#[source] CaptureBundleError),
}

/// Validates and publishes one complete capture. No aggregate escapes on failure.
pub fn finalize_acquisition(
    plan: AcquisitionFinalizationPlan,
) -> Result<CaptureBundle, AcquisitionFinalizationError> {
    let started_at = plan.lifecycle.started_at();
    if plan.lifecycle.capture_id() != plan.request.capture_id() {
        return Err(AcquisitionFinalizationError::Lifecycle(
            AcquisitionObservationError::CaptureIdentityMismatch,
        ));
    }
    let termination = plan
        .lifecycle
        .termination()
        .cloned()
        .ok_or(AcquisitionFinalizationError::LifecycleNotStopped)?;
    let terminal = plan.terminal_offset.as_microseconds();
    let observed = plan.lifecycle.observed_through().as_microseconds();
    if terminal < observed {
        return Err(AcquisitionFinalizationError::TerminalOffsetBehind { terminal, observed });
    }
    if terminal != observed {
        return Err(AcquisitionFinalizationError::TerminalOffsetMismatch);
    }
    let activity_result = match plan.activity_result {
        Some(result) => result,
        None => derive_activity_result(&termination)?,
    };
    validate_activity_outcome(&termination, activity_result.outcome())?;
    let terminal = crate::TerminalObservationState::new(
        plan.terminal_offset,
        plan.events,
        plan.bytes,
        plan.in_flight,
    );
    let observation = plan
        .lifecycle
        .finish_from_accounting(plan.finished_at, terminal, termination)
        .map_err(|error| match error {
            AcquisitionObservationError::Window(error) => {
                AcquisitionFinalizationError::ObservationWindow(error)
            }
            AcquisitionObservationError::Observation(error) => {
                AcquisitionFinalizationError::Observation(error)
            }
            other => AcquisitionFinalizationError::Lifecycle(other),
        })?;
    validate_artifact_timestamps(
        started_at,
        plan.finished_at,
        &plan.manifest,
        plan.artifact_timestamp_order,
    )?;
    let outputs: Vec<ArtifactRecord> = plan
        .manifest
        .results()
        .all_artifacts()
        .into_iter()
        .map(|artifact| artifact.metadata().record().clone())
        .collect();
    let (activity_outcome, activity_signal) = activity_result.into_parts();
    let receipt = ActivityReceipt::new(
        plan.request.capture_id().activity_id(),
        plan.operation,
        plan.producer,
        Vec::new(),
        outputs,
        activity_outcome,
        activity_signal,
        started_at,
        plan.finished_at,
    )
    .map_err(AcquisitionFinalizationError::ActivityReceipt)?;
    let receipt = CaptureReceipt::new(plan.request.capture_id(), receipt)
        .map_err(AcquisitionFinalizationError::CaptureReceipt)?;
    let acquisition = WebAcquisitionRecord::new(plan.request, plan.resolution, receipt)
        .map_err(AcquisitionFinalizationError::AcquisitionRecord)?;
    let capture = WebCapture::finalize(
        acquisition,
        plan.environment,
        observation,
        plan.capabilities,
        plan.manifest,
        plan.relationships,
    )
    .map_err(AcquisitionFinalizationError::WebCapture)?;
    let capture = match plan.browser_execution {
        Some(receipt) => capture
            .with_browser_execution(receipt)
            .map_err(AcquisitionFinalizationError::WebCapture)?,
        None => capture,
    };
    let capture = match plan.browser_challenge {
        Some(fact) => capture
            .with_browser_challenge(fact)
            .map_err(AcquisitionFinalizationError::WebCapture)?,
        None => capture,
    };
    let mut builder = CaptureBundle::builder(capture);
    for (reference, bytes) in plan.payloads {
        builder
            .insert(reference, bytes)
            .map_err(AcquisitionFinalizationError::Bundle)?;
    }
    builder
        .finalize()
        .map_err(AcquisitionFinalizationError::Bundle)
}

fn derive_activity_result(
    termination: &CaptureTermination,
) -> Result<AcquisitionActivityResult, AcquisitionFinalizationError> {
    let (outcome, reason, retry) = match termination {
        CaptureTermination::Settled(_) | CaptureTermination::ControllerStopped(_) => {
            return Ok(AcquisitionActivityResult::new(
                ActivityOutcome::Succeeded,
                None,
            ));
        }
        CaptureTermination::DeadlineReached { .. } => (
            ActivityOutcome::Partial,
            "capture.deadline",
            RetryDisposition::NotRetryable,
        ),
        CaptureTermination::EventLimitReached { .. } => (
            ActivityOutcome::Partial,
            "capture.event-limit",
            RetryDisposition::NotRetryable,
        ),
        CaptureTermination::ByteLimitReached { .. } => (
            ActivityOutcome::Partial,
            "capture.byte-limit",
            RetryDisposition::NotRetryable,
        ),
        CaptureTermination::Interrupted(evidence) => {
            let outcome = if matches!(evidence.initiator(), InterruptionInitiator::Caller) {
                ActivityOutcome::Cancelled
            } else {
                ActivityOutcome::Partial
            };
            let retry = if matches!(evidence.initiator(), InterruptionInitiator::Caller) {
                RetryDisposition::Unknown
            } else {
                RetryDisposition::Retryable
            };
            return Ok(AcquisitionActivityResult::new(
                outcome,
                Some(ActivitySignal::new(evidence.reason().clone(), retry)),
            ));
        }
    };
    let reason = ReasonCode::new(reason).map_err(AcquisitionFinalizationError::ActivityReason)?;
    Ok(AcquisitionActivityResult::new(
        outcome,
        Some(ActivitySignal::new(reason, retry)),
    ))
}

fn validate_activity_outcome(
    termination: &CaptureTermination,
    outcome: ActivityOutcome,
) -> Result<(), AcquisitionFinalizationError> {
    let coherent = match termination {
        CaptureTermination::Settled(_) | CaptureTermination::ControllerStopped(_) => {
            matches!(
                outcome,
                ActivityOutcome::Succeeded | ActivityOutcome::Partial
            )
        }
        CaptureTermination::DeadlineReached { .. }
        | CaptureTermination::EventLimitReached { .. }
        | CaptureTermination::ByteLimitReached { .. } => outcome == ActivityOutcome::Partial,
        CaptureTermination::Interrupted(evidence) => match evidence.initiator() {
            InterruptionInitiator::Caller => outcome == ActivityOutcome::Cancelled,
            InterruptionInitiator::Provider => {
                matches!(outcome, ActivityOutcome::Partial | ActivityOutcome::Failed)
            }
            InterruptionInitiator::System => outcome == ActivityOutcome::Partial,
        },
    };
    if coherent {
        Ok(())
    } else {
        Err(AcquisitionFinalizationError::ActivityOutcomeMismatch)
    }
}

fn validate_artifact_timestamps(
    started_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
    manifest: &WebArtifactManifest,
    order: ArtifactTimestampOrder,
) -> Result<(), AcquisitionFinalizationError> {
    let generated: Vec<_> = manifest
        .results()
        .all_artifacts()
        .into_iter()
        .map(|artifact| artifact.metadata().provenance().generated_at().to_owned())
        .collect();
    if generated
        .iter()
        .any(|at| *at < started_at || *at > finished_at)
    {
        return Err(AcquisitionFinalizationError::ArtifactTimestampOutsideWindow);
    }
    if order == ArtifactTimestampOrder::ManifestOrder
        && generated
            .windows(2)
            .any(|pair| matches!(pair, [first, second] if first > second))
    {
        return Err(AcquisitionFinalizationError::ArtifactTimestampsUnordered);
    }
    Ok(())
}

#[cfg(test)]
#[path = "acquisition_finalization_tests.rs"]
mod tests;
