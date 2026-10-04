//! Nonblocking, process-local admission for documented anonymous quotas.
use std::{
    collections::{BTreeMap, VecDeque},
    sync::{Mutex, OnceLock},
    time::{Duration, Instant},
};

use super::super::{PublicProvider, SourceFailure};

static RECENT: OnceLock<Mutex<BTreeMap<PublicProvider, VecDeque<Instant>>>> = OnceLock::new();

pub(super) fn admit(provider: PublicProvider) -> Result<(), SourceFailure> {
    let (count, window) = match provider {
        PublicProvider::SubdomainCenter => (5, Duration::from_secs(60)),
        PublicProvider::HackerTarget => (20, Duration::from_hours(24)),
        _ => return Ok(()),
    };
    let mut recent = RECENT
        .get_or_init(|| Mutex::new(BTreeMap::new()))
        .lock()
        .map_err(|_| SourceFailure::RateLimited)?;
    let now = Instant::now();
    let calls = recent.entry(provider).or_default();
    while calls
        .front()
        .is_some_and(|time| now.saturating_duration_since(*time) >= window)
    {
        calls.pop_front();
    }
    if calls.len() >= count {
        return Err(SourceFailure::RateLimited);
    }
    calls.push_back(now);
    drop(recent);
    Ok(())
}
