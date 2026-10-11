//! Provider-neutral bounded accounting for one acquisition attempt.

use crate::internal::web_capture as yosoi_web_capture;

mod completion;
pub use completion::AcquisitionObservationError;

use crate::internal::types::CaptureId;
use chrono::{DateTime, Utc};
use thiserror::Error;

use crate::internal::web_capture::{
    ByteCount, CaptureOffset, CaptureTermination, EventAdmission, LifecycleEvent, LifecycleStop,
    ObservationPolicy,
};

/// Checked failures from the provider-neutral bounded lifecycle.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BoundedAcquisitionError {
    #[error("event offset {offered} precedes previously observed offset {previous}")]
    NonMonotonic { offered: u64, previous: u64 },
    #[error("event accounting overflowed")]
    EventOverflow,
    #[error("byte accounting overflowed")]
    ByteOverflow,
    #[error("lifecycle is already stopped")]
    AlreadyStopped,
}

/// Retained accounting snapshot used when staged payload publication fails.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RetentionCheckpoint {
    events: u64,
    bytes: u64,
}

/// Concrete provider-neutral identity, policy, clock, termination, and accounting state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundedAcquisitionLifecycle {
    capture_id: CaptureId,
    observation: ObservationPolicy,
    started_at: DateTime<Utc>,
    observed_through: CaptureOffset,
    admitted_events: u64,
    retained_events: u64,
    admitted_bytes: u64,
    retained_bytes: u64,
    stop: Option<CaptureTermination>,
}

impl BoundedAcquisitionLifecycle {
    pub const fn start(
        capture_id: CaptureId,
        observation: ObservationPolicy,
        started_at: DateTime<Utc>,
    ) -> Self {
        Self {
            capture_id,
            observation,
            started_at,
            observed_through: CaptureOffset::from_microseconds(0),
            admitted_events: 0,
            retained_events: 0,
            admitted_bytes: 0,
            retained_bytes: 0,
            stop: None,
        }
    }

    pub const fn capture_id(&self) -> CaptureId {
        self.capture_id
    }
    pub const fn observation(&self) -> &ObservationPolicy {
        &self.observation
    }
    pub const fn started_at(&self) -> DateTime<Utc> {
        self.started_at
    }
    pub const fn termination(&self) -> Option<&CaptureTermination> {
        self.stop.as_ref()
    }
    pub const fn observed_through(&self) -> CaptureOffset {
        self.observed_through
    }
    pub const fn admitted_events(&self) -> u64 {
        self.admitted_events
    }
    pub const fn retained_events(&self) -> u64 {
        self.retained_events
    }
    pub const fn admitted_bytes(&self) -> u64 {
        self.admitted_bytes
    }
    pub const fn retained_bytes(&self) -> u64 {
        self.retained_bytes
    }
    pub const fn dropped_counts(&self) -> (u64, u64) {
        (
            self.admitted_events.saturating_sub(self.retained_events),
            self.admitted_bytes.saturating_sub(self.retained_bytes),
        )
    }
    pub const fn retention_checkpoint(&self) -> RetentionCheckpoint {
        RetentionCheckpoint {
            events: self.retained_events,
            bytes: self.retained_bytes,
        }
    }
    pub const fn restore_retention(&mut self, checkpoint: RetentionCheckpoint) {
        self.retained_events = checkpoint.events;
        self.retained_bytes = checkpoint.bytes;
    }

    pub fn observe_through(
        &mut self,
        offset: CaptureOffset,
    ) -> Result<(), BoundedAcquisitionError> {
        self.ensure_running()?;
        self.check_monotonic(offset)?;
        let deadline = self
            .observation
            .limits()
            .maximum_elapsed()
            .as_microseconds();
        self.observed_through =
            CaptureOffset::from_microseconds(offset.as_microseconds().min(deadline));
        if offset.as_microseconds() >= deadline {
            self.stop = Some(CaptureTermination::DeadlineReached {
                maximum_elapsed: self.observation.limits().maximum_elapsed(),
            });
        }
        Ok(())
    }

    pub fn admit(
        &mut self,
        event: LifecycleEvent,
    ) -> Result<EventAdmission, BoundedAcquisitionError> {
        self.ensure_running()?;
        self.check_monotonic(event.offset())?;
        let deadline = self
            .observation
            .limits()
            .maximum_elapsed()
            .as_microseconds();
        if event.offset().as_microseconds() >= deadline {
            self.observed_through = CaptureOffset::from_microseconds(deadline);
            let termination = CaptureTermination::DeadlineReached {
                maximum_elapsed: self.observation.limits().maximum_elapsed(),
            };
            self.stop = Some(termination.clone());
            return Ok(EventAdmission::NotAdmittedAndStopped(termination));
        }
        let events = self
            .admitted_events
            .checked_add(1)
            .ok_or(BoundedAcquisitionError::EventOverflow)?;
        let retained_events = self
            .retained_events
            .checked_add(u64::from(event.is_retained()))
            .ok_or(BoundedAcquisitionError::EventOverflow)?;
        let limits = self.observation.limits();
        let admitted_amount = limits.byte_limit().map_or_else(
            || event.admitted_bytes().get(),
            |limit| {
                limit
                    .get()
                    .saturating_sub(self.admitted_bytes)
                    .min(event.admitted_bytes().get())
            },
        );
        let retained_amount = event.retained_bytes().get().min(admitted_amount);
        let bytes = self
            .admitted_bytes
            .checked_add(admitted_amount)
            .ok_or(BoundedAcquisitionError::ByteOverflow)?;
        let retained_bytes = self
            .retained_bytes
            .checked_add(retained_amount)
            .ok_or(BoundedAcquisitionError::ByteOverflow)?;
        self.admitted_events = events;
        self.retained_events = retained_events;
        self.admitted_bytes = bytes;
        self.retained_bytes = retained_bytes;
        self.observed_through = event.offset();
        let admitted = yosoi_web_capture::AdmittedEvent::new(
            ByteCount::new(admitted_amount),
            ByteCount::new(retained_amount),
            event.is_retained(),
        );
        let termination = limits
            .event_limit()
            .filter(|limit| events == limit.get())
            .map(|event_limit| CaptureTermination::EventLimitReached { event_limit })
            .or_else(|| {
                limits
                    .byte_limit()
                    .filter(|limit| bytes == limit.get())
                    .map(|byte_limit| CaptureTermination::ByteLimitReached { byte_limit })
            });
        if let Some(termination) = termination {
            self.stop = Some(termination.clone());
            Ok(EventAdmission::AdmittedAndStopped {
                admitted,
                termination,
            })
        } else {
            Ok(EventAdmission::Admitted(admitted))
        }
    }

    pub fn stop(
        &mut self,
        offset: CaptureOffset,
        stop: LifecycleStop,
    ) -> Result<(), BoundedAcquisitionError> {
        self.ensure_running()?;
        self.check_monotonic(offset)?;
        if offset.as_microseconds()
            >= self
                .observation
                .limits()
                .maximum_elapsed()
                .as_microseconds()
        {
            return self.observe_through(offset);
        }
        self.observed_through = offset;
        self.stop = Some(match stop {
            LifecycleStop::Completed(reason) => CaptureTermination::ControllerStopped(reason),
            LifecycleStop::Interrupted(evidence) => CaptureTermination::Interrupted(evidence),
        });
        Ok(())
    }

    const fn ensure_running(&self) -> Result<(), BoundedAcquisitionError> {
        if self.stop.is_some() {
            Err(BoundedAcquisitionError::AlreadyStopped)
        } else {
            Ok(())
        }
    }
    fn check_monotonic(&self, offset: CaptureOffset) -> Result<(), BoundedAcquisitionError> {
        if offset < self.observed_through {
            Err(BoundedAcquisitionError::NonMonotonic {
                offered: offset.as_microseconds(),
                previous: self.observed_through.as_microseconds(),
            })
        } else {
            Ok(())
        }
    }
}
