use std::{
    collections::HashSet,
    fmt,
    num::{NonZeroU32, NonZeroU64},
};

use crate::internal::types::ActivityId;
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use super::super::{BrowserNavigationReadinessCheckpoint, BrowserProfileId, BrowserProfileOwnerId};
use crate::internal::web_capture::RequestedWebTarget;

/// Largest caller-supplied warm-up plan admitted by this domain contract.
pub const MAX_PROFILE_WARM_TARGETS: u32 = 64;
/// Largest allowed bound for an individual warm-up navigation, in milliseconds.
pub const MAX_PROFILE_WARM_NAVIGATION_MILLISECONDS: u64 = 300_000;
/// Largest allowed overall warm-up bound, in milliseconds.
pub const MAX_PROFILE_WARM_OVERALL_MILLISECONDS: u64 = 1_800_000;

/// Validated identity and lease owner for a profile being provisioned.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NewProfileSpec {
    pub(super) profile_id: BrowserProfileId,
    pub(super) owner_id: BrowserProfileOwnerId,
}

impl NewProfileSpec {
    pub const fn new(profile_id: BrowserProfileId, owner_id: BrowserProfileOwnerId) -> Self {
        Self {
            profile_id,
            owner_id,
        }
    }

    pub const fn profile_id(&self) -> &BrowserProfileId {
        &self.profile_id
    }

    pub const fn owner_id(&self) -> BrowserProfileOwnerId {
        self.owner_id
    }
}

macro_rules! profile_warm_id {
    ($name:ident) => {
        #[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
        #[serde(transparent)]
        pub struct $name(ActivityId);

        impl $name {
            pub fn random() -> Self {
                Self(ActivityId::random())
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                self.0.fmt(formatter)
            }
        }
    };
}

profile_warm_id!(ProfileWarmPlanId);

/// Explicit upper bounds for one ordered profile warm-up plan.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileWarmBounds {
    maximum_targets: NonZeroU32,
    navigation_milliseconds: NonZeroU64,
    overall_milliseconds: NonZeroU64,
}

impl ProfileWarmBounds {
    pub fn new(
        maximum_targets: u32,
        navigation_milliseconds: u64,
        overall_milliseconds: u64,
    ) -> Result<Self, ProfileWarmPlanError> {
        let maximum_targets =
            NonZeroU32::new(maximum_targets).ok_or(ProfileWarmPlanError::ZeroTargetLimit)?;
        if maximum_targets.get() > MAX_PROFILE_WARM_TARGETS {
            return Err(ProfileWarmPlanError::TargetLimitTooLarge);
        }
        let navigation_milliseconds = NonZeroU64::new(navigation_milliseconds)
            .ok_or(ProfileWarmPlanError::ZeroNavigationDeadline)?;
        if navigation_milliseconds.get() > MAX_PROFILE_WARM_NAVIGATION_MILLISECONDS {
            return Err(ProfileWarmPlanError::NavigationDeadlineTooLarge);
        }
        let overall_milliseconds = NonZeroU64::new(overall_milliseconds)
            .ok_or(ProfileWarmPlanError::ZeroOverallDeadline)?;
        if overall_milliseconds.get() > MAX_PROFILE_WARM_OVERALL_MILLISECONDS {
            return Err(ProfileWarmPlanError::OverallDeadlineTooLarge);
        }
        if overall_milliseconds < navigation_milliseconds {
            return Err(ProfileWarmPlanError::OverallDeadlineShorterThanNavigation);
        }
        Ok(Self {
            maximum_targets,
            navigation_milliseconds,
            overall_milliseconds,
        })
    }

    pub const fn maximum_targets(self) -> u32 {
        self.maximum_targets.get()
    }

    pub const fn navigation_milliseconds(self) -> u64 {
        self.navigation_milliseconds.get()
    }

    pub const fn overall_milliseconds(self) -> u64 {
        self.overall_milliseconds.get()
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProfileWarmBoundsWire {
    maximum_targets: u32,
    navigation_milliseconds: u64,
    overall_milliseconds: u64,
}

impl<'de> Deserialize<'de> for ProfileWarmBounds {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = ProfileWarmBoundsWire::deserialize(deserializer)?;
        Self::new(
            wire.maximum_targets,
            wire.navigation_milliseconds,
            wire.overall_milliseconds,
        )
        .map_err(D::Error::custom)
    }
}

/// Stable one-based position of a target within a warm plan.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(transparent)]
pub struct ProfileWarmStepNumber(NonZeroU32);

impl ProfileWarmStepNumber {
    pub const fn get(self) -> u32 {
        self.0.get()
    }
}

/// Stable identity for one target step, derived from its plan and position.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileWarmStepId {
    pub(super) plan: ProfileWarmPlanId,
    pub(super) number: ProfileWarmStepNumber,
}

impl ProfileWarmStepId {
    pub const fn plan(self) -> ProfileWarmPlanId {
        self.plan
    }

    pub const fn number(self) -> ProfileWarmStepNumber {
        self.number
    }
}

/// One caller-supplied target in the plan. Debug output hides its URL.
#[derive(Clone, Eq, PartialEq)]
pub struct ProfileWarmStep {
    id: ProfileWarmStepId,
    target: RequestedWebTarget,
}

impl ProfileWarmStep {
    pub const fn id(&self) -> ProfileWarmStepId {
        self.id
    }

    pub const fn target(&self) -> &RequestedWebTarget {
        &self.target
    }
}

impl fmt::Debug for ProfileWarmStep {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProfileWarmStep")
            .field("id", &self.id)
            .field("target", &"<redacted>")
            .finish()
    }
}

/// Validated, ordered navigation-only warm-up plan.
#[derive(Clone, Eq, PartialEq)]
pub struct ProfileWarmPlan {
    pub(super) id: ProfileWarmPlanId,
    pub(super) steps: Vec<ProfileWarmStep>,
    pub(super) bounds: ProfileWarmBounds,
    pub(super) readiness: BrowserNavigationReadinessCheckpoint,
}

impl ProfileWarmPlan {
    pub fn new(
        targets: Vec<RequestedWebTarget>,
        bounds: ProfileWarmBounds,
        readiness: BrowserNavigationReadinessCheckpoint,
    ) -> Result<Self, ProfileWarmPlanError> {
        Self::with_id(ProfileWarmPlanId::random(), targets, bounds, readiness)
    }

    pub fn with_id(
        id: ProfileWarmPlanId,
        targets: Vec<RequestedWebTarget>,
        bounds: ProfileWarmBounds,
        readiness: BrowserNavigationReadinessCheckpoint,
    ) -> Result<Self, ProfileWarmPlanError> {
        if targets.is_empty() {
            return Err(ProfileWarmPlanError::EmptyPlan);
        }
        if targets.len()
            > usize::try_from(bounds.maximum_targets())
                .map_err(|_| ProfileWarmPlanError::TargetLimitTooLarge)?
        {
            return Err(ProfileWarmPlanError::TooManyTargets);
        }
        if readiness == BrowserNavigationReadinessCheckpoint::NetworkIdle {
            return Err(ProfileWarmPlanError::UnsupportedReadiness);
        }
        let mut unique_targets = HashSet::with_capacity(targets.len());
        for target in &targets {
            if !unique_targets.insert(target) {
                return Err(ProfileWarmPlanError::DuplicateTarget);
            }
        }

        let mut steps = Vec::with_capacity(targets.len());
        for (index, target) in targets.into_iter().enumerate() {
            let one_based = index
                .checked_add(1)
                .and_then(|number| u32::try_from(number).ok())
                .and_then(NonZeroU32::new)
                .ok_or(ProfileWarmPlanError::TooManyTargets)?;
            steps.push(ProfileWarmStep {
                id: ProfileWarmStepId {
                    plan: id,
                    number: ProfileWarmStepNumber(one_based),
                },
                target,
            });
        }
        Ok(Self {
            id,
            steps,
            bounds,
            readiness,
        })
    }

    pub const fn id(&self) -> ProfileWarmPlanId {
        self.id
    }

    pub fn steps(&self) -> &[ProfileWarmStep] {
        &self.steps
    }

    pub const fn bounds(&self) -> ProfileWarmBounds {
        self.bounds
    }

    pub const fn readiness(&self) -> BrowserNavigationReadinessCheckpoint {
        self.readiness
    }
}

impl fmt::Debug for ProfileWarmPlan {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProfileWarmPlan")
            .field("id", &self.id)
            .field("target_count", &self.steps.len())
            .field("bounds", &self.bounds)
            .field("readiness", &self.readiness)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ProfileWarmPlanError {
    #[error("profile warm-up plan must contain at least one target")]
    EmptyPlan,
    #[error("profile warm-up plan exceeds its target limit")]
    TooManyTargets,
    #[error("profile warm-up target limit must be non-zero")]
    ZeroTargetLimit,
    #[error("profile warm-up target limit exceeds the supported maximum")]
    TargetLimitTooLarge,
    #[error("profile warm-up navigation deadline must be non-zero")]
    ZeroNavigationDeadline,
    #[error("profile warm-up navigation deadline exceeds the supported maximum")]
    NavigationDeadlineTooLarge,
    #[error("profile warm-up overall deadline must be non-zero")]
    ZeroOverallDeadline,
    #[error("profile warm-up overall deadline exceeds the supported maximum")]
    OverallDeadlineTooLarge,
    #[error("overall profile warm-up deadline is shorter than one navigation deadline")]
    OverallDeadlineShorterThanNavigation,
    #[error("profile warm-up target list contains a duplicate target")]
    DuplicateTarget,
    #[error("network-idle readiness is not supported by the navigation scheduler")]
    UnsupportedReadiness,
}
