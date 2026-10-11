use chrono::{DateTime, Utc};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};

use super::super::BrowserProfileLeaseGeneration;
use super::{
    BROWSER_PROFILE_LIFECYCLE_SCHEMA_VERSION, BrowserProfileLifecycleError,
    BrowserProfileLifecycleEvent, BrowserProfileLifecycleReason, BrowserProfileLifecycleSource,
    BrowserProfileLifecycleState, BrowserProfileQuarantineReason, reduce_browser_profile_lifecycle,
};

/// Secret-safe record of one lifecycle state transition.
///
/// The wire representation contains only typed states, fixed reason/source
/// codes, generation watermarks, and an observation timestamp. It has no path,
/// URL, credential, or caller-supplied text field.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileLifecycleRecord {
    observed_at: DateTime<Utc>,
    schema_version: u16,
    source: BrowserProfileLifecycleSource,
    previous: BrowserProfileLifecycleState,
    previous_latest_generation: Option<BrowserProfileLeaseGeneration>,
    next: BrowserProfileLifecycleState,
    latest_generation: Option<BrowserProfileLeaseGeneration>,
    reason: BrowserProfileLifecycleReason,
}

impl BrowserProfileLifecycleRecord {
    pub fn from_event(
        observed_at: DateTime<Utc>,
        previous: BrowserProfileLifecycleState,
        previous_latest_generation: Option<BrowserProfileLeaseGeneration>,
        event: BrowserProfileLifecycleEvent,
    ) -> Result<Self, BrowserProfileLifecycleError> {
        let transition =
            reduce_browser_profile_lifecycle(previous, previous_latest_generation, event)?;
        Self::new(
            observed_at,
            event.source(),
            previous,
            previous_latest_generation,
            transition.next(),
            transition.latest_generation(),
            event.reason(),
        )
    }

    pub fn new(
        observed_at: DateTime<Utc>,
        source: BrowserProfileLifecycleSource,
        previous: BrowserProfileLifecycleState,
        previous_latest_generation: Option<BrowserProfileLeaseGeneration>,
        next: BrowserProfileLifecycleState,
        latest_generation: Option<BrowserProfileLeaseGeneration>,
        reason: BrowserProfileLifecycleReason,
    ) -> Result<Self, BrowserProfileLifecycleError> {
        if !valid_record_transition(
            previous,
            previous_latest_generation,
            next,
            latest_generation,
            reason,
        ) || !source_matches_reason(source, reason)
        {
            return Err(BrowserProfileLifecycleError::InvalidRecord);
        }
        Ok(Self {
            observed_at,
            schema_version: BROWSER_PROFILE_LIFECYCLE_SCHEMA_VERSION,
            source,
            previous,
            previous_latest_generation,
            next,
            latest_generation,
            reason,
        })
    }

    pub const fn observed_at(&self) -> &DateTime<Utc> {
        &self.observed_at
    }

    pub const fn schema_version(&self) -> u16 {
        self.schema_version
    }

    pub const fn source(&self) -> BrowserProfileLifecycleSource {
        self.source
    }

    pub const fn previous(&self) -> BrowserProfileLifecycleState {
        self.previous
    }

    pub const fn previous_latest_generation(&self) -> Option<BrowserProfileLeaseGeneration> {
        self.previous_latest_generation
    }

    pub const fn next(&self) -> BrowserProfileLifecycleState {
        self.next
    }

    pub const fn latest_generation(&self) -> Option<BrowserProfileLeaseGeneration> {
        self.latest_generation
    }

    pub const fn reason(&self) -> BrowserProfileLifecycleReason {
        self.reason
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserProfileLifecycleRecordWire {
    observed_at: DateTime<Utc>,
    schema_version: u16,
    source: BrowserProfileLifecycleSource,
    previous: BrowserProfileLifecycleState,
    #[serde(deserialize_with = "deserialize_required_option")]
    previous_latest_generation: Option<BrowserProfileLeaseGeneration>,
    next: BrowserProfileLifecycleState,
    #[serde(deserialize_with = "deserialize_required_option")]
    latest_generation: Option<BrowserProfileLeaseGeneration>,
    reason: BrowserProfileLifecycleReason,
}

fn deserialize_required_option<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer)
}

impl<'de> Deserialize<'de> for BrowserProfileLifecycleRecord {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = BrowserProfileLifecycleRecordWire::deserialize(deserializer)?;
        if wire.schema_version != BROWSER_PROFILE_LIFECYCLE_SCHEMA_VERSION {
            return Err(D::Error::custom(
                BrowserProfileLifecycleError::UnsupportedSchemaVersion,
            ));
        }
        Self::new(
            wire.observed_at,
            wire.source,
            wire.previous,
            wire.previous_latest_generation,
            wire.next,
            wire.latest_generation,
            wire.reason,
        )
        .map_err(D::Error::custom)
    }
}

const fn source_matches_reason(
    source: BrowserProfileLifecycleSource,
    reason: BrowserProfileLifecycleReason,
) -> bool {
    use BrowserProfileLifecycleReason as Reason;
    use BrowserProfileLifecycleSource as Source;

    matches!(
        (source, reason),
        (
            Source::Provisioner,
            Reason::ProfileStaged
                | Reason::ProvisionSucceeded
                | Reason::ProvisioningFailed
                | Reason::ProvisionOwnershipUncertain,
        ) | (
            Source::ForkManager,
            Reason::ForkChildAvailable | Reason::ForkOutcomeUncertain
        ) | (
            Source::LeaseManager,
            Reason::LeaseAcquired
                | Reason::LeaseReleased
                | Reason::LeaseExpired
                | Reason::LeaseOwnershipUncertain
        ) | (Source::BrowserRuntime, Reason::CorruptionDetected)
            | (
                Source::Operator,
                Reason::OperatorRetired | Reason::OperatorReviewedAvailable
            )
            | (
                Source::StartupClassifier,
                Reason::StartupProvisionInterrupted | Reason::StartupLeaseInterrupted
            )
    )
}

#[allow(
    clippy::unnested_or_patterns,
    reason = "nested reason alternatives keep the lifecycle transition matrix grouped by state pair"
)]
fn valid_record_transition(
    previous: BrowserProfileLifecycleState,
    previous_latest_generation: Option<BrowserProfileLeaseGeneration>,
    next: BrowserProfileLifecycleState,
    latest_generation: Option<BrowserProfileLeaseGeneration>,
    reason: BrowserProfileLifecycleReason,
) -> bool {
    use BrowserProfileLifecycleReason as Reason;
    use BrowserProfileLifecycleState as State;

    let previous_state_watermark_is_valid = match previous {
        State::Leased { generation } => previous_latest_generation == Some(generation),
        State::Quarantined {
            reason:
                BrowserProfileQuarantineReason::LeaseExpired
                | BrowserProfileQuarantineReason::LeaseOwnershipUncertain
                | BrowserProfileQuarantineReason::StartupLeaseInterrupted,
        } => previous_latest_generation.is_some(),
        _ => true,
    };
    let next_state_watermark_is_valid = match next {
        State::Leased { generation } => latest_generation == Some(generation),
        State::Quarantined {
            reason:
                BrowserProfileQuarantineReason::LeaseExpired
                | BrowserProfileQuarantineReason::LeaseOwnershipUncertain
                | BrowserProfileQuarantineReason::StartupLeaseInterrupted,
        } => latest_generation.is_some(),
        _ => true,
    };
    if !previous_state_watermark_is_valid || !next_state_watermark_is_valid {
        return false;
    }

    let generation_flow_is_valid = match reason {
        Reason::LeaseAcquired => match next {
            State::Leased { generation } => {
                latest_generation == Some(generation)
                    && previous_latest_generation.is_none_or(|previous| generation > previous)
            }
            _ => false,
        },
        Reason::LeaseReleased | Reason::LeaseExpired | Reason::LeaseOwnershipUncertain => {
            match previous {
                State::Leased { generation } => {
                    previous_latest_generation == Some(generation)
                        && latest_generation == Some(generation)
                }
                _ => false,
            }
        }
        _ => latest_generation == previous_latest_generation,
    };
    if !generation_flow_is_valid {
        return false;
    }

    match (previous, next, reason) {
        (State::Staged, State::Staged, Reason::ProfileStaged)
        | (
            State::Staged,
            State::Available,
            Reason::ProvisionSucceeded | Reason::ForkChildAvailable,
        )
        | (
            State::Staged,
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::ProvisioningFailed,
            },
            Reason::ProvisioningFailed,
        )
        | (
            State::Available,
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::ProvisioningFailed,
            },
            Reason::ProvisioningFailed,
        )
        | (
            State::Staged | State::Available,
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::ProvisionOwnershipUncertain,
            },
            Reason::ProvisionOwnershipUncertain,
        )
        | (
            State::Staged | State::Available,
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::ForkOutcomeUncertain,
            },
            Reason::ForkOutcomeUncertain,
        )
        | (
            State::Staged,
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::StartupProvisionInterrupted,
            },
            Reason::StartupProvisionInterrupted,
        ) => previous_latest_generation.is_none() && latest_generation.is_none(),
        (State::Available, State::Leased { .. }, Reason::LeaseAcquired)
        | (State::Leased { .. }, State::Available, Reason::LeaseReleased)
        | (
            State::Leased { .. },
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::LeaseExpired,
            },
            Reason::LeaseExpired,
        )
        | (
            State::Leased { .. },
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::LeaseOwnershipUncertain,
            },
            Reason::LeaseOwnershipUncertain,
        )
        | (
            State::Staged | State::Available | State::Leased { .. } | State::Quarantined { .. },
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::CorruptionDetected,
            },
            Reason::CorruptionDetected,
        )
        | (
            State::Staged | State::Available | State::Leased { .. } | State::Quarantined { .. },
            State::Retired,
            Reason::OperatorRetired,
        )
        | (State::Quarantined { .. }, State::Available, Reason::OperatorReviewedAvailable)
        | (
            State::Leased { .. },
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::StartupLeaseInterrupted,
            },
            Reason::StartupLeaseInterrupted,
        ) => true,
        _ => false,
    }
}
