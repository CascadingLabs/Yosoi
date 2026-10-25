//! Shared archive opt-in and output selection, independent of source processes.
use serde::{Deserialize, Serialize};
use std::{error::Error, path::PathBuf};
/// Whether a source retains immutable evidence and operation receipts.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ArchivePolicy {
    /// Retain no archive data.
    #[default]
    Off,
    /// Retain captures and command receipts.
    Enabled,
}
/// Evidence and output policy shared by browser and video connections.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct SurfacePolicy {
    /// Explicit archive opt-in; disabled by default.
    pub archive: ArchivePolicy,
    /// Durable archive directory, otherwise an owned temporary store.
    pub archive_root: Option<PathBuf>,
    /// Trace and artifact directory, otherwise owned temporary storage.
    pub output: Option<PathBuf>,
}
/// Source preparation, execution or cleanup failure; effects may already have occurred.
#[derive(Debug, thiserror::Error)]
pub enum ExecutionError {
    /// Original source or persistence failure, without rollback claims.
    #[error("surface execution failed: {0}")]
    Operation(#[source] Box<dyn Error + Send + Sync>),
}
