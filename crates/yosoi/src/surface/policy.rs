//! Evidence retention selected by Surface policy, independent of storage location.

use serde::{Deserialize, Serialize};

/// Whether a Surface retains the evidence required to become an Archive value.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ArchivePolicy {
    /// Retain no portable outcome; ordinary immutable reads remain available.
    #[default]
    Off,
    /// Retain bounded operation inputs, observations and receipts for explicit saving.
    Enabled,
}

/// Resource limits for a self-contained Surface outcome before encoding.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ArchiveLimits {
    /// Maximum retained original source and derived payload bytes combined.
    pub bytes: u64,
    /// Maximum source captures and materialized artifacts.
    pub observations: usize,
    /// Maximum retained operation receipts, including rejected operations.
    pub operations: usize,
}

impl Default for ArchiveLimits {
    fn default() -> Self {
        Self {
            bytes: 64 * 1024 * 1024,
            observations: 256,
            operations: 4096,
        }
    }
}

impl ArchiveLimits {
    pub(super) fn validate(self) -> Result<(), super::SurfaceError> {
        if self.bytes == 0
            || self.bytes > 128 * 1024 * 1024
            || self.observations == 0
            || self.observations > 4096
            || self.operations == 0
            || self.operations > 4096
        {
            return Err(super::SurfaceError::Invalid(
                "invalid archive retention limits".into(),
            ));
        }
        Ok(())
    }
}

use super::Outcome;
use std::{error::Error, path::PathBuf};
/// Execution and retention settings for the Surface connection.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct SurfacePolicy {
    /// Per-representation capture, tree-depth and serialized response bounds.
    pub documents: super::DocumentPolicies,
    /// Whether execution retains a portable outcome. Defaults to off.
    pub archive: ArchivePolicy,
    /// Bounded evidence retention, separate from response budgets.
    pub archive_limits: ArchiveLimits,
    /// Optional durable checkpoint directory. Otherwise an owned temporary store is used.
    pub archive_root: Option<PathBuf>,
    /// Optional retained traces and artifacts. Otherwise temporary artifacts live with the runtime.
    pub output: Option<PathBuf>,
}
impl Default for SurfacePolicy {
    fn default() -> Self {
        Self {
            documents: super::DocumentPolicies::default(),
            archive: ArchivePolicy::Off,
            archive_limits: ArchiveLimits::default(),
            archive_root: None,
            output: None,
        }
    }
}

/// Failure from the shared execution boundary, preserving its diagnostic source.
#[derive(Debug, thiserror::Error)]
pub enum ExecutionError {
    /// Preparation, validation, provider, retention or cleanup failed.
    #[error("Surface execution failed: {0}")]
    Operation(#[source] Box<dyn Error + Send + Sync>),
    /// Execution failed after producing retained outcomes, including the failed attempt.
    #[error("Surface execution failed: {source}")]
    Execution {
        /// Separate completed or partial executions; each remains archivable.
        outcomes: Vec<Outcome>,
        /// Original execution or cleanup failure, without inventing success.
        #[source]
        source: Box<dyn Error + Send + Sync>,
    },
}
