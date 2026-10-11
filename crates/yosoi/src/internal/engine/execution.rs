//! Bounded execution capacity, independent of browser/tab ownership.
use std::sync::{
    Arc,
    atomic::{AtomicU32, AtomicU64, Ordering},
};
use thiserror::Error;
use tokio::sync as tokio_sync;
use tokio::sync::{OwnedSemaphorePermit, Semaphore, broadcast};

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ExecutionPoolError {
    #[error("execution capacity must be between 1 and 32; queue capacity between 1 and 1024")]
    InvalidLimits,
    #[error("execution queue is full")]
    QueueFull,
    #[error("execution pool is closed")]
    Closed,
}

/// Clone/share this pool across Sessions to bound work across browser processes.
/// It lends execution slots, never tab or browser ownership. Admission is FIFO.
#[derive(Clone, Debug)]
pub struct ExecutionPool {
    inner: Arc<Inner>,
}
#[derive(Debug)]
struct Inner {
    workers: Arc<Semaphore>,
    waiters: Arc<Semaphore>,
    capacity: u32,
    active: AtomicU32,
    queued: AtomicU32,
    parked: AtomicU32,
    waiting: AtomicU32,
    events: broadcast::Sender<ExecutionSnapshot>,
    peak: AtomicU32,
    admitted: AtomicU64,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ExecutionSnapshot {
    pub capacity: u32,
    pub active: u32,
    pub queued: u32,
    pub parked: u32,
    pub waiting: u32,
    pub peak_active: u32,
    pub admitted: u64,
}

impl ExecutionPool {
    pub fn new(concurrency: u32, queue_capacity: u32) -> Result<Self, ExecutionPoolError> {
        if !(1..=32).contains(&concurrency) || !(1..=1024).contains(&queue_capacity) {
            return Err(ExecutionPoolError::InvalidLimits);
        }
        Ok(Self {
            inner: Arc::new(Inner {
                workers: Arc::new(Semaphore::new(
                    usize::try_from(concurrency).map_err(|_| ExecutionPoolError::InvalidLimits)?,
                )),
                waiters: Arc::new(Semaphore::new(
                    usize::try_from(queue_capacity)
                        .map_err(|_| ExecutionPoolError::InvalidLimits)?,
                )),
                capacity: concurrency,
                active: AtomicU32::new(0),
                queued: AtomicU32::new(0),
                parked: AtomicU32::new(0),
                waiting: AtomicU32::new(0),
                events: broadcast::channel(64).0,
                peak: AtomicU32::new(0),
                admitted: AtomicU64::new(0),
            }),
        })
    }
    pub fn snapshot(&self) -> ExecutionSnapshot {
        ExecutionSnapshot {
            capacity: self.inner.capacity,
            active: self.inner.active.load(Ordering::Relaxed),
            queued: self.inner.queued.load(Ordering::Relaxed),
            parked: self.inner.parked.load(Ordering::Relaxed),
            waiting: self.inner.waiting.load(Ordering::Relaxed),
            peak_active: self.inner.peak.load(Ordering::Relaxed),
            admitted: self.inner.admitted.load(Ordering::Relaxed),
        }
    }
    #[doc(hidden)]
    pub async fn acquire(&self) -> Result<ExecutionPermit, ExecutionPoolError> {
        let permit = match Arc::clone(&self.inner.workers).try_acquire_owned() {
            Ok(permit) => permit,
            Err(tokio_sync::TryAcquireError::Closed) => return Err(ExecutionPoolError::Closed),
            Err(tokio_sync::TryAcquireError::NoPermits) => {
                let waiting = Arc::clone(&self.inner.waiters)
                    .try_acquire_owned()
                    .map_err(|_| ExecutionPoolError::QueueFull)?;
                let _ = self
                    .inner
                    .queued
                    .try_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
                        Some(n.saturating_add(1))
                    });
                let queue = QueueGuard {
                    inner: Arc::clone(&self.inner),
                    _permit: waiting,
                };
                self.publish();
                let permit = Arc::clone(&self.inner.workers)
                    .acquire_owned()
                    .await
                    .map_err(|_| ExecutionPoolError::Closed)?;
                drop(queue);
                permit
            }
        };
        let previous = self
            .inner
            .active
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
                Some(n.saturating_add(1))
            })
            .unwrap_or(0);
        self.inner
            .peak
            .fetch_max(previous.saturating_add(1), Ordering::Relaxed);
        let _ = self
            .inner
            .admitted
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
                Some(n.saturating_add(1))
            });
        self.publish();
        Ok(ExecutionPermit {
            inner: Arc::clone(&self.inner),
            _permit: permit,
        })
    }
    #[doc(hidden)]
    pub fn park(&self) -> ParkedExecution {
        self.condition_wait(true)
    }
    /// Bounded telemetry; slow observers receive Tokio's explicit lag error.
    /// Observing capacity does not acquire a worker or a tab lease.
    pub fn subscribe(&self) -> broadcast::Receiver<ExecutionSnapshot> {
        self.inner.events.subscribe()
    }
    fn publish(&self) {
        let _ = self.inner.events.send(self.snapshot());
    }
    #[doc(hidden)]
    pub fn condition_wait(&self, yielded: bool) -> ParkedExecution {
        let _ = self
            .inner
            .waiting
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
                Some(n.saturating_add(1))
            });
        if yielded {
            let _ = self
                .inner
                .parked
                .try_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
                    Some(n.saturating_add(1))
                });
        }
        self.publish();
        ParkedExecution {
            inner: Arc::clone(&self.inner),
            yielded,
        }
    }
}
#[derive(Debug)]
pub struct ExecutionPermit {
    inner: Arc<Inner>,
    _permit: OwnedSemaphorePermit,
}
impl Drop for ExecutionPermit {
    fn drop(&mut self) {
        let _ = self
            .inner
            .active
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
                Some(n.saturating_sub(1))
            });
        ExecutionPool {
            inner: Arc::clone(&self.inner),
        }
        .publish();
    }
}
struct QueueGuard {
    inner: Arc<Inner>,
    _permit: OwnedSemaphorePermit,
}
impl Drop for QueueGuard {
    fn drop(&mut self) {
        let _ = self
            .inner
            .queued
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
                Some(n.saturating_sub(1))
            });
        ExecutionPool {
            inner: Arc::clone(&self.inner),
        }
        .publish();
    }
}
#[derive(Debug)]
pub struct ParkedExecution {
    inner: Arc<Inner>,
    yielded: bool,
}
impl Drop for ParkedExecution {
    fn drop(&mut self) {
        let _ = self
            .inner
            .waiting
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
                Some(n.saturating_sub(1))
            });
        if self.yielded {
            let _ = self
                .inner
                .parked
                .try_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
                    Some(n.saturating_sub(1))
                });
        }
        let pool = ExecutionPool {
            inner: Arc::clone(&self.inner),
        };
        pool.publish();
    }
}
