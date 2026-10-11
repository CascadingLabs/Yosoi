use std::collections::BTreeMap;

use serde::Serialize;

use super::super::BrowserProfileId;
use super::{
    BrowserProfileLifecycleRecord, BrowserProfileLifecycleState,
    MAX_BROWSER_PROFILE_POOL_SNAPSHOT_ENTRIES,
};

/// One profile included in a bounded pool snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfilePoolSnapshotEntry {
    profile_id: BrowserProfileId,
    state: BrowserProfileLifecycleState,
}

impl BrowserProfilePoolSnapshotEntry {
    pub const fn profile_id(&self) -> &BrowserProfileId {
        &self.profile_id
    }

    pub const fn state(&self) -> BrowserProfileLifecycleState {
        self.state
    }

    pub const fn is_eligible(&self) -> bool {
        self.state.is_eligible()
    }
}

/// Stable, lexically ordered prefix of the latest records for a profile pool.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfilePoolSnapshot {
    entries: Vec<BrowserProfilePoolSnapshotEntry>,
    truncated: bool,
}

impl BrowserProfilePoolSnapshot {
    pub fn from_records(
        records: &BTreeMap<BrowserProfileId, BrowserProfileLifecycleRecord>,
    ) -> Self {
        let entries: Vec<_> = records
            .iter()
            .take(MAX_BROWSER_PROFILE_POOL_SNAPSHOT_ENTRIES)
            .map(|(profile_id, record)| BrowserProfilePoolSnapshotEntry {
                profile_id: profile_id.clone(),
                state: record.next(),
            })
            .collect();
        let truncated = records.len() > entries.len();
        Self { entries, truncated }
    }

    pub fn entries(&self) -> &[BrowserProfilePoolSnapshotEntry] {
        &self.entries
    }

    pub const fn is_truncated(&self) -> bool {
        self.truncated
    }

    pub fn eligible_count(&self) -> usize {
        self.entries
            .iter()
            .filter(|entry| entry.is_eligible())
            .count()
    }
}
