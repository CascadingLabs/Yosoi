//! Capture capacity is independent of retained tabs and action-worker permits.

use crate::{policy::ObserveLimits, session::SessionError};
use std::sync::{
    Arc,
    atomic::{AtomicU32, AtomicU64, Ordering},
};

#[derive(Clone)]
pub(super) struct CaptureAdmission {
    sources: Arc<AtomicU32>,
    outputs: Arc<AtomicU32>,
    buffered: Arc<AtomicU64>,
    limits: ObserveLimits,
}

impl CaptureAdmission {
    pub(super) fn new(limits: &ObserveLimits) -> Self {
        Self {
            sources: Arc::new(AtomicU32::new(0)),
            outputs: Arc::new(AtomicU32::new(0)),
            buffered: Arc::new(AtomicU64::new(0)),
            limits: *limits,
        }
    }

    pub(super) fn source(&self) -> Result<CapturePermit, SessionError> {
        reserve_count(&self.sources, self.limits.max_sources)
    }

    pub(super) fn output(&self) -> Result<CapturePermit, SessionError> {
        reserve_count(&self.outputs, self.limits.max_recordings)
    }

    pub(super) fn buffer(&self, bytes: u64) -> Result<CaptureBufferPermit, SessionError> {
        let maximum = self.limits.max_buffer_bytes.get();
        self.buffered
            .try_update(Ordering::AcqRel, Ordering::Acquire, |used| {
                used.checked_add(bytes).filter(|total| *total <= maximum)
            })
            .map_err(|_| SessionError::Admission)?;
        Ok(CaptureBufferPermit {
            buffered: Arc::clone(&self.buffered),
            bytes,
        })
    }
}

fn reserve_count(counter: &Arc<AtomicU32>, maximum: u32) -> Result<CapturePermit, SessionError> {
    counter
        .try_update(Ordering::AcqRel, Ordering::Acquire, |used| {
            used.checked_add(1).filter(|total| *total <= maximum)
        })
        .map_err(|_| SessionError::Admission)?;
    Ok(CapturePermit {
        counter: Arc::clone(counter),
    })
}

pub(super) struct CapturePermit {
    counter: Arc<AtomicU32>,
}
impl Drop for CapturePermit {
    fn drop(&mut self) {
        let _ = self
            .counter
            .try_update(Ordering::AcqRel, Ordering::Acquire, |used| {
                used.checked_sub(1)
            });
    }
}

/// RAII reservation that keeps transient capture bytes charged to the Session.
pub struct CaptureBufferPermit {
    buffered: Arc<AtomicU64>,
    bytes: u64,
}
impl Drop for CaptureBufferPermit {
    fn drop(&mut self) {
        let _ = self
            .buffered
            .try_update(Ordering::AcqRel, Ordering::Acquire, |used| {
                used.checked_sub(self.bytes)
            });
    }
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use super::*;
    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions fail the test harness; Result propagates fallible fixture setup"
    )]
    fn source_output_and_buffer_reservations_release_independently() -> Result<(), Box<dyn Error>> {
        let limits = ObserveLimits {
            max_sources: 1,
            max_recordings: 2,
            ..ObserveLimits::default()
        };
        let admission = CaptureAdmission::new(&limits);
        let source = admission.source()?;
        assert!(admission.source().is_err());
        let first = admission.output()?;
        let second = admission.output()?;
        assert!(admission.output().is_err());
        drop(first);
        let _replacement = admission.output()?;
        let buffer = admission.buffer(limits.max_buffer_bytes.get())?;
        assert!(admission.buffer(1).is_err());
        drop(buffer);
        let _small_buffer = admission.buffer(1)?;
        drop(second);
        drop(source);
        let _next_source = admission.source()?;
        Ok(())
    }
}
