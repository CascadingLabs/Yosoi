//! Provider-free lifecycle policy for managed browser profiles.
//!
//! This module decides whether a profile can be offered for a lease. It does
//! not create directories, recover browser state, or talk to a provider.

use thiserror::Error;

mod domain;
mod pool;
mod record;
mod store;

pub use domain::*;
pub use pool::*;
pub use record::*;
pub use store::*;

/// Current schema for serialized profile lifecycle transition records.
pub const BROWSER_PROFILE_LIFECYCLE_SCHEMA_VERSION: u16 = 2;
/// Maximum number of profiles included in one deterministic pool snapshot.
pub const MAX_BROWSER_PROFILE_POOL_SNAPSHOT_ENTRIES: usize = 128;

/// Redacted failures returned by the local profile lifecycle store.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ProfileLifecycleStoreError {
    #[error("profile lifecycle store root is empty")]
    EmptyRoot,
    #[error("profile lifecycle store I/O failed")]
    Io,
    #[error("profile lifecycle store contains an invalid record")]
    CorruptRecord,
    #[error("profile lifecycle store contains an unexpected entry")]
    CorruptStore,
    #[error("profile lifecycle transition does not match stored state")]
    StaleTransition,
    #[error("profile lifecycle store requires an initial staged record")]
    InvalidInitialRecord,
    #[error("profile lifecycle local filesystem lock is unavailable")]
    LockUnavailable,
    #[error("profile lifecycle temporary file names are unavailable")]
    TemporaryNameUnavailable,
    #[error("profile lifecycle record is invalid")]
    InvalidRecord,
}
