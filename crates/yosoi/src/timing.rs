//! Millisecond timeout inputs and runtime deadline scopes.

use std::{future::Future, time::Duration};
use tokio::time::Instant;

/// Converts seconds to milliseconds. The `u32` input always fits in `u64`.
pub fn seconds(value: u32) -> u64 {
    u64::from(value).saturating_mul(1_000)
}

/// Returns the supplied millisecond value for use with `.timeout(...)`.
pub fn milliseconds(value: u32) -> u64 {
    u64::from(value)
}

tokio::task_local! { static ACTION_DEADLINE: Instant; }

pub(crate) async fn scope<T>(deadline: Instant, future: impl Future<Output = T>) -> T {
    ACTION_DEADLINE.scope(deadline, future).await
}

pub(crate) fn deadline() -> Option<Instant> {
    ACTION_DEADLINE.try_with(|deadline| *deadline).ok()
}

pub(crate) fn remaining() -> Option<Duration> {
    deadline().map(|deadline| deadline.saturating_duration_since(Instant::now()))
}

pub(crate) fn checked_deadline(duration: Duration) -> Option<Instant> {
    Instant::now().checked_add(duration)
}

#[cfg(any(not(feature = "browser"), test))]
pub(crate) async fn bound<T>(
    duration: Duration,
    future: impl Future<Output = T>,
) -> Result<T, tokio::time::error::Elapsed> {
    tokio::time::timeout(duration, future).await
}
