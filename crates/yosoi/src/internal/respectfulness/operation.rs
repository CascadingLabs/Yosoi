use std::{
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{
    task::spawn_blocking,
    time::{Instant, timeout_at},
};

use crate::policy::respectfulness::Retry;

use super::{Event, EventKind, Permit, RespectfulnessError, Runtime, expiry, now_ms, setup};

/// One serial acquisition's live permit. Spec clones share ownership; separate
/// acquisitions get separate operations over the same Registry.
#[derive(Clone, Debug)]
pub struct Operation {
    runtime: Runtime,
    pending: Arc<Mutex<Option<Permit>>>,
    events: Arc<Mutex<Vec<Event>>>,
}

impl PartialEq for Operation {
    fn eq(&self, other: &Self) -> bool {
        self.runtime == other.runtime && Arc::ptr_eq(&self.pending, &other.pending)
    }
}
impl Eq for Operation {}

impl Operation {
    pub fn new(runtime: Runtime) -> Self {
        Self {
            runtime,
            pending: Arc::new(Mutex::new(None)),
            events: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn retry(&self) -> &Retry {
        &self.runtime.policy().retry
    }

    pub async fn acquire(
        &self,
        target: String,
        remaining: Duration,
    ) -> Result<(), RespectfulnessError> {
        let runtime = self.runtime.clone();
        let expires = expiry(now_ms()?, remaining)?;
        let permit = spawn_blocking(move || {
            let now = now_ms()?;
            runtime.reserve_at(&target, now, expires)
        })
        .await
        .map_err(|_| setup("registry admission task failed"))?;
        let permit = match permit {
            Ok(permit) => permit,
            Err(error) => {
                self.record(Event {
                    kind: EventKind::Rejected,
                    groups: Vec::new(),
                    registry_id: None,
                    status: None,
                    error: Some(error.clone()),
                })?;
                return Err(error);
            }
        };
        let event = Event {
            kind: EventKind::Admitted,
            groups: permit.groups.clone(),
            registry_id: permit.registry_id.clone(),
            status: None,
            error: None,
        };
        let mut pending = self
            .pending
            .lock()
            .map_err(|_| setup("permit state poisoned"))?;
        if pending.is_some() {
            return Err(setup("prior HTTP exchange has not released its permit"));
        }
        *pending = Some(permit);
        drop(pending);
        self.record(event)
    }

    pub async fn observe(
        &self,
        status: Option<u16>,
        retry_after: Option<String>,
        transport_error: bool,
    ) -> Result<(), RespectfulnessError> {
        let permit = self
            .pending
            .lock()
            .map_err(|_| setup("permit state poisoned"))?
            .clone();
        if let Some(permit) = permit {
            let event = Event {
                kind: EventKind::Response,
                groups: permit.groups.clone(),
                registry_id: permit.registry_id.clone(),
                status,
                error: None,
            };
            self.record(event)?;
            let updated = spawn_blocking(move || {
                permit.observe_at(now_ms()?, status, retry_after.as_deref(), transport_error)
            })
            .await
            .map_err(|_| setup("registry feedback task failed"))?;
            if let Err(error) = updated {
                self.record(Event {
                    kind: EventKind::Rejected,
                    groups: Vec::new(),
                    registry_id: None,
                    status,
                    error: Some(error.clone()),
                })?;
                return Err(error);
            }
        }
        Ok(())
    }

    pub async fn finish_before(&self, deadline: Instant) -> Result<(), RespectfulnessError> {
        if let Ok(result) = timeout_at(deadline, self.finish()).await {
            result
        } else {
            let error = setup(
                "registry release exceeded the acquisition deadline; its bounded lease remains recoverable",
            );
            self.record_error(error.clone())?;
            Err(error)
        }
    }

    pub fn record_error(&self, error: RespectfulnessError) -> Result<(), RespectfulnessError> {
        self.record(Event {
            kind: EventKind::Rejected,
            groups: Vec::new(),
            registry_id: None,
            status: None,
            error: Some(error),
        })
    }

    pub async fn finish(&self) -> Result<(), RespectfulnessError> {
        let permit = self
            .pending
            .lock()
            .map_err(|_| setup("permit state poisoned"))?
            .take();
        if let Some(permit) = permit {
            let event = Event {
                kind: EventKind::Released,
                groups: permit.groups.clone(),
                registry_id: permit.registry_id.clone(),
                status: None,
                error: None,
            };
            let result = spawn_blocking(move || permit.finish_at(now_ms()?, None, None, false))
                .await
                .map_err(|_| setup("registry release task failed"))?;
            match result {
                Ok(()) => self.record(event)?,
                Err(error) => {
                    self.record_error(error.clone())?;
                    return Err(error);
                }
            }
        }
        Ok(())
    }

    pub fn events(&self) -> Result<Vec<Event>, RespectfulnessError> {
        Ok(self
            .events
            .lock()
            .map_err(|_| setup("event state poisoned"))?
            .clone())
    }

    pub fn record_retry(&self, status: Option<u16>) -> Result<(), RespectfulnessError> {
        self.record(Event {
            kind: EventKind::Retry,
            groups: Vec::new(),
            registry_id: None,
            status,
            error: None,
        })
    }

    fn record(&self, event: Event) -> Result<(), RespectfulnessError> {
        let mut events = self
            .events
            .lock()
            .map_err(|_| setup("event state poisoned"))?;
        if events.len() >= 512 {
            return Err(setup("respectfulness event budget exhausted"));
        }
        events.push(event);
        drop(events);
        Ok(())
    }
}
