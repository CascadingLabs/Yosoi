//! Declared quiet-period policy and evidence.

use std::{fmt, num::NonZeroU64, str::FromStr};

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use super::{
    ActivityCount, CaptureDuration, CaptureOffset, EventAccounting, MeasuredCount,
    ObservationLimits,
};

const MAX_POLICY_ID_BYTES: usize = 128;

/// Error returned when a settlement policy identity is not canonical.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum SettlementPolicyIdError {
    /// The identity was empty.
    #[error("settlement policy identity cannot be empty")]
    Empty,
    /// The identity exceeded its wire bound.
    #[error("settlement policy identity cannot exceed {MAX_POLICY_ID_BYTES} bytes")]
    TooLong,
    /// The identity did not use the canonical namespaced alphabet.
    #[error(
        "settlement policy identity must be lowercase ASCII, namespaced, and contain only letters, digits, '.', '-', or '_'"
    )]
    Invalid,
}

/// Stable namespaced identity of declared settlement semantics.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct SettlementPolicyId(String);

impl SettlementPolicyId {
    /// Validates and creates a settlement policy identity.
    pub fn new(value: impl Into<String>) -> Result<Self, SettlementPolicyIdError> {
        let value = value.into();
        validate_settlement_policy_id(&value)?;
        Ok(Self(value))
    }

    /// Returns the canonical identity.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for SettlementPolicyId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for SettlementPolicyId {
    type Err = SettlementPolicyIdError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

impl<'de> Deserialize<'de> for SettlementPolicyId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        String::deserialize(deserializer)?
            .parse()
            .map_err(D::Error::custom)
    }
}

/// Error returned when a required quiet period is zero.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("required quiet period must be greater than zero")]
pub struct QuietPeriodError;

/// Non-zero duration required by a quiet-period settlement policy.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct QuietPeriod(NonZeroU64);

impl QuietPeriod {
    /// Returns the required quiet duration in microseconds.
    pub const fn as_microseconds(self) -> u64 {
        self.0.get()
    }

    /// Returns the required quiet duration.
    pub const fn duration(self) -> CaptureDuration {
        CaptureDuration::from_microseconds(self.as_microseconds())
    }
}

impl TryFrom<u64> for QuietPeriod {
    type Error = QuietPeriodError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        NonZeroU64::new(value).map(Self).ok_or(QuietPeriodError)
    }
}

impl From<QuietPeriod> for u64 {
    fn from(value: QuietPeriod) -> Self {
        value.as_microseconds()
    }
}

impl<'de> Deserialize<'de> for QuietPeriod {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        u64::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Declared semantics for quiet-period settlement.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuietPeriodPolicy {
    id: SettlementPolicyId,
    required_quiet: QuietPeriod,
    maximum_relevant_in_flight: ActivityCount,
}

impl QuietPeriodPolicy {
    /// Creates a declared quiet-period policy.
    pub const fn new(
        id: SettlementPolicyId,
        required_quiet: QuietPeriod,
        maximum_relevant_in_flight: ActivityCount,
    ) -> Self {
        Self {
            id,
            required_quiet,
            maximum_relevant_in_flight,
        }
    }

    /// Returns the policy identity.
    pub const fn id(&self) -> &SettlementPolicyId {
        &self.id
    }

    /// Returns the required uninterrupted quiet duration.
    pub const fn required_quiet(&self) -> QuietPeriod {
        self.required_quiet
    }

    /// Returns the maximum relevant activity permitted at settlement.
    pub const fn maximum_relevant_in_flight(&self) -> ActivityCount {
        self.maximum_relevant_in_flight
    }
}

/// Settlement behavior selected for an observation window.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "kind", content = "policy", rename_all = "snake_case")]
pub enum SettlementPolicy {
    /// The observation does not use settlement as a completion condition.
    Disabled,
    /// A declared quiet-period condition can complete the observation.
    QuietPeriod(QuietPeriodPolicy),
}

/// Configured limits and optional settlement behavior for one observation.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObservationPolicy {
    limits: ObservationLimits,
    settlement: SettlementPolicy,
}

impl ObservationPolicy {
    /// Creates an observation policy.
    pub const fn new(limits: ObservationLimits, settlement: SettlementPolicy) -> Self {
        Self { limits, settlement }
    }

    /// Returns the hard observation limits.
    pub const fn limits(&self) -> &ObservationLimits {
        &self.limits
    }

    /// Returns the selected settlement behavior.
    pub const fn settlement(&self) -> &SettlementPolicy {
        &self.settlement
    }
}

/// Error returned when claimed settlement evidence cannot prove quiet coverage.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum SettlementEvidenceError {
    /// Settlement timestamps were reversed.
    #[error("settlement satisfaction cannot precede the beginning of its quiet period")]
    InvalidTimeOrder,
    /// Relevant events were admitted during the claimed quiet period.
    #[error("settlement cannot be proven when relevant events occurred during quiet")]
    RelevantEventsObserved,
    /// Relevant event loss was not measurable during the claimed quiet period.
    #[error("settlement requires known relevant-event loss during quiet")]
    RelevantLossUnavailable,
}

/// Evidence that one declared quiet-period policy was satisfied.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
pub struct SettlementEvidence {
    policy: SettlementPolicyId,
    quiet_since: CaptureOffset,
    satisfied_at: CaptureOffset,
    relevant_in_flight: ActivityCount,
    quiet_period_events: EventAccounting,
}

impl SettlementEvidence {
    /// Creates settlement evidence after checking time ordering and quiet coverage.
    pub fn new(
        policy: SettlementPolicyId,
        quiet_since: CaptureOffset,
        satisfied_at: CaptureOffset,
        relevant_in_flight: ActivityCount,
        quiet_period_events: EventAccounting,
    ) -> Result<Self, SettlementEvidenceError> {
        if satisfied_at < quiet_since {
            return Err(SettlementEvidenceError::InvalidTimeOrder);
        }
        if quiet_period_events.admitted().get() != 0 {
            return Err(SettlementEvidenceError::RelevantEventsObserved);
        }
        if !matches!(quiet_period_events.dropped(), MeasuredCount::Known(count) if count.get() == 0)
        {
            return Err(SettlementEvidenceError::RelevantLossUnavailable);
        }
        Ok(Self {
            policy,
            quiet_since,
            satisfied_at,
            relevant_in_flight,
            quiet_period_events,
        })
    }

    /// Returns the satisfied policy identity.
    pub const fn policy(&self) -> &SettlementPolicyId {
        &self.policy
    }

    /// Returns when uninterrupted quiet began.
    pub const fn quiet_since(&self) -> CaptureOffset {
        self.quiet_since
    }

    /// Returns when the policy was satisfied.
    pub const fn satisfied_at(&self) -> CaptureOffset {
        self.satisfied_at
    }

    /// Returns relevant activity still in flight when the policy was satisfied.
    pub const fn relevant_in_flight(&self) -> ActivityCount {
        self.relevant_in_flight
    }

    /// Returns relevant event accounting scoped to the claimed quiet interval.
    pub const fn quiet_period_events(&self) -> &EventAccounting {
        &self.quiet_period_events
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SettlementEvidenceWire {
    policy: SettlementPolicyId,
    quiet_since: CaptureOffset,
    satisfied_at: CaptureOffset,
    relevant_in_flight: ActivityCount,
    quiet_period_events: EventAccounting,
}

impl TryFrom<SettlementEvidenceWire> for SettlementEvidence {
    type Error = SettlementEvidenceError;

    fn try_from(value: SettlementEvidenceWire) -> Result<Self, Self::Error> {
        Self::new(
            value.policy,
            value.quiet_since,
            value.satisfied_at,
            value.relevant_in_flight,
            value.quiet_period_events,
        )
    }
}

impl<'de> Deserialize<'de> for SettlementEvidence {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        SettlementEvidenceWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

fn validate_settlement_policy_id(value: &str) -> Result<(), SettlementPolicyIdError> {
    if value.is_empty() {
        return Err(SettlementPolicyIdError::Empty);
    }
    if value.len() > MAX_POLICY_ID_BYTES {
        return Err(SettlementPolicyIdError::TooLong);
    }

    let valid_character = |character: u8| {
        character.is_ascii_lowercase()
            || character.is_ascii_digit()
            || matches!(character, b'.' | b'-' | b'_')
    };
    let valid_edge = |character: u8| character.is_ascii_lowercase() || character.is_ascii_digit();
    if !value.contains('.')
        || value.split('.').any(str::is_empty)
        || !value.bytes().all(valid_character)
        || !value.bytes().next().is_some_and(valid_edge)
        || !value.bytes().next_back().is_some_and(valid_edge)
    {
        return Err(SettlementPolicyIdError::Invalid);
    }
    Ok(())
}
