//! Validated aggregate of policy, window, terminal state, and stop reason.

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use super::{
    CaptureTermination, MeasuredCount, ObservationPolicy, ObservationWindow, SettlementEvidence,
    SettlementPolicy, TerminalObservationState,
};

/// Error returned when terminal observation facts contradict the policy or window.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum CaptureObservationError {
    /// Terminal accounting did not cover the complete elapsed window.
    #[error("terminal accounting must be observed through the window's elapsed duration")]
    TerminalOffsetMismatch,
    /// A non-deadline outcome finished after the mandatory deadline.
    #[error("observation cannot finish after its maximum elapsed duration")]
    WindowExceedsMaximum,
    /// Settlement was reported even though settlement was disabled.
    #[error("settled termination requires a quiet-period settlement policy")]
    SettlementDisabled,
    /// Settlement evidence named a different policy.
    #[error("settlement evidence must identify the declared policy")]
    SettlementPolicyMismatch,
    /// The declared quiet duration was not observed.
    #[error("settlement evidence does not satisfy the declared quiet period")]
    QuietPeriodNotSatisfied,
    /// Too much relevant activity remained for settlement.
    #[error("settlement evidence exceeds the policy's in-flight threshold")]
    SettlementInFlightExceeded,
    /// Settlement satisfaction did not coincide with terminal elapsed time.
    #[error("settlement evidence must be satisfied when the observation terminates")]
    SettlementOutsideWindow,
    /// Terminal in-flight accounting disagreed with settlement evidence.
    #[error("settlement evidence must match terminal relevant in-flight activity")]
    SettlementTerminalStateMismatch,
    /// Deadline evidence disagreed with the configured deadline.
    #[error("deadline termination must identify the configured maximum elapsed duration")]
    DeadlineMismatch,
    /// The window ended before its configured deadline.
    #[error("deadline termination requires elapsed time to reach the configured maximum")]
    DeadlineNotReached,
    /// Event-limit evidence disagreed with the configured event limit.
    #[error("event-limit termination must identify the configured event limit")]
    EventLimitMismatch,
    /// Event-limit termination did not admit enough events to reach its bound.
    #[error("event-limit termination requires admitted events to reach the configured limit")]
    EventLimitNotReached,
    /// Admitted events exceeded their configured hard bound.
    #[error("admitted events cannot exceed the configured event limit")]
    EventLimitExceeded,
    /// Byte-limit evidence disagreed with the configured byte limit.
    #[error("byte-limit termination must identify the configured byte limit")]
    ByteLimitMismatch,
    /// Byte-limit termination did not admit enough bytes to reach its bound.
    #[error("byte-limit termination requires admitted bytes to reach the configured limit")]
    ByteLimitNotReached,
    /// Admitted bytes exceeded their configured hard bound.
    #[error("admitted bytes cannot exceed the configured byte limit")]
    ByteLimitExceeded,
}

/// Policy, actual window, terminal accounting, and stop reason for one observation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CaptureObservation {
    policy: ObservationPolicy,
    window: ObservationWindow,
    terminal_state: TerminalObservationState,
    termination: CaptureTermination,
}

impl CaptureObservation {
    /// Creates a terminal observation after checking outcome-specific evidence.
    pub fn new(
        policy: ObservationPolicy,
        window: ObservationWindow,
        terminal_state: TerminalObservationState,
        termination: CaptureTermination,
    ) -> Result<Self, CaptureObservationError> {
        validate_capture_observation(&policy, &window, &terminal_state, &termination)?;
        Ok(Self {
            policy,
            window,
            terminal_state,
            termination,
        })
    }

    /// Returns the configured observation policy.
    pub const fn policy(&self) -> &ObservationPolicy {
        &self.policy
    }

    /// Returns the actual observation window.
    pub const fn window(&self) -> &ObservationWindow {
        &self.window
    }

    /// Returns data and in-flight accounting at termination.
    pub const fn terminal_state(&self) -> &TerminalObservationState {
        &self.terminal_state
    }

    /// Returns why observation stopped.
    pub const fn termination(&self) -> &CaptureTermination {
        &self.termination
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CaptureObservationWire {
    policy: ObservationPolicy,
    window: ObservationWindow,
    terminal_state: TerminalObservationState,
    termination: CaptureTermination,
}

impl TryFrom<CaptureObservationWire> for CaptureObservation {
    type Error = CaptureObservationError;

    fn try_from(value: CaptureObservationWire) -> Result<Self, Self::Error> {
        Self::new(
            value.policy,
            value.window,
            value.terminal_state,
            value.termination,
        )
    }
}

impl<'de> Deserialize<'de> for CaptureObservation {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        CaptureObservationWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

fn validate_capture_observation(
    policy: &ObservationPolicy,
    window: &ObservationWindow,
    terminal_state: &TerminalObservationState,
    termination: &CaptureTermination,
) -> Result<(), CaptureObservationError> {
    if terminal_state.observed_through().as_microseconds() != window.elapsed().as_microseconds() {
        return Err(CaptureObservationError::TerminalOffsetMismatch);
    }
    if !matches!(termination, CaptureTermination::DeadlineReached { .. })
        && window.elapsed() > policy.limits().maximum_elapsed().duration()
    {
        return Err(CaptureObservationError::WindowExceedsMaximum);
    }
    if policy
        .limits()
        .event_limit()
        .is_some_and(|limit| terminal_state.events().admitted().get() > limit.get())
    {
        return Err(CaptureObservationError::EventLimitExceeded);
    }
    if policy
        .limits()
        .byte_limit()
        .is_some_and(|limit| terminal_state.bytes().admitted().get() > limit.get())
    {
        return Err(CaptureObservationError::ByteLimitExceeded);
    }

    match termination {
        CaptureTermination::Settled(evidence) => {
            validate_settlement(policy, window, terminal_state, evidence)
        }
        CaptureTermination::ControllerStopped(_) | CaptureTermination::Interrupted(_) => Ok(()),
        CaptureTermination::DeadlineReached { maximum_elapsed } => {
            if *maximum_elapsed != policy.limits().maximum_elapsed() {
                return Err(CaptureObservationError::DeadlineMismatch);
            }
            if window.elapsed() < maximum_elapsed.duration() {
                return Err(CaptureObservationError::DeadlineNotReached);
            }
            Ok(())
        }
        CaptureTermination::EventLimitReached { event_limit } => {
            if Some(*event_limit) != policy.limits().event_limit() {
                return Err(CaptureObservationError::EventLimitMismatch);
            }
            if terminal_state.events().admitted().get() < event_limit.get() {
                return Err(CaptureObservationError::EventLimitNotReached);
            }
            Ok(())
        }
        CaptureTermination::ByteLimitReached { byte_limit } => {
            if Some(*byte_limit) != policy.limits().byte_limit() {
                return Err(CaptureObservationError::ByteLimitMismatch);
            }
            if terminal_state.bytes().admitted().get() < byte_limit.get() {
                return Err(CaptureObservationError::ByteLimitNotReached);
            }
            Ok(())
        }
    }
}

fn validate_settlement(
    policy: &ObservationPolicy,
    window: &ObservationWindow,
    terminal_state: &TerminalObservationState,
    evidence: &SettlementEvidence,
) -> Result<(), CaptureObservationError> {
    let SettlementPolicy::QuietPeriod(quiet_policy) = policy.settlement() else {
        return Err(CaptureObservationError::SettlementDisabled);
    };
    if evidence.policy() != quiet_policy.id() {
        return Err(CaptureObservationError::SettlementPolicyMismatch);
    }
    let observed_quiet = evidence
        .satisfied_at()
        .duration_since(evidence.quiet_since())
        .ok_or(CaptureObservationError::QuietPeriodNotSatisfied)?;
    if observed_quiet < quiet_policy.required_quiet().duration() {
        return Err(CaptureObservationError::QuietPeriodNotSatisfied);
    }
    if evidence.relevant_in_flight() > quiet_policy.maximum_relevant_in_flight() {
        return Err(CaptureObservationError::SettlementInFlightExceeded);
    }
    if evidence.satisfied_at().as_microseconds() != window.elapsed().as_microseconds() {
        return Err(CaptureObservationError::SettlementOutsideWindow);
    }
    if terminal_state.in_flight().settlement_relevant()
        != &MeasuredCount::Known(evidence.relevant_in_flight())
    {
        return Err(CaptureObservationError::SettlementTerminalStateMismatch);
    }
    Ok(())
}
