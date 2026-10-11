use super::{
    Arc, BrowserExecutionManagerError, CancellationToken, ExecutionPageContext, LeaseResource,
    ManagerInner, Mutex, TabEntry, Weak, cleanup_deadline, fmt, oneshot, poison_slot, provider,
    timeout_at, yosoi,
};

mod create;
pub(super) use create::create_additional_tab;

pub(super) struct NavigationTabParts {
    pub(super) page: Arc<provider::Page>,
    pub(super) gate: Arc<Mutex<()>>,
    pub(super) closing: CancellationToken,
    pub(super) lease: yosoi::BrowserTabLease,
}

/// Provider-neutral snapshot of CDP-domain escalation on one leased tab.
#[allow(
    clippy::struct_excessive_bools,
    reason = "each flag independently records one provider instrumentation capability"
)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserTabInstrumentationState {
    pub low_cdp: bool,
    pub network_enabled: bool,
    pub runtime_enabled: bool,
    pub utility_world_enabled: bool,
}

#[derive(Clone)]
pub struct RuntimeBrowserTabLease {
    pub(super) id: yosoi::BrowserTabLeaseId,
    pub(super) resource: Weak<LeaseResource>,
}

impl fmt::Debug for RuntimeBrowserTabLease {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RuntimeBrowserTabLease")
            .field("id", &self.id)
            .finish_non_exhaustive()
    }
}

impl RuntimeBrowserTabLease {
    pub const fn id(&self) -> yosoi::BrowserTabLeaseId {
        self.id
    }

    pub(super) fn authorize_profile_admission(&self) -> Result<(), BrowserExecutionManagerError> {
        let resource = self
            .resource
            .upgrade()
            .ok_or(BrowserExecutionManagerError::TabReleased)?;
        resource.authorize_profile_admission()
    }

    pub async fn close(&self) -> Result<(), BrowserExecutionManagerError> {
        let resource = self
            .resource
            .upgrade()
            .ok_or(BrowserExecutionManagerError::TabReleased)?;
        let manager = resource
            .manager
            .upgrade()
            .ok_or(BrowserExecutionManagerError::ManagerClosing)?;
        let (page, navigation_gate) = {
            let mut lease_state = resource.state.lock().await;
            if lease_state.releasing || lease_state.release_result.is_some() {
                return Err(BrowserExecutionManagerError::TabReleased);
            }
            let entry = lease_state
                .tabs
                .get_mut(&self.id)
                .ok_or(BrowserExecutionManagerError::TabReleased)?;
            if !entry.open {
                return Ok(());
            }
            if entry.closing {
                return Err(BrowserExecutionManagerError::TabCloseFailed);
            }
            entry.closing = true;
            entry.navigation_closing.cancel();
            let page = entry
                .page
                .as_ref()
                .map(Arc::clone)
                .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
            let navigation_gate = Arc::clone(&entry.navigation_gate);
            drop(lease_state);
            (page, navigation_gate)
        };
        let deadline = cleanup_deadline(manager.limits);
        let close_succeeded = match timeout_at(deadline, navigation_gate.lock_owned()).await {
            Ok(_navigation_guard) => {
                matches!(timeout_at(deadline, page.close()).await, Ok(Ok(())))
            }
            Err(_) => false,
        };
        let should_return_capacity = {
            let mut lease_state = resource.state.lock().await;
            if lease_state.releasing || lease_state.release_result.is_some() {
                false
            } else {
                let entry = lease_state
                    .tabs
                    .get_mut(&self.id)
                    .ok_or(BrowserExecutionManagerError::TabReleased)?;
                entry.closing = false;
                if close_succeeded && entry.open {
                    entry.open = false;
                    entry.page = None;
                    lease_state.active_tabs = lease_state
                        .active_tabs
                        .checked_sub(1)
                        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
                    true
                } else {
                    false
                }
            }
        };
        if should_return_capacity {
            decrement_global_tabs(&manager, 1).await?;
            return Ok(());
        }
        if close_succeeded {
            return Err(BrowserExecutionManagerError::TabReleased);
        }
        poison_slot(&manager, resource.slot_id, resource.generation).await?;
        Err(BrowserExecutionManagerError::TabCloseFailed)
    }

    pub(in crate::internal::web_capture) async fn page(
        &self,
    ) -> Result<Arc<provider::Page>, BrowserExecutionManagerError> {
        let resource = self
            .resource
            .upgrade()
            .ok_or(BrowserExecutionManagerError::TabReleased)?;
        resource.authorize_profile_admission()?;
        let state = resource.state.lock().await;
        if state.releasing || state.release_result.is_some() {
            return Err(BrowserExecutionManagerError::TabReleased);
        }
        let entry = state
            .tabs
            .get(&self.id)
            .ok_or(BrowserExecutionManagerError::TabReleased)?;
        if !entry.open || entry.closing {
            return Err(BrowserExecutionManagerError::TabReleased);
        }
        let page = entry
            .page
            .as_ref()
            .map(Arc::clone)
            .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
        drop(state);
        Ok(page)
    }

    /// Returns stable routing facts without exposing the provider page.
    pub async fn instrumentation_state(
        &self,
    ) -> Result<BrowserTabInstrumentationState, BrowserExecutionManagerError> {
        let state = self.page().await?.instrumentation_state();
        Ok(BrowserTabInstrumentationState {
            low_cdp: state.low_cdp,
            network_enabled: state.network_enabled,
            runtime_enabled: state.runtime_enabled,
            utility_world_enabled: state.utility_world_enabled,
        })
    }

    pub(super) async fn navigation_parts(
        &self,
    ) -> Result<NavigationTabParts, BrowserExecutionManagerError> {
        let resource = self
            .resource
            .upgrade()
            .ok_or(BrowserExecutionManagerError::TabReleased)?;
        resource.authorize_profile_admission()?;
        let state = resource.state.lock().await;
        if state.releasing || state.release_result.is_some() {
            return Err(BrowserExecutionManagerError::TabReleased);
        }
        let entry = state
            .tabs
            .get(&self.id)
            .ok_or(BrowserExecutionManagerError::TabReleased)?;
        if !entry.open || entry.closing {
            return Err(BrowserExecutionManagerError::TabReleased);
        }
        let page = entry
            .page
            .as_ref()
            .map(Arc::clone)
            .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
        let parts = NavigationTabParts {
            page,
            gate: Arc::clone(&entry.navigation_gate),
            closing: entry.navigation_closing.clone(),
            lease: yosoi::BrowserTabLease::new(resource.admission.session().clone(), self.id),
        };
        drop(state);
        Ok(parts)
    }
}

pub(super) async fn finish_tab_creation_failure(
    resource: &Arc<LeaseResource>,
    manager: &Arc<ManagerInner>,
    id: yosoi::BrowserTabLeaseId,
) -> Result<(), BrowserExecutionManagerError> {
    let mut lease_state = resource.state.lock().await;
    if !lease_state.tab_creations.contains_key(&id) {
        return Ok(());
    }
    lease_state.active_tabs = lease_state
        .active_tabs
        .checked_sub(1)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    let mut manager_state = manager.state.lock().await;
    manager_state.active_tabs = manager_state
        .active_tabs
        .checked_sub(1)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    let _ = lease_state.tab_creations.remove(&id);
    drop(manager_state);
    drop(lease_state);
    resource.released.notify_waiters();
    manager.changed.notify_waiters();
    Ok(())
}

pub(super) async fn finish_tab_creation_success(
    resource: &Arc<LeaseResource>,
    manager: &Arc<ManagerInner>,
    id: yosoi::BrowserTabLeaseId,
) {
    let _ = resource.state.lock().await.tab_creations.remove(&id);
    resource.released.notify_waiters();
    manager.changed.notify_waiters();
}

pub(super) async fn decrement_global_tabs(
    manager: &Arc<ManagerInner>,
    count: u32,
) -> Result<(), BrowserExecutionManagerError> {
    let mut state = manager.state.lock().await;
    state.active_tabs = state
        .active_tabs
        .checked_sub(count)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    drop(state);
    manager.changed.notify_waiters();
    Ok(())
}
