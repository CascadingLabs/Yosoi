#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;

impl ManagedProfileWarmService {
    pub(super) fn discard_unleased(
        &self,
        spec: &NewProfileSpec,
        plan: &ProfileWarmPlan,
        staging: StagedManagedProfile,
        steps: Vec<ProfileWarmStepReceipt>,
        reason: ProfileWarmTerminalReason,
        lifecycle_staged: bool,
    ) -> Result<ProfileWarmTerminalReceipt, ProfileWarmServiceError> {
        let Ok(lease) = staging.acquire_lease() else {
            if lifecycle_staged {
                let _provision_uncertain = self.commit_lifecycle_event(
                    spec.profile_id(),
                    BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain,
                );
            }
            return Self::receipt(
                spec,
                plan,
                steps,
                ProfileWarmTerminalReason::OwnershipUncertain,
                ProfileWarmProcessCleanup::ConfirmedClosed,
                ProfileWarmProfileDisposition::RetainedUnavailable,
            );
        };
        let disposition = staging
            .discard(lease.release_after_confirmed_browser_close())
            .map_or(ProfileWarmProfileDisposition::RetainedUnavailable, |_| {
                ProfileWarmProfileDisposition::Removed
            });
        if disposition == ProfileWarmProfileDisposition::RetainedUnavailable {
            if lifecycle_staged {
                let _provision_uncertain = self.commit_lifecycle_event(
                    spec.profile_id(),
                    BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain,
                );
            }
            return Self::receipt(
                spec,
                plan,
                steps,
                ProfileWarmTerminalReason::OwnershipUncertain,
                ProfileWarmProcessCleanup::ConfirmedClosed,
                disposition,
            );
        }
        if lifecycle_staged
            && self
                .commit_lifecycle_event(
                    spec.profile_id(),
                    BrowserProfileLifecycleEvent::ProvisionFailed,
                )
                .is_err()
        {
            return Self::receipt(
                spec,
                plan,
                steps,
                ProfileWarmTerminalReason::OwnershipUncertain,
                ProfileWarmProcessCleanup::ConfirmedClosed,
                disposition,
            );
        }
        Self::receipt(
            spec,
            plan,
            steps,
            reason,
            ProfileWarmProcessCleanup::ConfirmedClosed,
            disposition,
        )
    }

    pub(super) fn finish_after_cleanup(
        &self,
        spec: &NewProfileSpec,
        plan: &ProfileWarmPlan,
        staging: StagedManagedProfile,
        steps: Vec<ProfileWarmStepReceipt>,
        reason: ProfileWarmTerminalReason,
        cleanup: ProfileWarmCleanupOutcome,
    ) -> Result<ProfileWarmTerminalReceipt, ProfileWarmServiceError> {
        if !cleanup.succeeded {
            let _provision_uncertain = self.commit_lifecycle_event(
                spec.profile_id(),
                BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain,
            );
            return Self::receipt(
                spec,
                plan,
                steps,
                ProfileWarmTerminalReason::CleanupFailed,
                ProfileWarmProcessCleanup::Uncertain,
                ProfileWarmProfileDisposition::RetainedUnavailable,
            );
        }
        let Some(release) = cleanup.staging_release else {
            let _provision_uncertain = self.commit_lifecycle_event(
                spec.profile_id(),
                BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain,
            );
            return Self::receipt(
                spec,
                plan,
                steps,
                ProfileWarmTerminalReason::CleanupFailed,
                ProfileWarmProcessCleanup::Uncertain,
                ProfileWarmProfileDisposition::RetainedUnavailable,
            );
        };
        if reason == ProfileWarmTerminalReason::Completed
            && steps.iter().all(|step| {
                matches!(step.outcome(), ProfileWarmStepOutcome::Navigation(receipt)
                    if receipt.outcome() == BrowserNavigationOutcome::Completed
                        && readiness_reached(plan.readiness(), receipt.reached_readiness()))
            })
        {
            let published = match staging.publish(release) {
                Ok(_) => true,
                Err(error)
                    if error.disposition
                        == ManagedProfileStagingDisposition::PublishedAvailable =>
                {
                    true
                }
                Err(_) => {
                    let _provision_uncertain = self.commit_lifecycle_event(
                        spec.profile_id(),
                        BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain,
                    );
                    return Self::receipt(
                        spec,
                        plan,
                        steps,
                        ProfileWarmTerminalReason::OwnershipUncertain,
                        ProfileWarmProcessCleanup::ConfirmedClosed,
                        ProfileWarmProfileDisposition::RetainedUnavailable,
                    );
                }
            };
            if published
                && self
                    .commit_lifecycle_event(
                        spec.profile_id(),
                        BrowserProfileLifecycleEvent::ProvisionSucceeded,
                    )
                    .is_ok()
            {
                return Self::receipt(
                    spec,
                    plan,
                    steps,
                    ProfileWarmTerminalReason::Completed,
                    ProfileWarmProcessCleanup::ConfirmedClosed,
                    ProfileWarmProfileDisposition::PublishedAvailable,
                );
            }
            let _provision_uncertain = self.commit_lifecycle_event(
                spec.profile_id(),
                BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain,
            );
            return Self::receipt(
                spec,
                plan,
                steps,
                ProfileWarmTerminalReason::OwnershipUncertain,
                ProfileWarmProcessCleanup::ConfirmedClosed,
                ProfileWarmProfileDisposition::RetainedUnavailable,
            );
        }
        let disposition = staging
            .discard(release)
            .map_or(ProfileWarmProfileDisposition::RetainedUnavailable, |_| {
                ProfileWarmProfileDisposition::Removed
            });
        let reason = if disposition == ProfileWarmProfileDisposition::RetainedUnavailable {
            ProfileWarmTerminalReason::OwnershipUncertain
        } else {
            reason
        };
        let lifecycle_event = if disposition == ProfileWarmProfileDisposition::RetainedUnavailable {
            BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain
        } else {
            BrowserProfileLifecycleEvent::ProvisionFailed
        };
        let lifecycle_failed = self
            .commit_lifecycle_event(spec.profile_id(), lifecycle_event)
            .is_err();
        Self::receipt(
            spec,
            plan,
            steps,
            if lifecycle_failed {
                ProfileWarmTerminalReason::OwnershipUncertain
            } else {
                reason
            },
            ProfileWarmProcessCleanup::ConfirmedClosed,
            disposition,
        )
    }

    pub(super) fn commit_lifecycle_event(
        &self,
        profile_id: &BrowserProfileId,
        event: BrowserProfileLifecycleEvent,
    ) -> Result<(), ProfileLifecycleStoreError> {
        self.lifecycle
            .transition(profile_id, wall_now(), event)
            .map(|_| ())
    }

    pub(super) fn receipt(
        spec: &NewProfileSpec,
        plan: &ProfileWarmPlan,
        steps: Vec<ProfileWarmStepReceipt>,
        reason: ProfileWarmTerminalReason,
        cleanup: ProfileWarmProcessCleanup,
        disposition: ProfileWarmProfileDisposition,
    ) -> Result<ProfileWarmTerminalReceipt, ProfileWarmServiceError> {
        ProfileWarmTerminalReceipt::new(spec, plan, steps, reason, cleanup, disposition)
            .map_err(|_| ProfileWarmServiceError::ReceiptInvariant)
    }
}
