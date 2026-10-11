use super::{
    Arc, BrowserExecutionManager, BrowserExecutionManagerError, CloseAction, Instant, ManagerInner,
    ProcessCloseOutcome, ProcessStatus, Reservation, cleanup_deadline, find_slot_mut, provider,
    rollback_reserved_capacity, yosoi,
};

impl BrowserExecutionManager {
    pub(super) async fn launch_reserved_process(
        &self,
        reservation: &Reservation,
    ) -> Result<Arc<provider::BrowserSession>, BrowserExecutionManagerError> {
        let managed_profile_launch = self
            .inner
            .managed_profile
            .as_ref()
            .map(|profile| profile.acquire_before_launch(&self.inner))
            .transpose()?;
        let managed_profile_generation = managed_profile_launch
            .as_ref()
            .map(|profile| profile.generation);
        let mut builder =
            provider::BrowserSession::builder().cdp_mode(if self.inner.config.minimal_cdp {
                provider::CdpMode::Minimal
            } else {
                provider::CdpMode::Normal
            });
        builder = if self.inner.config.headful {
            builder.headful()
        } else {
            builder.headless()
        };
        if let Some(profile) = managed_profile_launch {
            builder = builder.user_data_dir(profile.user_data_dir);
        }
        let executor = self.inner.provider_executor.clone();
        let manager = Arc::clone(&self.inner);
        let managed_profile = self.inner.managed_profile.clone();
        let reservation = reservation.clone();
        let launch = async move {
            let Ok(launched) = builder.launch().await else {
                if let Some(profile) = &managed_profile
                    && profile.mark_ownership_uncertain().is_err()
                {
                    return Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain);
                }
                return Err(BrowserExecutionManagerError::ProviderUnavailable);
            };
            let session = Arc::new(launched);
            #[cfg(test)]
            let creation_pause = {
                let mut state = manager.state.lock().await;
                let slot = find_slot_mut(
                    &mut state.slots,
                    reservation.slot_id,
                    reservation.generation,
                )
                .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
                if slot.status != ProcessStatus::Launching {
                    return Err(BrowserExecutionManagerError::InternalInvariant);
                }
                slot.status = ProcessStatus::Ready;
                slot.session = Some(Arc::clone(&session));
                state.creation_pause.clone()
            };
            #[cfg(not(test))]
            {
                let mut state = manager.state.lock().await;
                let slot = find_slot_mut(
                    &mut state.slots,
                    reservation.slot_id,
                    reservation.generation,
                )
                .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
                if slot.status != ProcessStatus::Launching {
                    return Err(BrowserExecutionManagerError::InternalInvariant);
                }
                slot.status = ProcessStatus::Ready;
                slot.session = Some(Arc::clone(&session));
                drop(state);
            }
            manager.changed.notify_waiters();
            if let (Some(profile), Some(profile_generation)) =
                (&managed_profile, managed_profile_generation)
                && profile
                    .bind_process_generation(profile_generation, reservation.generation)
                    .is_err()
            {
                return Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain);
            }
            #[cfg(test)]
            if let Some((started, proceed)) = creation_pause {
                started.notify_one();
                proceed.notified().await;
            }
            Ok(session)
        };
        match executor {
            Some(executor) => executor
                .spawn(launch)
                .await
                .map_err(|_| BrowserExecutionManagerError::ProviderUnavailable)?,
            None => launch.await,
        }
    }
}

pub(super) async fn rollback_creation_state(
    manager: &Arc<ManagerInner>,
    reservation: &Reservation,
    poison: bool,
) -> Option<CloseAction> {
    let action = {
        let mut state = manager.state.lock().await;
        state.creations.remove(&reservation.creation_id)?;
        match rollback_reserved_capacity(&mut state, reservation, poison) {
            Ok(action) => action,
            Err(error) => {
                state.maintenance_errors.push_back(error);
                None
            }
        }
    };
    manager.changed.notify_waiters();
    action
}

pub(super) async fn rollback_creation_inner(
    manager: &Arc<ManagerInner>,
    reservation: &Reservation,
    poison: bool,
) {
    if let Some(action) = rollback_creation_state(manager, reservation, poison).await
        && let Err(error) =
            close_process_slot(manager, action, cleanup_deadline(manager.limits)).await
    {
        let mut state = manager.state.lock().await;
        state.maintenance_errors.push_back(error);
        drop(state);
        manager.changed.notify_waiters();
    }
}

pub(super) async fn rollback_abandoned_creation(
    manager: &Arc<ManagerInner>,
    reservation: &Reservation,
) {
    if let Some(action) = rollback_creation_state(manager, reservation, true).await {
        // This first bounded attempt starts provider-owned shutdown. The
        // teardown pass retries the retained session without publishing an
        // intermediate failure as queue maintenance.
        let _ = close_process_slot(manager, action, cleanup_deadline(manager.limits)).await;
    }
}

pub(super) async fn close_process_slot(
    manager: &Arc<ManagerInner>,
    action: CloseAction,
    deadline: Instant,
) -> Result<(), BrowserExecutionManagerError> {
    close_process_slot_outcome(manager, action, deadline)
        .await
        .error()
        .map_or(Ok(()), Err)
}

pub(super) async fn close_process_slot_outcome(
    manager: &Arc<ManagerInner>,
    action: CloseAction,
    deadline: Instant,
) -> ProcessCloseOutcome {
    #[cfg(test)]
    let injected_outcome = manager
        .state
        .lock()
        .await
        .process_close_outcomes
        .pop_front();
    let observed_outcome = match action.session.close_before(deadline).await {
        Ok(()) => ProcessCloseOutcome::Completed,
        Err(provider::VoidCrawlError::Timeout(_)) => ProcessCloseOutcome::DeadlineExceeded,
        Err(_) => ProcessCloseOutcome::Failed,
    };
    #[cfg(test)]
    let outcome = injected_outcome.unwrap_or(observed_outcome);
    #[cfg(not(test))]
    let outcome = observed_outcome;
    if let Some(profile) = &manager.managed_profile {
        let confirmation = if outcome == ProcessCloseOutcome::Completed {
            profile.confirm_process_closed(action.generation)
        } else {
            Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain)
        };
        if confirmation.is_err() {
            let _ownership_error = profile.mark_ownership_uncertain();
        }
    }
    let mut state = manager.state.lock().await;
    if let Some(slot) = find_slot_mut(&mut state.slots, action.slot_id, action.generation)
        && slot.status == ProcessStatus::Closing
        && outcome == ProcessCloseOutcome::Completed
    {
        slot.session = None;
        slot.status = ProcessStatus::Vacant;
        slot.completed_contexts = 0;
    }
    drop(state);
    manager.changed.notify_waiters();
    outcome
}

pub(super) async fn poison_slot(
    manager: &Arc<ManagerInner>,
    slot_id: yosoi::BrowserProcessSlotId,
    generation: u64,
) -> Result<(), BrowserExecutionManagerError> {
    let action = {
        let mut state = manager.state.lock().await;
        find_slot_mut(&mut state.slots, slot_id, generation).and_then(|slot| {
            slot.status = ProcessStatus::Draining;
            if slot.active_contexts == 0 {
                slot.status = ProcessStatus::Closing;
                slot.session.clone().map(|session| CloseAction {
                    slot_id,
                    generation,
                    session,
                })
            } else {
                None
            }
        })
    };
    manager.changed.notify_waiters();
    match action {
        Some(action) => close_process_slot(manager, action, cleanup_deadline(manager.limits)).await,
        None => Ok(()),
    }
}
