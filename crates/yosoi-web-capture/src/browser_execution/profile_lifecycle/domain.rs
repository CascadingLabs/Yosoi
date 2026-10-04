use serde::{Deserialize, Serialize};
use thiserror::Error;

use super::super::BrowserProfileLeaseGeneration;

/// Why a profile must remain unavailable for leasing.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserProfileQuarantineReason {
    ProvisioningFailed,
    ProvisionOwnershipUncertain,
    ForkOutcomeUncertain,
    LeaseExpired,
    LeaseOwnershipUncertain,
    CorruptionDetected,
    StartupProvisionInterrupted,
    StartupLeaseInterrupted,
}

/// Provider-free state of one managed profile.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub enum BrowserProfileLifecycleState {
    Staged,
    Available,
    Leased {
        generation: BrowserProfileLeaseGeneration,
    },
    Quarantined {
        reason: BrowserProfileQuarantineReason,
    },
    Retired,
}

impl BrowserProfileLifecycleState {
    /// A profile is leaseable only after it is explicitly available.
    pub const fn is_eligible(self) -> bool {
        matches!(self, Self::Available)
    }
}

/// Reducer output carrying the lease-generation watermark across state changes.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserProfileLifecycleTransition {
    next: BrowserProfileLifecycleState,
    latest_generation: Option<BrowserProfileLeaseGeneration>,
}

impl BrowserProfileLifecycleTransition {
    pub const fn next(self) -> BrowserProfileLifecycleState {
        self.next
    }

    pub const fn latest_generation(self) -> Option<BrowserProfileLeaseGeneration> {
        self.latest_generation
    }
}

/// The subsystem that observed a lifecycle transition.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserProfileLifecycleSource {
    Provisioner,
    ForkManager,
    LeaseManager,
    BrowserRuntime,
    Operator,
    StartupClassifier,
}

/// A typed explanation for one persisted lifecycle transition.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserProfileLifecycleReason {
    ProfileStaged,
    ProvisionSucceeded,
    ProvisioningFailed,
    ProvisionOwnershipUncertain,
    ForkChildAvailable,
    ForkOutcomeUncertain,
    LeaseAcquired,
    LeaseReleased,
    LeaseExpired,
    LeaseOwnershipUncertain,
    CorruptionDetected,
    OperatorRetired,
    OperatorReviewedAvailable,
    StartupProvisionInterrupted,
    StartupLeaseInterrupted,
}

/// Typed inputs accepted by the pure profile lifecycle reducer.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserProfileLifecycleEvent {
    ProfileStaged,
    ProvisionSucceeded,
    ProvisionFailed,
    ProvisionOwnershipUncertain,
    ForkChildAvailable,
    ForkChildUncertain,
    LeaseAcquired {
        generation: BrowserProfileLeaseGeneration,
    },
    LeaseReleased {
        generation: BrowserProfileLeaseGeneration,
    },
    LeaseExpired {
        generation: BrowserProfileLeaseGeneration,
    },
    LeaseOwnershipUncertain {
        generation: BrowserProfileLeaseGeneration,
    },
    CorruptionDetected,
    OperatorRetire,
    OperatorReviewApproved,
}

impl BrowserProfileLifecycleEvent {
    pub(super) const fn source(self) -> BrowserProfileLifecycleSource {
        match self {
            Self::ProfileStaged
            | Self::ProvisionSucceeded
            | Self::ProvisionFailed
            | Self::ProvisionOwnershipUncertain => BrowserProfileLifecycleSource::Provisioner,
            Self::ForkChildAvailable | Self::ForkChildUncertain => {
                BrowserProfileLifecycleSource::ForkManager
            }
            Self::LeaseAcquired { .. }
            | Self::LeaseReleased { .. }
            | Self::LeaseExpired { .. }
            | Self::LeaseOwnershipUncertain { .. } => BrowserProfileLifecycleSource::LeaseManager,
            Self::CorruptionDetected => BrowserProfileLifecycleSource::BrowserRuntime,
            Self::OperatorRetire | Self::OperatorReviewApproved => {
                BrowserProfileLifecycleSource::Operator
            }
        }
    }

    pub(super) const fn reason(self) -> BrowserProfileLifecycleReason {
        match self {
            Self::ProfileStaged => BrowserProfileLifecycleReason::ProfileStaged,
            Self::ProvisionSucceeded => BrowserProfileLifecycleReason::ProvisionSucceeded,
            Self::ProvisionFailed => BrowserProfileLifecycleReason::ProvisioningFailed,
            Self::ProvisionOwnershipUncertain => {
                BrowserProfileLifecycleReason::ProvisionOwnershipUncertain
            }
            Self::ForkChildAvailable => BrowserProfileLifecycleReason::ForkChildAvailable,
            Self::ForkChildUncertain => BrowserProfileLifecycleReason::ForkOutcomeUncertain,
            Self::LeaseAcquired { .. } => BrowserProfileLifecycleReason::LeaseAcquired,
            Self::LeaseReleased { .. } => BrowserProfileLifecycleReason::LeaseReleased,
            Self::LeaseExpired { .. } => BrowserProfileLifecycleReason::LeaseExpired,
            Self::LeaseOwnershipUncertain { .. } => {
                BrowserProfileLifecycleReason::LeaseOwnershipUncertain
            }
            Self::CorruptionDetected => BrowserProfileLifecycleReason::CorruptionDetected,
            Self::OperatorRetire => BrowserProfileLifecycleReason::OperatorRetired,
            Self::OperatorReviewApproved => {
                BrowserProfileLifecycleReason::OperatorReviewedAvailable
            }
        }
    }
}

/// Reduces one typed event into the next profile lifecycle state.
pub fn reduce_browser_profile_lifecycle(
    current: BrowserProfileLifecycleState,
    latest_generation: Option<BrowserProfileLeaseGeneration>,
    event: BrowserProfileLifecycleEvent,
) -> Result<BrowserProfileLifecycleTransition, BrowserProfileLifecycleError> {
    use BrowserProfileLifecycleEvent as Event;
    use BrowserProfileLifecycleState as State;

    let (next, next_generation) = match (current, latest_generation, event) {
        (State::Staged, None, Event::ProfileStaged) => (State::Staged, None),
        (State::Staged, None, Event::ProvisionSucceeded | Event::ForkChildAvailable) => {
            (State::Available, None)
        }
        (State::Staged, None, Event::ProvisionFailed) => (
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::ProvisioningFailed,
            },
            None,
        ),
        (State::Staged | State::Available, latest, Event::ProvisionFailed) => (
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::ProvisioningFailed,
            },
            latest,
        ),
        (State::Staged | State::Available, latest, Event::ProvisionOwnershipUncertain) => (
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::ProvisionOwnershipUncertain,
            },
            latest,
        ),
        (State::Staged | State::Available, latest, Event::ForkChildUncertain) => (
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::ForkOutcomeUncertain,
            },
            latest,
        ),
        (State::Available, latest, Event::LeaseAcquired { generation })
            if latest.is_none_or(|last| generation > last) =>
        {
            (State::Leased { generation }, Some(generation))
        }
        (State::Available, Some(_), Event::LeaseAcquired { .. }) => {
            return Err(BrowserProfileLifecycleError::StaleGeneration);
        }
        (State::Leased { generation: active }, latest, Event::LeaseAcquired { generation })
            if generation <= active || latest.is_some_and(|last| generation <= last) =>
        {
            return Err(BrowserProfileLifecycleError::StaleGeneration);
        }
        (State::Leased { generation: active }, latest, Event::LeaseReleased { generation })
            if generation == active && latest == Some(active) =>
        {
            (State::Available, latest)
        }
        (State::Leased { generation: active }, latest, Event::LeaseExpired { generation })
            if generation == active && latest == Some(active) =>
        {
            (
                State::Quarantined {
                    reason: BrowserProfileQuarantineReason::LeaseExpired,
                },
                latest,
            )
        }
        (
            State::Leased { generation: active },
            latest,
            Event::LeaseOwnershipUncertain { generation },
        ) if generation == active && latest == Some(active) => (
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::LeaseOwnershipUncertain,
            },
            latest,
        ),
        (
            State::Leased { generation: active },
            _,
            Event::LeaseReleased { generation }
            | Event::LeaseExpired { generation }
            | Event::LeaseOwnershipUncertain { generation },
        ) if generation != active => {
            return Err(BrowserProfileLifecycleError::StaleGeneration);
        }
        (State::Quarantined { .. }, latest, Event::OperatorReviewApproved) => {
            (State::Available, latest)
        }
        (state, latest, Event::CorruptionDetected) if !matches!(state, State::Retired) => (
            State::Quarantined {
                reason: BrowserProfileQuarantineReason::CorruptionDetected,
            },
            latest,
        ),
        (state, latest, Event::OperatorRetire) if !matches!(state, State::Retired) => {
            (State::Retired, latest)
        }
        _ => return Err(BrowserProfileLifecycleError::InvalidTransition),
    };
    Ok(BrowserProfileLifecycleTransition {
        next,
        latest_generation: next_generation,
    })
}

/// Fails closed on process restart when provisioning or lease ownership may
/// have been interrupted. Other states are preserved without recovery.
pub const fn classify_abandoned_on_startup(
    state: BrowserProfileLifecycleState,
) -> BrowserProfileLifecycleState {
    match state {
        BrowserProfileLifecycleState::Staged => BrowserProfileLifecycleState::Quarantined {
            reason: BrowserProfileQuarantineReason::StartupProvisionInterrupted,
        },
        BrowserProfileLifecycleState::Leased { .. } => BrowserProfileLifecycleState::Quarantined {
            reason: BrowserProfileQuarantineReason::StartupLeaseInterrupted,
        },
        state => state,
    }
}

/// Errors returned by the provider-free profile lifecycle contract.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserProfileLifecycleError {
    #[error("profile lifecycle event is invalid for the current state")]
    InvalidTransition,
    #[error("profile lifecycle event uses a stale lease generation")]
    StaleGeneration,
    #[error("profile lifecycle record is inconsistent")]
    InvalidRecord,
    #[error("profile lifecycle record schema version is unsupported")]
    UnsupportedSchemaVersion,
}
