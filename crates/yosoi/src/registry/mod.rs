//! Shared transactional state for cooperating Yosoi callers.
//!
//! [`Registry::new`] opens the standard per-user JSONL file; [`Registry::jsonl`]
//! selects an explicit file. Each handle has a caller identity, retained by
//! clones. Independent handles to the same file share state across processes.
//!
//! Read a [`Snapshot`], evaluate a decision, then [`Registry::commit`] against
//! its exact [`Revision`]. A conflict means the decision must be reevaluated;
//! never perform its external effect before the commit succeeds. These are
//! synchronous operations: async consumers should use a blocking task for file
//! operations. Registry does not execute requests, implement Respect rules, or
//! retain locks while consumer work runs.
//!
//! The journal bounds state to 4,096 entries and 4 MiB serialized, keys to
//! 256 UTF-8 bytes, individual values to 64 KiB/32 nesting levels, and a mutation
//! batch to 4,096 changes/4 MiB. JSONL history is capped at 64 MiB; compact it
//! before reaching that bound. These limits apply independently of traffic policy.

mod jsonl;
mod values;

use std::{fmt, path::Path, sync::Arc};

pub use values::{
    Caller, Change, Coordination, RegistryError, Reservation, Revision, Snapshot, Transaction,
    TransactionContext,
};

/// Cloneable runtime handle, separate from portable state/DTOs. Dropping a
/// handle does not remove durable state or affect other owners of its backend.
#[derive(Clone)]
pub struct Registry(Arc<jsonl::Jsonl>);

impl Registry {
    /// Opens the standard per-user JSONL file. Opening is fallible; failures
    /// never substitute empty state. Clones retain the same caller identity.
    pub fn new() -> Result<Self, RegistryError> {
        Self::jsonl(jsonl::global_path()?)
    }

    /// Caller identity attached to this handle's committed transactions.
    pub fn caller(&self) -> &Caller {
        self.0.caller()
    }

    /// Canonical journal path shared by cooperating local callers.
    pub fn path(&self) -> &Path {
        self.0.path()
    }

    /// Opens or creates an append-only journal. Relative paths resolve when
    /// opening; parents are created. Existing paths are canonicalized so symlink
    /// aliases share a lock. Hard-link aliases and network filesystems are not
    /// supported coordination mechanisms. Independent-owner file-lock contention
    /// returns `Busy` without polling. Clones serialize their local transactions. Committed malformed/versioned records fail loudly.
    pub fn jsonl(path: impl AsRef<Path>) -> Result<Self, RegistryError> {
        Ok(Self(Arc::new(jsonl::Jsonl::open(path.as_ref())?)))
    }

    /// Returns the backend's actual coordination boundary.
    pub const fn coordination(&self) -> Coordination {
        Coordination::LocalProcesses
    }

    /// Reads a snapshot. Values are copied and cannot mutate registry state.
    pub fn snapshot(&self) -> Result<Snapshot, RegistryError> {
        self.0.snapshot()
    }

    /// Applies changes atomically against a previously read revision. A stale
    /// decision returns `Conflict`; the caller chooses bounded retry/cancellation.
    pub fn commit(
        &self,
        expected: &Revision,
        changes: &[Change],
    ) -> Result<Snapshot, RegistryError> {
        self.commit_with_context(expected, changes, &TransactionContext::default())
    }

    /// Commits the complete batch with bounded application metadata. The
    /// context describes the decision; Registry supplies identity, time,
    /// sequence and caller. No network work runs under the file lock.
    pub fn commit_with_context(
        &self,
        expected: &Revision,
        changes: &[Change],
        context: &TransactionContext,
    ) -> Result<Snapshot, RegistryError> {
        self.0
            .commit(expected, changes, context)
            .map(|(snapshot, _)| snapshot)
    }

    pub(crate) fn commit_with_receipt(
        &self,
        expected: &Revision,
        changes: &[Change],
        context: &TransactionContext,
    ) -> Result<(Snapshot, Option<Transaction>), RegistryError> {
        self.0.commit(expected, changes, context)
    }

    /// Compacts durable history under the same transaction lock as readers and
    /// writers. No logical revision advances. Compaction retains state rather than
    /// an audit history; export the journal first if historical records are needed.
    pub fn compact(&self) -> Result<(), RegistryError> {
        self.0.compact()
    }
}

impl fmt::Debug for Registry {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Registry")
            .field("coordination", &self.coordination())
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests;
