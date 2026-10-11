#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;

mod cleanup;

impl ManagedProfileWarmService {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        registry: provider::ProfileRegistry,
        lifecycle: ProfileLifecycleStore,
        generations: Arc<BrowserProfileLeaseGenerationRegistry>,
        manager_limits: BrowserExecutionLimits,
        manager_config: BrowserExecutionManagerConfig,
        scheduler_limits: BrowserNavigationSchedulerLimits,
        lease_duration: Duration,
    ) -> Result<Self, ProfileWarmServiceError> {
        if manager_limits.processes().get() != 1
            || manager_limits.contexts_total().get() != 1
            || manager_limits.contexts_per_process().get() != 1
        {
            return Err(ProfileWarmServiceError::InvalidManagerLimits);
        }
        if lease_duration.is_zero() {
            return Err(ProfileWarmServiceError::InvalidLeaseDuration);
        }
        if scheduler_limits.active_navigations().get() > manager_limits.tabs_total().get() {
            return Err(ProfileWarmServiceError::InvalidSchedulerLimits);
        }
        Ok(Self {
            registry,
            lifecycle,
            generations,
            manager_limits,
            manager_config,
            scheduler_limits,
            lease_duration,
        })
    }

    /// Stages, warms, and publishes a new profile after confirmed browser close.
    pub async fn provision(
        &self,
        spec: NewProfileSpec,
        plan: &ProfileWarmPlan,
        cancellation: &CancellationToken,
    ) -> Result<ProfileWarmTerminalReceipt, ProfileWarmServiceError> {
        let overall_deadline = Instant::now()
            .checked_add(Duration::from_millis(plan.bounds().overall_milliseconds()))
            .ok_or(ProfileWarmServiceError::DeadlineOverflow)?;
        if cancellation.is_cancelled() {
            return Self::receipt(
                &spec,
                plan,
                empty_steps(plan),
                ProfileWarmTerminalReason::CallerCancelled,
                ProfileWarmProcessCleanup::ConfirmedClosed,
                ProfileWarmProfileDisposition::Removed,
            );
        }
        if Instant::now() >= overall_deadline {
            return Self::receipt(
                &spec,
                plan,
                empty_steps(plan),
                ProfileWarmTerminalReason::DeadlineExceeded,
                ProfileWarmProcessCleanup::ConfirmedClosed,
                ProfileWarmProfileDisposition::Removed,
            );
        }
        let staging =
            match self
                .registry
                .stage_profile(spec.profile_id().as_str(), None, Vec::new())
            {
                Ok(staged) => staged,
                Err(error) => {
                    let disposition = match error.disposition {
                        ManagedProfileStagingDisposition::NotCreated
                        | ManagedProfileStagingDisposition::Discarded => {
                            ProfileWarmProfileDisposition::Removed
                        }
                        ManagedProfileStagingDisposition::StagedUnavailable
                        | ManagedProfileStagingDisposition::PublishedAvailable
                        | ManagedProfileStagingDisposition::RetainedUnavailable => {
                            ProfileWarmProfileDisposition::RetainedUnavailable
                        }
                    };
                    return Self::receipt(
                        &spec,
                        plan,
                        empty_steps(plan),
                        ProfileWarmTerminalReason::StagingFailed,
                        ProfileWarmProcessCleanup::ConfirmedClosed,
                        disposition,
                    );
                }
            };

        if self
            .lifecycle
            .stage_profile(spec.profile_id(), wall_now())
            .is_err()
        {
            return Self::discard_unleased(
                self,
                &spec,
                plan,
                staging,
                empty_steps(plan),
                ProfileWarmTerminalReason::StagingFailed,
                false,
            );
        }

        if cancellation.is_cancelled() {
            return Self::discard_unleased(
                self,
                &spec,
                plan,
                staging,
                empty_steps(plan),
                ProfileWarmTerminalReason::CallerCancelled,
                true,
            );
        }
        if Instant::now() >= overall_deadline {
            return Self::discard_unleased(
                self,
                &spec,
                plan,
                staging,
                empty_steps(plan),
                ProfileWarmTerminalReason::DeadlineExceeded,
                true,
            );
        }

        let Ok(staged_lease) = staging.acquire_lease() else {
            let _provision_uncertain = self.commit_lifecycle_event(
                spec.profile_id(),
                BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain,
            );
            return Self::receipt(
                &spec,
                plan,
                empty_steps(plan),
                ProfileWarmTerminalReason::StagingFailed,
                ProfileWarmProcessCleanup::ConfirmedClosed,
                ProfileWarmProfileDisposition::RetainedUnavailable,
            );
        };

        let Ok(manager) = BrowserExecutionManager::new_staged_managed_profile(
            self.manager_limits,
            self.manager_config,
            self.registry.clone(),
            spec.profile_id().clone(),
            spec.owner_id(),
            self.lifecycle.clone(),
            Arc::clone(&self.generations),
            self.lease_duration,
            staged_lease,
        ) else {
            let _provision_uncertain = self.commit_lifecycle_event(
                spec.profile_id(),
                BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain,
            );
            return Self::receipt(
                &spec,
                plan,
                empty_steps(plan),
                ProfileWarmTerminalReason::StagingFailed,
                ProfileWarmProcessCleanup::ConfirmedClosed,
                ProfileWarmProfileDisposition::RetainedUnavailable,
            );
        };
        let Ok(scheduler) = BrowserNavigationScheduler::new(manager.clone(), self.scheduler_limits)
        else {
            let cleanup = manager.shutdown().await;
            let cleanup = ProfileWarmCleanupOutcome {
                succeeded: cleanup.is_ok(),
                staging_release: manager.take_managed_profile_staging_release(),
            };
            return self.finish_after_cleanup(
                &spec,
                plan,
                staging,
                empty_steps(plan),
                ProfileWarmTerminalReason::StagingFailed,
                cleanup,
            );
        };

        let (steps, reason) =
            execute_warm_plan(&scheduler, plan, cancellation, overall_deadline).await?;

        let scheduler_cleanup = scheduler.shutdown().await;
        let manager_cleanup = manager.shutdown().await;
        let cleanup = ProfileWarmCleanupOutcome {
            succeeded: scheduler_cleanup.is_ok() && manager_cleanup.is_ok(),
            staging_release: manager.take_managed_profile_staging_release(),
        };
        self.finish_after_cleanup(&spec, plan, staging, steps, reason, cleanup)
    }
}
