//! One monotonic clock and absolute deadline for an acquisition attempt.

use std::time::{Duration, Instant};

use thiserror::Error;

use crate::{CaptureDuration, CaptureOffset};

/// Invalid clock observations cannot be published as acquisition offsets.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum AttemptBoundaryError {
    #[error("acquisition deadline must be greater than zero")]
    ZeroDuration,
    #[error("acquisition deadline exceeds the monotonic clock range")]
    DeadlineOverflow,
    #[error("clock observation precedes the acquisition start")]
    BeforeStart,
    #[error("acquisition elapsed time exceeds the offset range")]
    OffsetOverflow,
}

/// Shared clock semantics; each transport retains its own event and I/O loops.
#[derive(Clone, Copy, Debug)]
pub struct AttemptBoundary {
    started: Instant,
    deadline: Instant,
    maximum_elapsed: CaptureDuration,
}

impl AttemptBoundary {
    pub fn new(
        started: Instant,
        maximum_elapsed: CaptureDuration,
    ) -> Result<Self, AttemptBoundaryError> {
        if maximum_elapsed.as_microseconds() == 0 {
            return Err(AttemptBoundaryError::ZeroDuration);
        }
        let deadline = started
            .checked_add(Duration::from_micros(maximum_elapsed.as_microseconds()))
            .ok_or(AttemptBoundaryError::DeadlineOverflow)?;
        Ok(Self {
            started,
            deadline,
            maximum_elapsed,
        })
    }

    pub const fn started(self) -> Instant {
        self.started
    }

    pub const fn deadline(self) -> Instant {
        self.deadline
    }

    pub const fn maximum_elapsed(self) -> CaptureDuration {
        self.maximum_elapsed
    }

    pub fn elapsed(self) -> Result<CaptureOffset, AttemptBoundaryError> {
        self.offset_at(Instant::now())
    }

    pub fn offset_at(self, now: Instant) -> Result<CaptureOffset, AttemptBoundaryError> {
        let elapsed = now
            .checked_duration_since(self.started)
            .ok_or(AttemptBoundaryError::BeforeStart)?;
        let micros =
            u64::try_from(elapsed.as_micros()).map_err(|_| AttemptBoundaryError::OffsetOverflow)?;
        Ok(CaptureOffset::from_microseconds(micros))
    }

    /// Terminal acquisition time excludes time spent cleaning up after the deadline.
    pub fn bounded_offset_at(self, now: Instant) -> Result<CaptureOffset, AttemptBoundaryError> {
        let offset = self.offset_at(now)?;
        Ok(CaptureOffset::from_microseconds(
            offset
                .as_microseconds()
                .min(self.maximum_elapsed.as_microseconds()),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clock_and_deadline_share_one_origin() {
        let started = Instant::now();
        let boundary = AttemptBoundary::new(started, CaptureDuration::from_microseconds(10))
            .expect("bounded deadline");
        assert_eq!(boundary.offset_at(started).unwrap().as_microseconds(), 0);
        assert_eq!(
            boundary
                .offset_at(boundary.deadline())
                .unwrap()
                .as_microseconds(),
            10
        );
        let later = boundary
            .deadline()
            .checked_add(Duration::from_micros(7))
            .unwrap();
        assert_eq!(boundary.offset_at(later).unwrap().as_microseconds(), 17);
        assert_eq!(
            boundary.bounded_offset_at(later).unwrap().as_microseconds(),
            10
        );
    }

    #[test]
    fn observation_before_start_is_rejected() {
        let now = Instant::now();
        let started = now.checked_add(Duration::from_micros(1)).unwrap();
        let boundary =
            AttemptBoundary::new(started, CaptureDuration::from_microseconds(10)).unwrap();
        assert_eq!(
            boundary.offset_at(now),
            Err(AttemptBoundaryError::BeforeStart)
        );
    }

    #[test]
    fn zero_duration_is_rejected() {
        assert!(matches!(
            AttemptBoundary::new(Instant::now(), CaptureDuration::from_microseconds(0)),
            Err(AttemptBoundaryError::ZeroDuration)
        ));
    }
}
