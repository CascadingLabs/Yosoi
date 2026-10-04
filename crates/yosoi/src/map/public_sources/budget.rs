//! Shared dispatch admission for concurrent public-source requests.
use std::{collections::BTreeMap, mem, sync::Arc};

use tokio::sync::{Mutex, Notify};
use tokio::time::{Instant, sleep_until};
use url::Url;

use super::super::{CancellationToken, LimitReached, PublicProvider, RequestTrace, SourceFailure};

pub(super) struct Budget {
    state: Mutex<State>,
    changed: Notify,
    max_requests: u32,
    max_bytes: u64,
    response_cap: u64,
    inventory_cap: u64,
}

#[derive(Default)]
struct State {
    reserved: u64,
    charged: u64,
    inventory: u64,
    active: u32,
    peak: u32,
    traces: Vec<RequestTrace>,
    unfinished: BTreeMap<usize, u64>,
    limit: Option<LimitReached>,
}

pub(super) struct Reservation {
    pub ordinal: usize,
    pub cap: u64,
}

pub(super) enum AdmissionError {
    Limit(LimitReached),
    Stopped,
    Source(SourceFailure),
}

pub(super) struct Consumption {
    pub traces: Vec<RequestTrace>,
    pub charged: u64,
    pub inventory: u64,
    pub peak: u32,
    pub limit: Option<LimitReached>,
}

impl Budget {
    pub fn new(
        max_requests: u32,
        max_bytes: u64,
        response_cap: u64,
        inventory_cap: u64,
    ) -> Arc<Self> {
        Arc::new(Self {
            state: Mutex::new(State::default()),
            changed: Notify::new(),
            max_requests,
            max_bytes,
            response_cap,
            inventory_cap,
        })
    }

    #[cfg(test)]
    pub async fn reserve(
        &self,
        url: &Url,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<Reservation, AdmissionError> {
        self.reserve_for(url, token, deadline, None).await
    }

    pub async fn reserve_for(
        &self,
        url: &Url,
        token: &CancellationToken,
        deadline: Instant,
        provider: Option<PublicProvider>,
    ) -> Result<Reservation, AdmissionError> {
        loop {
            let notified = self.changed.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            {
                let mut state = self.state.lock().await;
                if token.is_cancelled() || Instant::now() >= deadline {
                    return Err(AdmissionError::Stopped);
                }
                if let Some(limit) = state.limit {
                    return Err(AdmissionError::Limit(limit));
                }
                if state.traces.len() >= usize::try_from(self.max_requests).unwrap_or(usize::MAX) {
                    state.limit.get_or_insert(LimitReached::Requests);
                    self.changed.notify_waiters();
                    return Err(AdmissionError::Limit(LimitReached::Requests));
                }
                let available = self
                    .max_bytes
                    .saturating_sub(state.charged)
                    .saturating_sub(state.reserved);
                if available > 0 && (available >= self.response_cap || state.reserved == 0) {
                    let inventory =
                        u64::try_from(url.as_str().len().saturating_add(96)).unwrap_or(u64::MAX);
                    if inventory > self.inventory_cap.saturating_sub(state.inventory) {
                        state.limit.get_or_insert(LimitReached::InventoryBytes);
                        self.changed.notify_waiters();
                        return Err(AdmissionError::Limit(LimitReached::InventoryBytes));
                    }
                    if let Some(provider) = provider {
                        super::rate::admit(provider).map_err(AdmissionError::Source)?;
                    }
                    state.inventory = state.inventory.saturating_add(inventory);
                    let cap = available.min(self.response_cap);
                    let ordinal = state.traces.len();
                    state.traces.push(RequestTrace {
                        target: url.clone(),
                        status: None,
                        charged_response_bytes: 0,
                    });
                    state.unfinished.insert(ordinal, cap);
                    state.reserved = state.reserved.saturating_add(cap);
                    state.active = state.active.saturating_add(1);
                    state.peak = state.peak.max(state.active);
                    return Ok(Reservation { ordinal, cap });
                }
                if state.reserved == 0 {
                    state.limit.get_or_insert(LimitReached::TotalResponseBytes);
                    self.changed.notify_waiters();
                    return Err(AdmissionError::Limit(LimitReached::TotalResponseBytes));
                }
                drop(state);
            }
            tokio::select! {
                () = &mut notified => {},
                () = token.cancelled() => return Err(AdmissionError::Stopped),
                () = sleep_until(deadline) => return Err(AdmissionError::Stopped),
            }
        }
    }

    pub async fn complete(&self, reservation: Reservation, status: Option<u16>, bytes: u64) {
        let mut state = self.state.lock().await;
        let charged = bytes.min(reservation.cap);
        state.unfinished.remove(&reservation.ordinal);
        state.reserved = state.reserved.saturating_sub(reservation.cap);
        state.charged = state.charged.saturating_add(charged);
        state.active = state.active.saturating_sub(1);
        if let Some(trace) = state.traces.get_mut(reservation.ordinal) {
            trace.status = status;
            trace.charged_response_bytes = charged;
        }
        drop(state);
        self.changed.notify_waiters();
    }

    pub async fn consumption(&self) -> Consumption {
        let mut state = self.state.lock().await;
        // A failed join must conservatively charge its remaining admission extent.
        for (ordinal, cap) in mem::take(&mut state.unfinished) {
            state.charged = state.charged.saturating_add(cap);
            if let Some(trace) = state.traces.get_mut(ordinal) {
                trace.charged_response_bytes = cap;
            }
        }
        state.reserved = 0;
        state.active = 0;
        Consumption {
            traces: mem::take(&mut state.traces),
            charged: state.charged,
            inventory: state.inventory,
            peak: state.peak,
            limit: state.limit,
        }
    }
}
