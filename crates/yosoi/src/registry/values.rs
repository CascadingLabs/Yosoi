use std::{collections::BTreeMap, io};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;
use uuid::Uuid;

pub(super) const MAX_STATE_BYTES: usize = 4 * 1024 * 1024;

/// Backend coordination boundary. Independent registries never implicitly share
/// state, even when they declare the same boundary.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Coordination {
    /// Only callers sharing this backend instance coordinate.
    Instance,
    /// Cooperating local processes sharing the same persistent registry coordinate.
    LocalProcesses,
    /// A backend coordinates clients across machines under its own contract.
    Distributed,
}

/// Portable optimistic-concurrency token. Identity prevents a revision from one
/// registry being accepted by an unrelated registry at the same sequence.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Revision {
    /// Stable logical registry identity, retained through restart and compaction.
    pub registry_id: String,
    /// Monotonically increasing commit sequence, starting at zero.
    pub sequence: u64,
}

/// Owned, serializable registry state at one exact revision. Keys identify
/// application DTOs; Registry does not interpret provider names or URLs.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    /// Identity and sequence to supply when committing a decision.
    pub revision: Revision,
    /// Portable JSON DTOs, ordered by their stable application keys.
    pub entries: BTreeMap<String, Value>,
}

impl Snapshot {
    pub(super) fn empty() -> Self {
        Self {
            revision: Revision {
                registry_id: Uuid::new_v4().to_string(),
                sequence: 0,
            },
            entries: BTreeMap::new(),
        }
    }

    pub(super) fn validate(&self) -> Result<(), RegistryError> {
        if Uuid::parse_str(&self.revision.registry_id).is_err() {
            return Err(RegistryError::InvalidState);
        }
        if self.entries.len() > 4096 {
            return Err(RegistryError::CapacityExceeded);
        }
        for (key, value) in &self.entries {
            validate_key(key)?;
            validate_value(value)?;
        }
        if serde_json::to_vec(self)?.len() > MAX_STATE_BYTES {
            return Err(RegistryError::CapacityExceeded);
        }
        Ok(())
    }

    pub(super) fn changed(
        &self,
        expected: &Revision,
        changes: &[Change],
    ) -> Result<Self, RegistryError> {
        if expected != &self.revision {
            return Err(RegistryError::Conflict);
        }
        if changes.len() > 4096 {
            return Err(RegistryError::CapacityExceeded);
        }
        for change in changes {
            match change {
                Change::Put { key, value } => {
                    validate_key(key)?;
                    validate_value(value)?;
                }
                Change::Remove { key } => {
                    validate_key(key)?;
                }
            }
        }
        if serde_json::to_vec(changes)?.len() > MAX_STATE_BYTES {
            return Err(RegistryError::CapacityExceeded);
        }
        let mut next = self.clone();
        for change in changes {
            match change {
                Change::Put { key, value } => {
                    next.entries.insert(key.clone(), value.clone());
                }
                Change::Remove { key } => {
                    next.entries.remove(key);
                }
            }
        }
        if !changes.is_empty() {
            next.revision.sequence = next
                .revision
                .sequence
                .checked_add(1)
                .ok_or(RegistryError::CapacityExceeded)?;
        }
        next.validate()?;
        Ok(next)
    }
}

fn validate_key(key: &str) -> Result<(), RegistryError> {
    if key.is_empty() || key.len() > 256 || key.chars().any(char::is_control) {
        return Err(RegistryError::InvalidKey);
    }
    Ok(())
}

fn validate_value(value: &Value) -> Result<(), RegistryError> {
    // Bound nesting before invoking recursive Serde or Clone. This also keeps
    // every accepted value below the journal decoder's recursion boundary.
    let mut pending = vec![(value, 0_u8)];
    while let Some((value, depth)) = pending.pop() {
        if depth > 32 {
            return Err(RegistryError::CapacityExceeded);
        }
        let child_depth = depth.saturating_add(1);
        match value {
            Value::Array(values) => pending.extend(values.iter().map(|value| (value, child_depth))),
            Value::Object(values) => {
                pending.extend(values.values().map(|value| (value, child_depth)));
            }
            _ => {}
        }
    }
    if serde_json::to_vec(value)?.len() > 64 * 1024 {
        return Err(RegistryError::CapacityExceeded);
    }
    Ok(())
}

/// One mutation in an atomic ordered batch. A value is a portable JSON DTO;
/// live handles, mutexes, and backend resources do not belong in it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Change {
    /// Creates or replaces one entry.
    Put {
        /// Stable nonempty key, at most 256 UTF-8 bytes, without control characters.
        key: String,
        /// New JSON value, at most 64 KiB serialized and 32 nesting levels.
        value: Value,
    },
    /// Removes an entry; removing a missing entry is allowed.
    Remove {
        /// Stable key to remove, under the same bounds as a put.
        key: String,
    },
}

/// Explicit registry failures. Callers must not dispatch external work based on
/// a failed commit or silently replace an unavailable registry with empty state.
#[derive(Debug, Error)]
pub enum RegistryError {
    /// Another transaction changed state or the expected identity was unrelated.
    #[error("registry revision conflict; reevaluate the decision before retrying")]
    Conflict,
    /// A local file transaction is already running. No waiting/retry is hidden.
    #[error("registry is busy")]
    Busy,
    /// An in-memory owner panicked while holding its lock.
    #[error("registry state lock is poisoned")]
    Poisoned,
    /// Keys must be nonempty, bounded and contain no control characters.
    #[error("invalid registry key")]
    InvalidKey,
    /// Stored state is malformed, inconsistent, empty, or has an unsupported version.
    #[error("invalid or unsupported registry journal")]
    InvalidState,
    /// State, transaction, sequence or journal exceeded its bounded capacity.
    #[error("registry capacity exceeded; compact the journal or reduce state")]
    CapacityExceeded,
    /// No absolute standard user state location is available.
    #[error("no absolute user state directory is configured")]
    NoGlobalLocation,
    /// Filesystem errors propagate. A write/sync failure can have an indeterminate
    /// commit outcome; inspect the journal before deciding whether to retry.
    #[error("registry I/O failed: {0}")]
    Io(#[from] io::Error),
    /// JSON conversion failed before commit or while decoding a portable value.
    #[error("registry JSON conversion failed: {0}")]
    Json(#[from] serde_json::Error),
}
