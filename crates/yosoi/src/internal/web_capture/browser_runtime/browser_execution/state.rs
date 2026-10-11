#[cfg(test)]
use super::Notify;
use super::{
    Arc, BrowserExecutionManagerError, Handle, HashMap, LeaseResource, ManagerInner, VecDeque,
    Weak, provider, yosoi,
};

pub(super) struct ManagerState {
    pub(super) slots: VecDeque<ProcessSlot>,
    pub(super) next_slot: usize,
    pub(super) active_contexts: u32,
    pub(super) active_tabs: u32,
    pub(super) queue: VecDeque<u64>,
    pub(super) resources: HashMap<yosoi::BrowserExecutionId, Arc<LeaseResource>>,
    pub(super) in_flight_creations: u32,
    pub(super) closing: bool,
    pub(super) shutdown_complete: bool,
    pub(super) maintenance_errors: VecDeque<BrowserExecutionManagerError>,
    pub(super) creations: HashMap<u64, Reservation>,
    #[cfg(test)]
    pub(super) process_close_outcomes: VecDeque<ProcessCloseOutcome>,
    #[cfg(test)]
    pub(super) context_cleanup_dispositions: VecDeque<yosoi::BrowserContextCleanupDisposition>,
    #[cfg(test)]
    pub(super) creation_pause: Option<(Arc<Notify>, Arc<Notify>)>,
    #[cfg(test)]
    pub(super) context_creation_pause: Option<(Arc<Notify>, Arc<Notify>)>,
    #[cfg(test)]
    pub(super) tab_reservation_pause: Option<(Arc<Notify>, Arc<Notify>)>,
    #[cfg(test)]
    pub(super) tab_creation_pause: Option<(Arc<Notify>, Arc<Notify>)>,
    #[cfg(test)]
    pub(super) release_pause: Option<(Arc<Notify>, Arc<Notify>)>,
    #[cfg(test)]
    pub(super) last_created_tab: Option<Arc<provider::Page>>,
}

pub(super) struct ProcessSlot {
    pub(super) id: yosoi::BrowserProcessSlotId,
    pub(super) generation: u64,
    pub(super) status: ProcessStatus,
    pub(super) session: Option<Arc<provider::BrowserSession>>,
    pub(super) active_contexts: u32,
    pub(super) completed_contexts: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum ProcessStatus {
    Vacant,
    Launching,
    Ready,
    Draining,
    Closing,
}

#[derive(Clone)]
pub(super) struct Reservation {
    pub(super) creation_id: u64,
    pub(super) slot_id: yosoi::BrowserProcessSlotId,
    pub(super) generation: u64,
    pub(super) session: Option<Arc<provider::BrowserSession>>,
}

pub(super) struct QueuedRequestGuard {
    pub(super) manager: Weak<ManagerInner>,
    pub(super) ticket: u64,
    pub(super) armed: bool,
}

#[derive(Clone)]
pub(super) struct CloseAction {
    pub(super) slot_id: yosoi::BrowserProcessSlotId,
    pub(super) generation: u64,
    pub(super) session: Arc<provider::BrowserSession>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum ProcessCloseOutcome {
    Completed,
    DeadlineExceeded,
    Failed,
}

impl ProcessCloseOutcome {
    pub(super) const fn error(self) -> Option<BrowserExecutionManagerError> {
        match self {
            Self::Completed => None,
            Self::DeadlineExceeded => Some(BrowserExecutionManagerError::ProcessCloseDeadline),
            Self::Failed => Some(BrowserExecutionManagerError::ProcessCloseFailed),
        }
    }

    pub(super) const fn disposition(self) -> yosoi::BrowserProcessCleanupDisposition {
        match self {
            Self::Completed => yosoi::BrowserProcessCleanupDisposition::Completed,
            Self::DeadlineExceeded => yosoi::BrowserProcessCleanupDisposition::DeadlineExceeded,
            Self::Failed => yosoi::BrowserProcessCleanupDisposition::Failed,
        }
    }
}

pub(super) enum ReserveDecision {
    Reserved(Reservation),
    Close(CloseAction),
    MaintenanceFailed(BrowserExecutionManagerError),
    Wait,
}

impl QueuedRequestGuard {
    pub(super) const fn arm(&mut self) {
        self.armed = true;
    }

    pub(super) const fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for QueuedRequestGuard {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        let Some(manager) = self.manager.upgrade() else {
            return;
        };
        let ticket = self.ticket;
        let handle = manager
            .provider_executor
            .clone()
            .or_else(|| Handle::try_current().ok());
        let Some(handle) = handle else {
            return;
        };
        handle.spawn(async move {
            let mut state = manager.state.lock().await;
            remove_ticket(&mut state.queue, ticket);
            drop(state);
            manager.changed.notify_waiters();
        });
    }
}

pub(super) fn enqueue_request(
    queue: &mut VecDeque<u64>,
    ticket: u64,
    maximum_depth: u32,
) -> Result<(), BrowserExecutionManagerError> {
    let depth =
        u32::try_from(queue.len()).map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
    if depth >= maximum_depth {
        return Err(BrowserExecutionManagerError::QueueFull);
    }
    queue.push_back(ticket);
    Ok(())
}

pub(super) fn remove_ticket(queue: &mut VecDeque<u64>, ticket: u64) {
    if let Some(position) = queue.iter().position(|queued| *queued == ticket) {
        let _ = queue.remove(position);
    }
}

pub(super) fn reserve_capacity(
    state: &mut ManagerState,
    limits: yosoi::BrowserExecutionLimits,
    creation_id: u64,
) -> Result<ReserveDecision, BrowserExecutionManagerError> {
    if state.active_contexts >= limits.contexts_total().get()
        || state.active_tabs >= limits.tabs_total().get()
    {
        return Ok(ReserveDecision::Wait);
    }
    let len = state.slots.len();
    let mut ready_index = None;
    let mut close_index = None;
    for offset in 0..len {
        let Some(raw_index) = state.next_slot.checked_add(offset) else {
            return Err(BrowserExecutionManagerError::InternalInvariant);
        };
        let index = raw_index
            .checked_rem(len)
            .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
        let Some(slot) = state.slots.get_mut(index) else {
            return Err(BrowserExecutionManagerError::InternalInvariant);
        };
        if slot.status == ProcessStatus::Ready {
            if slot
                .session
                .as_ref()
                .is_some_and(|session| session.is_alive())
                && slot.active_contexts < limits.contexts_per_process().get()
            {
                ready_index = Some(index);
                break;
            }
            if slot
                .session
                .as_ref()
                .is_some_and(|session| !session.is_alive())
            {
                slot.status = ProcessStatus::Draining;
            }
        }
        if matches!(
            slot.status,
            ProcessStatus::Draining | ProcessStatus::Closing
        ) && slot.active_contexts == 0
            && slot.session.is_some()
        {
            close_index = Some(index);
        }
    }
    if let Some(index) = ready_index {
        return reserve_slot(state, limits, creation_id, index, false);
    }
    if let Some(index) = state
        .slots
        .iter()
        .position(|slot| slot.status == ProcessStatus::Vacant)
    {
        return reserve_slot(state, limits, creation_id, index, true);
    }
    if let Some(index) = close_index {
        let Some(slot) = state.slots.get_mut(index) else {
            return Err(BrowserExecutionManagerError::InternalInvariant);
        };
        let Some(session) = slot.session.clone() else {
            return Err(BrowserExecutionManagerError::InternalInvariant);
        };
        slot.status = ProcessStatus::Closing;
        return Ok(ReserveDecision::Close(CloseAction {
            slot_id: slot.id,
            generation: slot.generation,
            session,
        }));
    }
    Ok(ReserveDecision::Wait)
}

pub(super) fn reserve_slot(
    state: &mut ManagerState,
    limits: yosoi::BrowserExecutionLimits,
    creation_id: u64,
    index: usize,
    launch: bool,
) -> Result<ReserveDecision, BrowserExecutionManagerError> {
    let len = state.slots.len();
    let Some(slot) = state.slots.get_mut(index) else {
        return Err(BrowserExecutionManagerError::InternalInvariant);
    };
    if launch {
        slot.generation = slot
            .generation
            .checked_add(1)
            .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
        slot.status = ProcessStatus::Launching;
        slot.completed_contexts = 0;
    }
    slot.active_contexts = slot
        .active_contexts
        .checked_add(1)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    state.active_contexts = state
        .active_contexts
        .checked_add(1)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    state.active_tabs = state
        .active_tabs
        .checked_add(1)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    state.in_flight_creations = state
        .in_flight_creations
        .checked_add(1)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    state.next_slot = index
        .checked_add(1)
        .and_then(|next| next.checked_rem(len))
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    let reservation = Reservation {
        creation_id,
        slot_id: slot.id,
        generation: slot.generation,
        session: slot.session.clone(),
    };
    if state.active_contexts > limits.contexts_total().get()
        || state.active_tabs > limits.tabs_total().get()
        || state
            .creations
            .insert(creation_id, reservation.clone())
            .is_some()
    {
        return Err(BrowserExecutionManagerError::InternalInvariant);
    }
    Ok(ReserveDecision::Reserved(reservation))
}

pub(super) fn rollback_reserved_capacity(
    state: &mut ManagerState,
    reservation: &Reservation,
    poison: bool,
) -> Result<Option<CloseAction>, BrowserExecutionManagerError> {
    state.active_contexts = state
        .active_contexts
        .checked_sub(1)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    state.active_tabs = state
        .active_tabs
        .checked_sub(1)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    state.in_flight_creations = state
        .in_flight_creations
        .checked_sub(1)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    let slot = find_slot_mut(
        &mut state.slots,
        reservation.slot_id,
        reservation.generation,
    )
    .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    slot.active_contexts = slot
        .active_contexts
        .checked_sub(1)
        .ok_or(BrowserExecutionManagerError::InternalInvariant)?;
    if poison {
        slot.status = ProcessStatus::Draining;
    }
    if slot.status == ProcessStatus::Launching {
        slot.status = ProcessStatus::Vacant;
        slot.session = None;
    }
    if slot.status == ProcessStatus::Draining && slot.active_contexts == 0 {
        let session = slot.session.clone();
        slot.status = if session.is_some() {
            ProcessStatus::Closing
        } else {
            ProcessStatus::Vacant
        };
        return Ok(session.map(|session| CloseAction {
            slot_id: slot.id,
            generation: slot.generation,
            session,
        }));
    }
    Ok(None)
}

pub(super) fn find_slot_mut(
    slots: &mut VecDeque<ProcessSlot>,
    id: yosoi::BrowserProcessSlotId,
    generation: u64,
) -> Option<&mut ProcessSlot> {
    slots
        .iter_mut()
        .find(|slot| slot.id == id && slot.generation == generation)
}
