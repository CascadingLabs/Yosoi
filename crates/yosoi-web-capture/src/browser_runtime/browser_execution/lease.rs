use super::{
    Arc, BrowserExecutionManagerError, CancellationToken, CloseAction, Handle, HashMap, Instant,
    JoinHandle, ManagerInner, Mutex, Notify, ProcessStatus, ReleaseExecutor,
    RuntimeBrowserTabLease, Weak, cleanup_deadline, create_additional_tab, fmt, oneshot,
    poison_slot, provider, release_wait_deadline, restart_release_on_current, start_release,
    wait_for_release_before, yosoi,
};

pub struct RuntimeBrowserLease {
    pub(super) resource: Arc<LeaseResource>,
    pub(super) initial_tab: RuntimeBrowserTabLease,
}

impl fmt::Debug for RuntimeBrowserLease {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RuntimeBrowserLease")
            .field("admission", &self.resource.admission)
            .finish_non_exhaustive()
    }
}

pub(super) struct LeaseResource {
    pub(super) manager: Weak<ManagerInner>,
    pub(super) admission: yosoi::BrowserExecutionAdmissionReceipt,
    pub(super) slot_id: yosoi::BrowserProcessSlotId,
    pub(super) generation: u64,
    pub(super) profile_generation: Option<yosoi::BrowserProfileLeaseGeneration>,
    pub(super) state: Mutex<LeaseState>,
    pub(super) released: Notify,
}

impl LeaseResource {
    pub(super) fn authorize_profile_admission(&self) -> Result<(), BrowserExecutionManagerError> {
        let Some(generation) = self.profile_generation else {
            return Ok(());
        };
        let manager = self
            .manager
            .upgrade()
            .ok_or(BrowserExecutionManagerError::ManagerClosing)?;
        let profile = manager
            .managed_profile
            .as_ref()
            .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
        profile.authorize_admission(generation)
    }

    pub(super) fn authorize_profile_cleanup(&self) -> Result<(), BrowserExecutionManagerError> {
        let Some(generation) = self.profile_generation else {
            return Ok(());
        };
        let manager = self
            .manager
            .upgrade()
            .ok_or(BrowserExecutionManagerError::ManagerClosing)?;
        let profile = manager
            .managed_profile
            .as_ref()
            .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
        profile.authorize_cleanup(generation)
    }
}

pub(super) struct LeaseState {
    pub(super) context: Option<Arc<ExecutionPageContext>>,
    pub(super) tabs: HashMap<yosoi::BrowserTabLeaseId, TabEntry>,
    pub(super) tab_creations: HashMap<yosoi::BrowserTabLeaseId, PendingTabCreation>,
    pub(super) active_tabs: u32,
    pub(super) releasing: bool,
    pub(super) release_worker: Option<JoinHandle<()>>,
    pub(super) release_progress: Option<ReleaseProgress>,
    pub(super) release_result: Option<Result<ReleaseCompletion, BrowserExecutionManagerError>>,
}

pub(super) enum ExecutionPageContext {
    Isolated(provider::IsolatedBrowserContext),
    ManagedProfile(provider::ManagedProfileContext),
}

impl ExecutionPageContext {
    pub(super) async fn new_blank_page(&self) -> Result<provider::Page, provider::VoidCrawlError> {
        match self {
            Self::Isolated(context) => context.new_blank_page().await,
            Self::ManagedProfile(context) => context.new_page().await,
        }
    }
}

pub(super) struct PendingTabCreation {
    pub(super) worker: Option<JoinHandle<()>>,
}

#[derive(Clone)]
pub(super) struct ReleaseProgress {
    pub(super) context_disposition: yosoi::BrowserContextCleanupDisposition,
    pub(super) process_action: Option<CloseAction>,
    pub(super) retained_process_disposition: yosoi::BrowserProcessCleanupDisposition,
    pub(super) completed_contexts_in_generation: u32,
}

#[derive(Clone)]
pub(super) struct ReleaseCompletion {
    pub(super) cleanup: yosoi::BrowserExecutionCleanupReceipt,
    pub(super) completed_contexts_in_generation: u32,
}

pub(super) struct TabEntry {
    pub(super) page: Option<Arc<provider::Page>>,
    pub(super) open: bool,
    pub(super) closing: bool,
    pub(super) navigation_gate: Arc<Mutex<()>>,
    pub(super) navigation_closing: CancellationToken,
}

/// Opaque, lease-scoped identity for one concrete Chromium tab.
impl RuntimeBrowserLease {
    pub fn scope(&self) -> yosoi::BrowserExecutionScope {
        self.resource.admission.scope()
    }

    pub fn admission(&self) -> &yosoi::BrowserExecutionAdmissionReceipt {
        &self.resource.admission
    }

    pub const fn initial_tab(&self) -> &RuntimeBrowserTabLease {
        &self.initial_tab
    }

    /// Returns the manager-owned process generation without exposing a provider handle.
    pub fn process_generation(&self) -> u64 {
        self.resource.generation
    }

    /// Adds one tab to a session-group context without exposing its provider handle.
    pub async fn new_tab(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<RuntimeBrowserTabLease, BrowserExecutionManagerError> {
        self.resource.authorize_profile_admission()?;
        if self.scope() != yosoi::BrowserExecutionScope::SessionGroup {
            return Err(BrowserExecutionManagerError::IndependentLeaseHasNoAdditionalTabs);
        }
        let manager = self
            .resource
            .manager
            .upgrade()
            .ok_or(BrowserExecutionManagerError::ManagerClosing)?;
        let id = yosoi::BrowserTabLeaseId::random();
        let context = {
            let mut lease_state = self.resource.state.lock().await;
            if lease_state.releasing || lease_state.release_result.is_some() {
                return Err(BrowserExecutionManagerError::TabReleased);
            }
            if lease_state.active_tabs >= manager.limits.tabs_per_session().get() {
                return Err(BrowserExecutionManagerError::SessionTabCapacity);
            }
            let context = lease_state
                .context
                .clone()
                .ok_or(BrowserExecutionManagerError::TabReleased)?;
            let mut state = manager.state.lock().await;
            if state.closing {
                return Err(BrowserExecutionManagerError::ManagerClosing);
            }
            if state.active_tabs >= manager.limits.tabs_total().get() {
                return Err(BrowserExecutionManagerError::GlobalTabCapacity);
            }
            state.active_tabs = state
                .active_tabs
                .checked_add(1)
                .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
            drop(state);
            lease_state.active_tabs = lease_state
                .active_tabs
                .checked_add(1)
                .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
            lease_state
                .tab_creations
                .insert(id, PendingTabCreation { worker: None });
            context
        };
        manager.changed.notify_waiters();

        let (result_sender, result_receiver) = oneshot::channel();
        let (ack_sender, ack_receiver) = oneshot::channel();
        let resource = Arc::clone(&self.resource);
        let worker_manager = Arc::clone(&manager);
        let worker_cancellation = cancellation.clone();
        let worker = async move {
            create_additional_tab(
                resource,
                worker_manager,
                context,
                id,
                worker_cancellation,
                result_sender,
                ack_receiver,
            )
            .await;
        };
        let executor = manager
            .provider_executor
            .clone()
            .unwrap_or_else(Handle::current);
        let worker = executor.spawn(worker);
        let mut lease_state = self.resource.state.lock().await;
        if let Some(creation) = lease_state.tab_creations.get_mut(&id) {
            creation.worker = Some(worker);
        }
        drop(lease_state);

        let result = result_receiver
            .await
            .map_err(|_| BrowserExecutionManagerError::ManagerClosing)??;
        ack_sender
            .send(())
            .map_err(|()| BrowserExecutionManagerError::TabReleased)?;
        Ok(RuntimeBrowserTabLease {
            id: result,
            resource: Arc::downgrade(&self.resource),
        })
    }

    /// Marks this process generation unavailable so it drains and is replaced on demand.
    pub async fn poison_process(&self) -> Result<(), BrowserExecutionManagerError> {
        let manager = self
            .resource
            .manager
            .upgrade()
            .ok_or(BrowserExecutionManagerError::ManagerClosing)?;
        poison_slot(&manager, self.resource.slot_id, self.resource.generation).await
    }

    /// Captures the admitted lease's validated, provider-neutral accounting state.
    pub async fn accounting_receipt(
        &self,
    ) -> Result<yosoi::BrowserExecutionAccountingReceipt, BrowserExecutionManagerError> {
        let manager = self
            .resource
            .manager
            .upgrade()
            .ok_or(BrowserExecutionManagerError::ManagerClosing)?;
        let lease_state = self.resource.state.lock().await;
        if lease_state.releasing || lease_state.release_result.is_some() {
            return Err(BrowserExecutionManagerError::TabReleased);
        }
        let active_tabs_in_session = lease_state.active_tabs;
        drop(lease_state);
        let state = manager.state.lock().await;
        let active_processes = state.slots.iter().try_fold(0_u32, |count, slot| {
            if slot.status == ProcessStatus::Vacant {
                Ok(count)
            } else {
                count
                    .checked_add(1)
                    .ok_or(BrowserExecutionManagerError::InternalInvariant)
            }
        })?;
        let slot = state
            .slots
            .iter()
            .find(|slot| {
                slot.id == self.resource.slot_id && slot.generation == self.resource.generation
            })
            .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
        let queued = u32::try_from(state.queue.len())
            .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
        let active_contexts = state.active_contexts;
        let active_tabs = state.active_tabs;
        let slot_active_contexts = slot.active_contexts;
        let completed_contexts = slot.completed_contexts;
        drop(state);
        yosoi::BrowserExecutionAccountingReceipt::new(
            self.resource.admission.clone(),
            manager.limits,
            active_processes,
            active_contexts,
            slot_active_contexts,
            active_tabs,
            active_tabs_in_session,
            queued,
            completed_contexts,
        )
        .map_err(|_| BrowserExecutionManagerError::InternalInvariant)
    }

    /// Captures manager accounting after this lease's bounded release has terminated.
    pub(crate) async fn terminal_accounting_receipt(
        &self,
    ) -> Result<yosoi::BrowserExecutionAccountingReceipt, BrowserExecutionManagerError> {
        let manager = self
            .resource
            .manager
            .upgrade()
            .ok_or(BrowserExecutionManagerError::ManagerClosing)?;
        let lease_state = self.resource.state.lock().await;
        let completion = lease_state
            .release_result
            .as_ref()
            .ok_or(BrowserExecutionManagerError::InternalInvariant)?
            .as_ref()
            .map_err(Clone::clone)?;
        let completed_contexts_in_generation = completion.completed_contexts_in_generation;
        let active_tabs_in_session = lease_state.active_tabs;
        drop(lease_state);
        let state = manager.state.lock().await;
        let active_processes = state.slots.iter().try_fold(0_u32, |count, slot| {
            if slot.status == ProcessStatus::Vacant {
                Ok(count)
            } else {
                count
                    .checked_add(1)
                    .ok_or(BrowserExecutionManagerError::InternalInvariant)
            }
        })?;
        let slot = state.slots.iter().find(|slot| {
            slot.id == self.resource.slot_id && slot.generation == self.resource.generation
        });
        let queued = u32::try_from(state.queue.len())
            .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
        let active_contexts = state.active_contexts;
        let active_tabs = state.active_tabs;
        let slot_active_contexts = slot.map_or(0, |slot| slot.active_contexts);
        let completed_contexts = slot
            .filter(|slot| slot.status != ProcessStatus::Vacant)
            .map_or(completed_contexts_in_generation, |slot| {
                slot.completed_contexts
            });
        drop(state);
        yosoi::BrowserExecutionAccountingReceipt::terminal(
            self.resource.admission.clone(),
            manager.limits,
            active_processes,
            active_contexts,
            slot_active_contexts,
            active_tabs,
            active_tabs_in_session,
            queued,
            completed_contexts,
        )
        .map_err(|_| BrowserExecutionManagerError::InternalInvariant)
    }

    /// Explicitly and idempotently disposes the entire context and returns capacity.
    pub async fn release(
        &self,
    ) -> Result<yosoi::BrowserExecutionCleanupReceipt, BrowserExecutionManagerError> {
        let manager = self
            .resource
            .manager
            .upgrade()
            .ok_or(BrowserExecutionManagerError::ManagerClosing)?;
        let context_deadline = cleanup_deadline(manager.limits);
        start_release(
            Arc::clone(&self.resource),
            context_deadline,
            ReleaseExecutor::Stable,
        )
        .await;
        if let Ok(cleanup) =
            wait_for_release_before(&self.resource, release_wait_deadline(manager.limits)).await
        {
            Ok(cleanup)
        } else {
            let retry_deadline = cleanup_deadline(manager.limits);
            restart_release_on_current(Arc::clone(&self.resource), retry_deadline).await;
            wait_for_release_before(&self.resource, release_wait_deadline(manager.limits)).await
        }
    }
}

impl Drop for RuntimeBrowserLease {
    fn drop(&mut self) {
        let resource = Arc::clone(&self.resource);
        let manager = resource.manager.upgrade();
        let handle = manager
            .as_ref()
            .and_then(|manager| manager.provider_executor.clone())
            .or_else(|| Handle::try_current().ok());
        let Some(handle) = handle else {
            return;
        };
        let deadline =
            manager.map_or_else(Instant::now, |manager| cleanup_deadline(manager.limits));
        handle.spawn(async move {
            start_release(resource, deadline, ReleaseExecutor::Stable).await;
        });
    }
}
