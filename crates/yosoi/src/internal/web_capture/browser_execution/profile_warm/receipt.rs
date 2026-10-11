use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use super::super::{
    BrowserNavigationOutcome, BrowserNavigationReadinessCheckpoint,
    BrowserNavigationTerminalReceipt, BrowserProfileId, BrowserProfileOwnerId,
};
use super::{
    NewProfileSpec, ProfileWarmBounds, ProfileWarmPlan, ProfileWarmPlanId, ProfileWarmStepId,
};

/// Result recorded for one planned target without retaining its URL.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProfileWarmStepOutcome {
    Navigation(BrowserNavigationTerminalReceipt),
    NotAttempted,
}

/// Secret-safe receipt for one target position in a warm plan.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileWarmStepReceipt {
    step: ProfileWarmStepId,
    outcome: ProfileWarmStepOutcome,
}

impl ProfileWarmStepReceipt {
    pub fn navigation(
        step: ProfileWarmStepId,
        outcome: BrowserNavigationTerminalReceipt,
    ) -> Result<Self, ProfileWarmReceiptError> {
        let receipt = Self {
            step,
            outcome: ProfileWarmStepOutcome::Navigation(outcome),
        };
        receipt.validate()?;
        Ok(receipt)
    }

    pub const fn not_attempted(step: ProfileWarmStepId) -> Self {
        Self {
            step,
            outcome: ProfileWarmStepOutcome::NotAttempted,
        }
    }

    pub const fn step(self) -> ProfileWarmStepId {
        self.step
    }

    pub const fn outcome(self) -> ProfileWarmStepOutcome {
        self.outcome
    }

    fn validate(self) -> Result<(), ProfileWarmReceiptError> {
        if let ProfileWarmStepOutcome::Navigation(navigation) = self.outcome {
            if navigation.requested_readiness() == BrowserNavigationReadinessCheckpoint::NetworkIdle
            {
                return Err(ProfileWarmReceiptError::UnsupportedReadiness);
            }
            if navigation.outcome() == BrowserNavigationOutcome::Completed
                && navigation.reached_readiness().is_none()
            {
                return Err(ProfileWarmReceiptError::MissingReachedReadiness);
            }
        }
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProfileWarmStepReceiptWire {
    step: ProfileWarmStepId,
    outcome: ProfileWarmStepOutcome,
}

impl TryFrom<ProfileWarmStepReceiptWire> for ProfileWarmStepReceipt {
    type Error = ProfileWarmReceiptError;

    fn try_from(value: ProfileWarmStepReceiptWire) -> Result<Self, Self::Error> {
        let receipt = Self {
            step: value.step,
            outcome: value.outcome,
        };
        receipt.validate()?;
        Ok(receipt)
    }
}

impl<'de> Deserialize<'de> for ProfileWarmStepReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        ProfileWarmStepReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProfileWarmTerminalReason {
    Completed,
    StagingFailed,
    NavigationFailed,
    CallerCancelled,
    DeadlineExceeded,
    ProfileLeaseExpired,
    ProviderDisconnected,
    CleanupFailed,
    OwnershipUncertain,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProfileWarmProcessCleanup {
    ConfirmedClosed,
    Failed,
    DeadlineExceeded,
    Uncertain,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProfileWarmProfileDisposition {
    PublishedAvailable,
    Removed,
    RetainedUnavailable,
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ProfileWarmReceiptError {
    #[error("profile warm-up receipt must contain one outcome for each planned target")]
    TargetCountMismatch,
    #[error("profile warm-up receipt step identity or order does not match its plan")]
    StepOrderMismatch,
    #[error("profile warm-up step readiness does not match its plan")]
    ReadinessMismatch,
    #[error("network-idle readiness is not supported by the navigation scheduler")]
    UnsupportedReadiness,
    #[error("completed profile warm-up navigation has no reached-readiness fact")]
    MissingReachedReadiness,
    #[error("profile warm-up navigated after an earlier step stopped or was skipped")]
    NavigationAfterStop,
    #[error("completed profile warm-up requires every target navigation to complete")]
    CompletionWithIncompleteNavigation,
    #[error("navigation-failed terminal reason requires an unsuccessful navigation")]
    NavigationFailureWithoutFailure,
    #[error("profile warm-up cannot publish before confirmed browser-process cleanup")]
    PublishedBeforeCleanup,
    #[error("profile warm-up may publish only after every navigation succeeds")]
    PublishedIncompleteProfile,
    #[error("unconfirmed browser cleanup must retain the profile unavailable")]
    UnconfirmedCleanupDisposition,
}

/// Secret-safe terminal record for one profile warm-up transaction.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileWarmTerminalReceipt {
    profile_id: BrowserProfileId,
    owner_id: BrowserProfileOwnerId,
    plan_id: ProfileWarmPlanId,
    target_count: u32,
    bounds: ProfileWarmBounds,
    readiness: BrowserNavigationReadinessCheckpoint,
    steps: Vec<ProfileWarmStepReceipt>,
    reason: ProfileWarmTerminalReason,
    process_cleanup: ProfileWarmProcessCleanup,
    profile_disposition: ProfileWarmProfileDisposition,
}

impl ProfileWarmTerminalReceipt {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        spec: &NewProfileSpec,
        plan: &ProfileWarmPlan,
        steps: Vec<ProfileWarmStepReceipt>,
        reason: ProfileWarmTerminalReason,
        process_cleanup: ProfileWarmProcessCleanup,
        profile_disposition: ProfileWarmProfileDisposition,
    ) -> Result<Self, ProfileWarmReceiptError> {
        let target_count = u32::try_from(plan.steps.len())
            .map_err(|_| ProfileWarmReceiptError::TargetCountMismatch)?;
        validate_steps(
            plan.id,
            target_count,
            plan.bounds,
            plan.readiness,
            &steps,
            reason,
            process_cleanup,
            profile_disposition,
        )?;
        Ok(Self {
            profile_id: spec.profile_id.clone(),
            owner_id: spec.owner_id,
            plan_id: plan.id,
            target_count,
            bounds: plan.bounds,
            readiness: plan.readiness,
            steps,
            reason,
            process_cleanup,
            profile_disposition,
        })
    }

    pub const fn profile_id(&self) -> &BrowserProfileId {
        &self.profile_id
    }

    pub const fn owner_id(&self) -> BrowserProfileOwnerId {
        self.owner_id
    }

    pub const fn plan_id(&self) -> ProfileWarmPlanId {
        self.plan_id
    }

    pub const fn target_count(&self) -> u32 {
        self.target_count
    }

    pub const fn bounds(&self) -> ProfileWarmBounds {
        self.bounds
    }

    pub const fn readiness(&self) -> BrowserNavigationReadinessCheckpoint {
        self.readiness
    }

    pub fn steps(&self) -> &[ProfileWarmStepReceipt] {
        &self.steps
    }

    pub const fn reason(&self) -> ProfileWarmTerminalReason {
        self.reason
    }

    pub const fn process_cleanup(&self) -> ProfileWarmProcessCleanup {
        self.process_cleanup
    }

    pub const fn profile_disposition(&self) -> ProfileWarmProfileDisposition {
        self.profile_disposition
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProfileWarmTerminalReceiptWire {
    profile_id: BrowserProfileId,
    owner_id: BrowserProfileOwnerId,
    plan_id: ProfileWarmPlanId,
    target_count: u32,
    bounds: ProfileWarmBounds,
    readiness: BrowserNavigationReadinessCheckpoint,
    steps: Vec<ProfileWarmStepReceipt>,
    reason: ProfileWarmTerminalReason,
    process_cleanup: ProfileWarmProcessCleanup,
    profile_disposition: ProfileWarmProfileDisposition,
}

impl TryFrom<ProfileWarmTerminalReceiptWire> for ProfileWarmTerminalReceipt {
    type Error = ProfileWarmReceiptError;

    fn try_from(value: ProfileWarmTerminalReceiptWire) -> Result<Self, Self::Error> {
        validate_steps(
            value.plan_id,
            value.target_count,
            value.bounds,
            value.readiness,
            &value.steps,
            value.reason,
            value.process_cleanup,
            value.profile_disposition,
        )?;
        Ok(Self {
            profile_id: value.profile_id,
            owner_id: value.owner_id,
            plan_id: value.plan_id,
            target_count: value.target_count,
            bounds: value.bounds,
            readiness: value.readiness,
            steps: value.steps,
            reason: value.reason,
            process_cleanup: value.process_cleanup,
            profile_disposition: value.profile_disposition,
        })
    }
}

impl<'de> Deserialize<'de> for ProfileWarmTerminalReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        ProfileWarmTerminalReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

// These independent receipt fields jointly define the validation invariant;
// grouping them into a synthetic argument would obscure the wire contract.
#[allow(clippy::too_many_arguments)]
fn validate_steps(
    plan_id: ProfileWarmPlanId,
    target_count: u32,
    bounds: ProfileWarmBounds,
    readiness: BrowserNavigationReadinessCheckpoint,
    receipts: &[ProfileWarmStepReceipt],
    reason: ProfileWarmTerminalReason,
    process_cleanup: ProfileWarmProcessCleanup,
    profile_disposition: ProfileWarmProfileDisposition,
) -> Result<(), ProfileWarmReceiptError> {
    let receipt_count =
        u32::try_from(receipts.len()).map_err(|_| ProfileWarmReceiptError::TargetCountMismatch)?;
    if target_count == 0 || receipt_count != target_count || target_count > bounds.maximum_targets()
    {
        return Err(ProfileWarmReceiptError::TargetCountMismatch);
    }
    if readiness == BrowserNavigationReadinessCheckpoint::NetworkIdle {
        return Err(ProfileWarmReceiptError::UnsupportedReadiness);
    }
    let mut stopped = false;
    let mut incomplete_navigation = false;
    for (index, receipt) in receipts.iter().enumerate() {
        let expected_number = index
            .checked_add(1)
            .and_then(|number| u32::try_from(number).ok())
            .ok_or(ProfileWarmReceiptError::TargetCountMismatch)?;
        if receipt.step.plan != plan_id || receipt.step.number.get() != expected_number {
            return Err(ProfileWarmReceiptError::StepOrderMismatch);
        }
        receipt.validate()?;
        match receipt.outcome {
            ProfileWarmStepOutcome::Navigation(navigation) => {
                if navigation.requested_readiness() != readiness {
                    return Err(ProfileWarmReceiptError::ReadinessMismatch);
                }
                if stopped {
                    return Err(ProfileWarmReceiptError::NavigationAfterStop);
                }
                if navigation.outcome() != BrowserNavigationOutcome::Completed {
                    stopped = true;
                    incomplete_navigation = true;
                }
            }
            ProfileWarmStepOutcome::NotAttempted => stopped = true,
        }
    }
    let all_navigations_completed = !stopped;
    if reason == ProfileWarmTerminalReason::Completed && !all_navigations_completed {
        return Err(ProfileWarmReceiptError::CompletionWithIncompleteNavigation);
    }
    if reason == ProfileWarmTerminalReason::NavigationFailed && !incomplete_navigation {
        return Err(ProfileWarmReceiptError::NavigationFailureWithoutFailure);
    }
    if profile_disposition == ProfileWarmProfileDisposition::PublishedAvailable {
        if process_cleanup != ProfileWarmProcessCleanup::ConfirmedClosed {
            return Err(ProfileWarmReceiptError::PublishedBeforeCleanup);
        }
        if reason != ProfileWarmTerminalReason::Completed || !all_navigations_completed {
            return Err(ProfileWarmReceiptError::PublishedIncompleteProfile);
        }
    }
    if process_cleanup != ProfileWarmProcessCleanup::ConfirmedClosed
        && profile_disposition != ProfileWarmProfileDisposition::RetainedUnavailable
    {
        return Err(ProfileWarmReceiptError::UnconfirmedCleanupDisposition);
    }
    if reason == ProfileWarmTerminalReason::Completed
        && profile_disposition != ProfileWarmProfileDisposition::PublishedAvailable
    {
        return Err(ProfileWarmReceiptError::PublishedIncompleteProfile);
    }
    Ok(())
}
