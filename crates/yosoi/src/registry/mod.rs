//! Shared transactional state for cooperating Yosoi callers.
//!
//! [`Registry::default`] creates an isolated in-memory registry. Cloning its
//! handle shares state. [`Registry::jsonl`] opts into a durable journal shared
//! by processes using the same canonical path. No backend is selected by Policy.
//!
//! Read a [`Snapshot`], evaluate a decision, then [`Registry::commit`] against
//! its exact [`Revision`]. A conflict means the decision must be reevaluated;
//! never perform its external effect before the commit succeeds. These are
//! synchronous operations: async consumers should use a blocking task for file
//! operations. Registry does not execute requests, implement Respect rules, or
//! retain locks while consumer work runs.
//!
//! Built-in backends bound state to 4,096 entries and 4 MiB serialized, keys to
//! 256 UTF-8 bytes, individual values to 64 KiB/32 nesting levels, and a mutation
//! batch to 4,096 changes/4 MiB. JSONL history is capped at 64 MiB; compact it
//! before reaching that bound. These limits apply independently of traffic policy.

mod jsonl;
mod memory;
mod values;

use std::{fmt, path::Path, sync::Arc};

pub use values::{Change, Coordination, RegistryError, Revision, Snapshot};

/// Backend-independent atomic state contract, also implementable by future
/// database/coordinator adapters. Implementations must reject stale revisions
/// and apply every change in a batch together, or none. An I/O failure during
/// commit may leave its outcome indeterminate; inspect state before retrying.
pub(crate) trait Backend: Send + Sync {
    /// Describes the callers this backend can coordinate; not a durability claim.
    fn coordination(&self) -> Coordination;
    /// Reads one internally consistent state and revision.
    fn snapshot(&self) -> Result<Snapshot, RegistryError>;
    /// Commits a batch only if identity and sequence match the current revision.
    /// Empty batches still check the revision but do not advance it.
    fn commit(&self, expected: &Revision, changes: &[Change]) -> Result<Snapshot, RegistryError>;
    /// Bounds backend history without changing logical state, identity or revision.
    /// A backend without retained history may implement this as a no-op.
    fn compact(&self) -> Result<(), RegistryError>;
}

/// Cloneable runtime handle, separate from portable state/DTOs. Dropping a
/// handle does not remove durable state or affect other owners of its backend.
#[derive(Clone)]
pub struct Registry(Arc<dyn Backend>);

impl Default for Registry {
    fn default() -> Self {
        Self::with_backend(memory::Memory::default())
    }
}

impl Registry {
    /// Binds a backend implementing the atomic transaction contract. No fallback
    /// backend is substituted after errors. Clones share this exact backend.
    fn with_backend(backend: impl Backend + 'static) -> Self {
        Self(Arc::new(backend))
    }

    /// Opens or creates an append-only journal. Relative paths resolve when
    /// opening; parents are created. Existing paths are canonicalized so symlink
    /// aliases share a lock. Hard-link aliases and network filesystems are not
    /// supported coordination mechanisms. Lock contention returns `Busy` without
    /// waiting or polling. Committed malformed/versioned records fail loudly.
    pub fn jsonl(path: impl AsRef<Path>) -> Result<Self, RegistryError> {
        Ok(Self::with_backend(jsonl::Jsonl::open(path.as_ref())?))
    }

    /// Opens the standard per-user JSONL registry. This is opt-in, not the
    /// default backend. Uses absolute XDG_STATE_HOME or HOME/.local/state on
    /// Unix, and LOCALAPPDATA on Windows; missing/relative locations are errors.
    pub fn global_jsonl() -> Result<Self, RegistryError> {
        Self::jsonl(jsonl::global_path()?)
    }

    /// Returns the backend's actual coordination boundary.
    pub fn coordination(&self) -> Coordination {
        self.0.coordination()
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
        self.0.commit(expected, changes)
    }

    /// Compacts durable history under the same transaction lock as readers and
    /// writers. No logical revision advances. Memory backends have no history.
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
