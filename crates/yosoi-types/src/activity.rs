//! Immutable terminal receipts for activities and capture specialization.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use crate::{
    ActivityId, ArtifactRecord, ArtifactRef, CaptureId, OperationId, Producer, ReasonCode,
};

/// Terminal result of one actual activity attempt.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActivityOutcome {
    /// Every declared output and condition completed.
    Succeeded,
    /// Useful evidence was retained, but the activity did not fully complete.
    Partial,
    /// The declared operation could not produce its intended result.
    ///
    /// This does not imply a defect in the producer; an external response such
    /// as an HTTP `404` can prevent the intended result.
    Failed,
    /// Policy or admission prevented the activity from running.
    Blocked,
    /// Available evidence could not establish success or failure.
    Inconclusive,
    /// The activity was deliberately stopped.
    Cancelled,
}

/// Whether retrying an unchanged activity could reasonably succeed.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RetryDisposition {
    /// Another unchanged attempt may succeed.
    Retryable,
    /// Intent or inputs must change before retry.
    NotRetryable,
    /// The producer cannot determine retry safety.
    Unknown,
}

/// Secret-safe signal explaining a non-success activity outcome.
///
/// A signal is an observed termination reason, not necessarily a defect in the
/// producer. For example, a remote `404`, an intentional policy block, or a
/// configured observation limit can all be useful terminal signals.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActivitySignal {
    code: ReasonCode,
    retry: RetryDisposition,
}

impl ActivitySignal {
    /// Creates a signal from an explicit reason and retry decision.
    pub const fn new(code: ReasonCode, retry: RetryDisposition) -> Self {
        Self { code, retry }
    }

    /// Returns the stable reason code.
    pub const fn code(&self) -> &ReasonCode {
        &self.code
    }

    /// Returns the retry decision.
    pub const fn retry(&self) -> RetryDisposition {
        self.retry
    }
}

/// Error returned when an activity receipt contains contradictory facts.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ActivityReceiptError {
    /// The activity ended before it began.
    #[error("activity finish time cannot precede start time")]
    InvalidTimeWindow,

    /// Success carried a termination signal.
    #[error("successful activity cannot carry a termination signal")]
    UnexpectedSignal,

    /// A non-success outcome omitted its termination signal.
    #[error("non-success activity outcome requires a termination signal")]
    MissingSignal,

    /// Two outputs claimed the same activity-local ID.
    #[error("activity output artifact IDs must be unique")]
    DuplicateArtifactId,

    /// An output claimed provenance from another activity.
    #[error("activity output provenance must reference the receipt activity")]
    ForeignOutputActivity,

    /// An output claimed a generation time outside the activity window.
    #[error("activity output generation time must fall within the activity window")]
    OutputTimeOutsideActivity,
}

/// Immutable cross-repository receipt for one completed activity attempt.
///
/// This is the hardened core of the selected hybrid design. It is a portable
/// finalized fact, not a mutable run record, event journal, replay plan, or
/// provider payload. Future replay code can reference receipts while allocating
/// a fresh `ActivityId` for every new attempt.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ActivityReceipt {
    id: ActivityId,
    operation: OperationId,
    producer: Producer,
    inputs: Vec<ArtifactRef>,
    outputs: Vec<ArtifactRecord>,
    outcome: ActivityOutcome,
    signal: Option<ActivitySignal>,
    started_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
}

impl ActivityReceipt {
    /// Creates and validates an immutable terminal activity receipt.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        id: ActivityId,
        operation: OperationId,
        producer: Producer,
        inputs: Vec<ArtifactRef>,
        outputs: Vec<ArtifactRecord>,
        outcome: ActivityOutcome,
        signal: Option<ActivitySignal>,
        started_at: DateTime<Utc>,
        finished_at: DateTime<Utc>,
    ) -> Result<Self, ActivityReceiptError> {
        validate_activity_receipt(
            id,
            &outputs,
            outcome,
            signal.as_ref(),
            &started_at,
            &finished_at,
        )?;
        Ok(Self {
            id,
            operation,
            producer,
            inputs,
            outputs,
            outcome,
            signal,
            started_at,
            finished_at,
        })
    }

    /// Returns this activity occurrence's identity.
    pub const fn id(&self) -> ActivityId {
        self.id
    }

    /// Returns the namespaced operation that was attempted.
    pub const fn operation(&self) -> &OperationId {
        &self.operation
    }

    /// Returns the component that coordinated or performed the activity.
    ///
    /// Individual output artifacts name their immediate producers in their own
    /// provenance and may therefore identify a different component.
    pub const fn producer(&self) -> &Producer {
        &self.producer
    }

    /// Returns direct artifact inputs.
    pub fn inputs(&self) -> &[ArtifactRef] {
        &self.inputs
    }

    /// Returns artifacts emitted by this attempt.
    ///
    /// Every output belongs to this activity occurrence, but its immediate
    /// producer may differ from the activity-level producer.
    pub fn outputs(&self) -> &[ArtifactRecord] {
        &self.outputs
    }

    /// Returns the terminal outcome.
    pub const fn outcome(&self) -> ActivityOutcome {
        self.outcome
    }

    /// Returns the signal explaining a non-success outcome.
    pub const fn signal(&self) -> Option<&ActivitySignal> {
        self.signal.as_ref()
    }

    /// Returns when the activity began.
    pub const fn started_at(&self) -> &DateTime<Utc> {
        &self.started_at
    }

    /// Returns when the activity reached its terminal outcome.
    pub const fn finished_at(&self) -> &DateTime<Utc> {
        &self.finished_at
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ActivityReceiptWire {
    id: ActivityId,
    operation: OperationId,
    producer: Producer,
    inputs: Vec<ArtifactRef>,
    outputs: Vec<ArtifactRecord>,
    outcome: ActivityOutcome,
    signal: Option<ActivitySignal>,
    started_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
}

impl TryFrom<ActivityReceiptWire> for ActivityReceipt {
    type Error = ActivityReceiptError;

    fn try_from(value: ActivityReceiptWire) -> Result<Self, Self::Error> {
        Self::new(
            value.id,
            value.operation,
            value.producer,
            value.inputs,
            value.outputs,
            value.outcome,
            value.signal,
            value.started_at,
            value.finished_at,
        )
    }
}

impl<'de> Deserialize<'de> for ActivityReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        ActivityReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Error returned when a capture wrapper and activity receipt disagree.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("capture identity must match its activity receipt")]
pub struct CaptureReceiptError;

/// Typed proof that an [`ActivityReceipt`] describes a capture activity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CaptureReceipt {
    id: CaptureId,
    receipt: ActivityReceipt,
}

impl CaptureReceipt {
    /// Creates a capture receipt when both typed identities agree.
    pub fn new(id: CaptureId, receipt: ActivityReceipt) -> Result<Self, CaptureReceiptError> {
        if id.activity_id() != receipt.id() {
            return Err(CaptureReceiptError);
        }
        Ok(Self { id, receipt })
    }

    /// Returns the capture identity.
    pub const fn id(&self) -> CaptureId {
        self.id
    }

    /// Returns the general activity receipt.
    pub const fn receipt(&self) -> &ActivityReceipt {
        &self.receipt
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CaptureReceiptWire {
    id: CaptureId,
    receipt: ActivityReceipt,
}

impl TryFrom<CaptureReceiptWire> for CaptureReceipt {
    type Error = CaptureReceiptError;

    fn try_from(value: CaptureReceiptWire) -> Result<Self, Self::Error> {
        Self::new(value.id, value.receipt)
    }
}

impl<'de> Deserialize<'de> for CaptureReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        CaptureReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

fn validate_activity_receipt(
    id: ActivityId,
    outputs: &[ArtifactRecord],
    outcome: ActivityOutcome,
    signal: Option<&ActivitySignal>,
    started_at: &DateTime<Utc>,
    finished_at: &DateTime<Utc>,
) -> Result<(), ActivityReceiptError> {
    if finished_at < started_at {
        return Err(ActivityReceiptError::InvalidTimeWindow);
    }
    if outcome == ActivityOutcome::Succeeded && signal.is_some() {
        return Err(ActivityReceiptError::UnexpectedSignal);
    }
    if outcome != ActivityOutcome::Succeeded && signal.is_none() {
        return Err(ActivityReceiptError::MissingSignal);
    }

    for (index, output) in outputs.iter().enumerate() {
        if outputs
            .iter()
            .skip(index.saturating_add(1))
            .any(|other| other.id() == output.id())
        {
            return Err(ActivityReceiptError::DuplicateArtifactId);
        }
        if output.provenance().activity_id() != id {
            return Err(ActivityReceiptError::ForeignOutputActivity);
        }
        if output.provenance().generated_at() < started_at
            || output.provenance().generated_at() > finished_at
        {
            return Err(ActivityReceiptError::OutputTimeOutsideActivity);
        }
    }
    Ok(())
}
