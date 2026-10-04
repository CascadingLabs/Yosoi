use super::super::{ManagerInner, shutdown_inner};
#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;
use tokio::time::{Instant as TokioInstant, sleep_until};

impl ManagedProfileTenancy {
    /// Acquires the profile file lock before launching Chrome and starts the
    /// monotonic expiry watchdog for this exact generation.
    pub(in crate::browser_runtime::browser_execution) fn acquire_before_launch(
        self: &Arc<Self>,
        manager: &Arc<ManagerInner>,
    ) -> Result<ManagedProfileLaunch, BrowserExecutionManagerError> {
        let child_contract_now: DateTime<Utc> = SystemTime::now().into();
        self.child_contract_store
            .authorize_profile(&self.profile_id, &child_contract_now)
            .map_err(map_child_contract_error)?;
        let mut state = self
            .state
            .lock()
            .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
        if matches!(&*state, ManagedProfileState::Staged { .. }) {
            let lifecycle_record = self
                .lifecycle
                .record(&self.profile_id)
                .map_err(|_| BrowserExecutionManagerError::ManagedProfileUnavailable)?
                .ok_or(BrowserExecutionManagerError::ManagedProfileUnavailable)?;
            if lifecycle_record.next() != BrowserProfileLifecycleState::Staged {
                return Err(BrowserExecutionManagerError::ManagedProfileUnavailable);
            }
            let wall_now: DateTime<Utc> = SystemTime::now().into();
            let child_expiry = self
                .child_contract_store
                .authorize_profile(&self.profile_id, &wall_now)
                .map_err(map_child_contract_error)?;
            let lease_duration = self.lease_duration_for_child(&wall_now, child_expiry.as_ref())?;
            let generation = self
                .generations
                .next_generation(&self.profile_id)
                .map_err(|_| BrowserExecutionManagerError::ManagedProfileUnavailable)?;
            let now = Instant::now();
            let fence = BrowserProfileLeaseFence::start(
                self.profile_id.clone(),
                yosoi::BrowserProfileLeaseId::random(),
                self.owner_id,
                generation,
                Arc::clone(&self.generations),
                lease_duration,
                now,
                wall_now,
            )
            .map_err(|_| BrowserExecutionManagerError::ManagedProfileUnavailable)?;
            let registry_lease = match &mut *state {
                ManagedProfileState::Staged { registry_lease } => registry_lease
                    .take()
                    .ok_or(BrowserExecutionManagerError::InternalInvariant)?,
                _ => return Err(BrowserExecutionManagerError::InternalInvariant),
            };
            let user_data_dir = registry_lease.path().to_path_buf();
            let deadline = fence.deadline();
            *state = ManagedProfileState::Held {
                registry_lease,
                fence,
                process_generation: None,
                lifecycle_leased: false,
                ownership_uncertain: false,
            };
            drop(state);

            let profile = Arc::clone(self);
            let manager = Arc::downgrade(manager);
            tokio::spawn(async move {
                sleep_until(TokioInstant::from_std(deadline)).await;
                if !profile.is_expired_generation(generation, Instant::now()) {
                    return;
                }
                let Some(manager) = manager.upgrade() else {
                    return;
                };
                if shutdown_inner(manager).await.is_err() {
                    // The detached expiry worker has no caller to receive a
                    // persistence failure; the method still marks in-memory
                    // ownership uncertain before attempting the durable event.
                    let _ = profile.mark_ownership_uncertain();
                }
            });

            return Ok(ManagedProfileLaunch {
                user_data_dir,
                generation,
                deadline,
            });
        }

        let (user_data_dir, generation, deadline, newly_acquired) = match &*state {
            ManagedProfileState::Held {
                registry_lease,
                fence,
                ownership_uncertain,
                ..
            } => {
                if *ownership_uncertain {
                    return Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain);
                }
                fence
                    .authorize(fence.generation(), Instant::now())
                    .map_err(|_| BrowserExecutionManagerError::ManagedProfileExpired)?;
                (
                    registry_lease.path().to_path_buf(),
                    fence.generation(),
                    fence.deadline(),
                    false,
                )
            }
            ManagedProfileState::Unleased => {
                let wall_now: DateTime<Utc> = SystemTime::now().into();
                let child_expiry = self
                    .child_contract_store
                    .authorize_profile(&self.profile_id, &wall_now)
                    .map_err(map_child_contract_error)?;
                let lease_duration =
                    self.lease_duration_for_child(&wall_now, child_expiry.as_ref())?;
                let lifecycle_record = self
                    .lifecycle
                    .record(&self.profile_id)
                    .map_err(|_| BrowserExecutionManagerError::ManagedProfileUnavailable)?
                    .ok_or(BrowserExecutionManagerError::ManagedProfileUnavailable)?;
                if lifecycle_record.next() != BrowserProfileLifecycleState::Available {
                    return Err(BrowserExecutionManagerError::ManagedProfileUnavailable);
                }
                let generation = self
                    .generations
                    .next_generation_after(&self.profile_id, lifecycle_record.latest_generation())
                    .map_err(|_| BrowserExecutionManagerError::ManagedProfileUnavailable)?;
                self.commit_lifecycle_event(BrowserProfileLifecycleEvent::LeaseAcquired {
                    generation,
                })?;
                let registry_lease = match self.registry.acquire_profile(self.profile_id.as_str()) {
                    Ok(lease) if lease.id() == self.profile_id.as_str() => lease,
                    Ok(_) | Err(_) => {
                        self.release_unlaunched_lifecycle_lease(generation)?;
                        return Err(BrowserExecutionManagerError::ManagedProfileUnavailable);
                    }
                };
                let now = Instant::now();
                let Ok(fence) = BrowserProfileLeaseFence::start(
                    self.profile_id.clone(),
                    yosoi::BrowserProfileLeaseId::random(),
                    self.owner_id,
                    generation,
                    Arc::clone(&self.generations),
                    lease_duration,
                    now,
                    wall_now,
                ) else {
                    drop(registry_lease);
                    self.release_unlaunched_lifecycle_lease(generation)?;
                    return Err(BrowserExecutionManagerError::ManagedProfileUnavailable);
                };
                let user_data_dir = registry_lease.path().to_path_buf();
                let deadline = fence.deadline();
                *state = ManagedProfileState::Held {
                    registry_lease,
                    fence,
                    process_generation: None,
                    lifecycle_leased: true,
                    ownership_uncertain: false,
                };
                (user_data_dir, generation, deadline, true)
            }
            ManagedProfileState::Staged { .. } => {
                return Err(BrowserExecutionManagerError::InternalInvariant);
            }
            ManagedProfileState::Terminal { .. } => {
                return Err(BrowserExecutionManagerError::ManagerClosing);
            }
        };
        drop(state);

        if newly_acquired {
            let profile = Arc::clone(self);
            let manager = Arc::downgrade(manager);
            tokio::spawn(async move {
                sleep_until(TokioInstant::from_std(deadline)).await;
                if !profile.is_expired_generation(generation, Instant::now()) {
                    return;
                }
                let Some(manager) = manager.upgrade() else {
                    return;
                };
                if shutdown_inner(manager).await.is_err() {
                    // See the staged-path expiry worker above: fail closed in
                    // memory even if the durable quarantine write also fails.
                    let _ = profile.mark_ownership_uncertain();
                }
            });
        }

        Ok(ManagedProfileLaunch {
            user_data_dir,
            generation,
            deadline,
        })
    }
}
