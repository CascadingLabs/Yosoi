//! Typed reasons why a bounded observation stopped.

use serde::{Deserialize, Serialize};
use yosoi_types::ReasonCode;

use super::{ByteLimit, CaptureDeadline, EventLimit, SettlementEvidence};

/// Normal controller decision that ended an otherwise healthy observation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ControllerStopReason {
    /// The controller obtained enough evidence for its current goal.
    GoalSatisfied,
    /// The controller determined that further observation was not useful.
    NoFurtherUsefulAction,
    /// A higher-level policy requested a successful stop.
    PolicyDecision,
}

/// Component responsible for an abnormal interruption.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InterruptionInitiator {
    /// The calling process cancelled the capture.
    Caller,
    /// The acquisition provider stopped unexpectedly.
    Provider,
    /// The hosting system stopped the capture.
    System,
}

/// Secret-safe evidence explaining an interrupted observation.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InterruptionEvidence {
    initiator: InterruptionInitiator,
    reason: ReasonCode,
}

impl InterruptionEvidence {
    /// Creates interruption evidence.
    pub const fn new(initiator: InterruptionInitiator, reason: ReasonCode) -> Self {
        Self { initiator, reason }
    }

    /// Returns who initiated the interruption.
    pub const fn initiator(&self) -> InterruptionInitiator {
        self.initiator
    }

    /// Returns the stable secret-safe interruption reason.
    pub const fn reason(&self) -> &ReasonCode {
        &self.reason
    }
}

/// Why a bounded observation window stopped.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "outcome", content = "evidence", rename_all = "snake_case")]
pub enum CaptureTermination {
    /// A declared quiet-period settlement policy was satisfied.
    Settled(SettlementEvidence),
    /// The controller deliberately completed a useful observation.
    ControllerStopped(ControllerStopReason),
    /// The mandatory elapsed-time bound was reached.
    DeadlineReached {
        /// The elapsed-time bound that caused termination.
        maximum_elapsed: CaptureDeadline,
    },
    /// The configured admitted-event bound was reached.
    EventLimitReached {
        /// The event bound that caused termination.
        event_limit: EventLimit,
    },
    /// The configured admitted-byte bound was reached.
    ByteLimitReached {
        /// The byte bound that caused termination.
        byte_limit: ByteLimit,
    },
    /// Observation was stopped abnormally.
    Interrupted(InterruptionEvidence),
}
