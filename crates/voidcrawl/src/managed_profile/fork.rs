use std::{
    fmt, fs, io,
    path::{Path, PathBuf},
    result::Result as StdResult,
};

use crate::error::{Result, VoidCrawlError};

use super::copy::{copy_regular_file_if_present, copy_snapshot_recursively};
use super::{
    ManagedProfileDescription, Manifest, ProfileRegistry, acquire_profile_lock, expand_tilde,
    resolve_profile,
};

mod managed;

/// Guardrail against accidentally multiplying a large profile without bound.
pub const MAX_PROFILE_SPLIT_COPIES: usize = 16;
/// Temporary, isolated clone of a quiesced managed profile.
/// The directory is removed when this lease is dropped.
pub struct ManagedProfileSnapshot {
    source_id: String,
    path: PathBuf,
    _tempdir: tempfile::TempDir,
}

/// Committed managed-profile children produced from one held source lease.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManagedProfileForkBatch {
    pub source_id: String,
    pub children: Vec<ManagedProfileDescription>,
    /// Sum of the regular-file lengths copied into every child.
    pub copied_bytes: u64,
}

/// Filesystem stages for a managed-profile fork, kept independent of browser
/// engine and operating-system path details.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ManagedProfileForkOperation {
    CreateRegistryRoot,
    OpenManifestLock,
    LockManifest,
    ReadManifest,
    ParseManifest,
    CreateStagingRoot,
    CreateStagingDirectory,
    ReadSourceDirectory,
    ReadSourceEntry,
    ReadSourceFile,
    CreateDestinationFile,
    WriteDestinationFile,
    ReadDestinationMetadata,
    SetDestinationPermissions,
    MoveChildIntoPlace,
    SerializeManifest,
    WriteManifestTemporary,
    ReplaceManifest,
    RemoveStagingRoot,
    RemoveUncommittedChild,
}

/// Stable reason and observable cleanup/accounting facts for a fork failure.
#[derive(Debug, thiserror::Error)]
#[error("managed-profile fork failed: {kind}")]
pub struct ManagedProfileForkError {
    pub kind: ManagedProfileForkErrorKind,
    pub facts: ManagedProfileForkFailureFacts,
}

#[derive(Debug, thiserror::Error)]
pub enum ManagedProfileForkErrorKind {
    #[error("copy count {requested} is outside 1..={max}")]
    InvalidCopyCount { requested: usize, max: usize },
    #[error("child identifier at index {child_index} is invalid")]
    InvalidChildId { child_index: usize },
    #[error("child identifier at index {child_index} is repeated")]
    DuplicateChildId { child_index: usize },
    #[error("child profile at index {child_index} already exists")]
    ChildAlreadyExists { child_index: usize },
    #[error("source lease does not match a registered profile")]
    LeaseNotRegistered,
    #[error("source profile directory is missing")]
    SourceMissing,
    #[error("aggregate byte quota {quota_bytes} exceeded at {attempted_bytes} bytes")]
    AggregateByteQuotaExceeded {
        quota_bytes: u64,
        attempted_bytes: u64,
    },
    #[error("copied-byte accounting overflowed")]
    ByteCountOverflow,
    #[error("copied-file byte count did not match its staged file")]
    CopiedFileLengthMismatch { child_index: usize },
    #[error("filesystem operation {operation:?} failed with {io_kind:?}")]
    Io {
        operation: ManagedProfileForkOperation,
        child_index: Option<usize>,
        io_kind: io::ErrorKind,
    },
    #[error("the existing managed-profile manifest is invalid")]
    InvalidManifest,
    #[error("managed-profile manifest serialization failed")]
    ManifestSerializationFailed,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ManagedProfileForkFailureFacts {
    /// Index of the child being copied or committed when the operation failed.
    pub child_index: Option<usize>,
    /// Regular-file bytes successfully copied before failure.
    pub copied_bytes: u64,
    /// Whether all staged and unregistered child directories were removed.
    pub cleanup_succeeded: bool,
}

impl ManagedProfileForkError {
    pub(super) fn new(kind: ManagedProfileForkErrorKind) -> Self {
        Self {
            kind,
            facts: ManagedProfileForkFailureFacts {
                cleanup_succeeded: true,
                ..ManagedProfileForkFailureFacts::default()
            },
        }
    }
}

impl fmt::Debug for ManagedProfileSnapshot {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ManagedProfileSnapshot")
            .field("source_id", &self.source_id)
            .field("path", &self.path)
            .finish_non_exhaustive()
    }
}

impl ManagedProfileSnapshot {
    pub fn source_id(&self) -> &str {
        &self.source_id
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

impl ProfileRegistry {
    /// Create a uniquely named temporary snapshot while holding the source's
    /// authoritative VoidCrawl lease. Lock and Chrome Singleton files are not
    /// copied. The returned directory is deleted on drop.
    pub fn snapshot_profile(&self, id: &str) -> Result<ManagedProfileSnapshot> {
        self.snapshot_copies(id, 1)?
            .pop()
            .ok_or_else(|| VoidCrawlError::Other("profile snapshot was not created".into()))
    }

    /// Fork an installed native Chrome profile into isolated, concurrently
    /// runnable `user_data_dir` roots.
    ///
    /// `source_name_or_path` may be a discovered Chrome profile name such as
    /// `Default` or an explicit profile-directory path. The containing Chrome
    /// user-data root must not be running: copying live SQLite and LevelDB
    /// state cannot produce a consistent fork. The native profile is
    /// normalized to `Default` inside each result, and its root `Local
    /// State` file is copied so encrypted cookies and profile metadata
    /// retain their Chrome context.
    pub fn fork_profile(
        &self,
        source_name_or_path: &str,
        copies: usize,
    ) -> Result<Vec<ManagedProfileSnapshot>> {
        validate_split_copies(copies)?;
        let explicit = PathBuf::from(expand_tilde(source_name_or_path));
        let source = if explicit.is_dir() {
            explicit
        } else {
            resolve_profile(source_name_or_path)?
        };
        if !source.join("Preferences").is_file() {
            return Err(VoidCrawlError::ProfileNotFound {
                name: source_name_or_path.to_string(),
                searched: vec![source.display().to_string()],
            });
        }
        let user_data_root = source.parent().ok_or_else(|| {
            VoidCrawlError::Other(format!(
                "native profile {} has no Chrome user-data parent",
                source.display()
            ))
        })?;
        let singleton_lock = user_data_root.join("SingletonLock");
        if singleton_lock.symlink_metadata().is_ok() {
            return Err(VoidCrawlError::ChromeProfileBusy {
                name: source_name_or_path.to_string(),
                lock_path: singleton_lock.display().to_string(),
            });
        }

        let _source_lease = acquire_profile_lock(source_name_or_path, &source)?;
        self.copy_profile_baseline(source_name_or_path, copies, |destination| {
            let default_profile = destination.join("Default");
            copy_snapshot_recursively(&source, &default_profile)?;
            copy_regular_file_if_present(
                &user_data_root.join("Local State"),
                &destination.join("Local State"),
            )
        })
    }

    /// Split one quiesced managed profile into isolated, concurrently runnable
    /// copies from the same baseline.
    ///
    /// The source lease is held across every copy, so no cooperating VoidCrawl
    /// process can modify the source between copy one and copy N. Each returned
    /// snapshot has a unique `user_data_dir`; Chrome therefore gives every
    /// worker its own `SingletonLock`. The copies begin with the same cookies,
    /// storage, extensions, and profile identity, but writes made after launch
    /// are intentionally not synchronized between them or back to the source.
    /// Dropping the returned snapshots deletes all temporary directories.
    pub fn split_profile(&self, id: &str, copies: usize) -> Result<Vec<ManagedProfileSnapshot>> {
        validate_split_copies(copies)?;
        self.snapshot_copies(id, copies)
    }

    fn snapshot_copies(&self, id: &str, copies: usize) -> Result<Vec<ManagedProfileSnapshot>> {
        let profile = self.describe_profile(id)?.profile;
        let _source_lease = acquire_profile_lock(id, &profile.path)?;
        self.copy_profile_baseline(id, copies, |destination| {
            copy_snapshot_recursively(&profile.path, destination)
        })
    }

    fn copy_profile_baseline(
        &self,
        source_id: &str,
        copies: usize,
        mut copy_into: impl FnMut(&Path) -> Result<()>,
    ) -> Result<Vec<ManagedProfileSnapshot>> {
        let snapshots_root = self.root.join(".snapshots");
        fs::create_dir_all(&snapshots_root).map_err(|e| {
            VoidCrawlError::Other(format!(
                "create snapshot root {}: {e}",
                snapshots_root.display()
            ))
        })?;

        let mut snapshots = Vec::with_capacity(copies);
        for _ in 0..copies {
            let tempdir = tempfile::Builder::new()
                .prefix(&format!("{source_id}-"))
                .tempdir_in(&snapshots_root)
                .map_err(|e| VoidCrawlError::Other(format!("create profile snapshot: {e}")))?;
            let path = tempdir.path().join("profile");
            copy_into(&path)?;
            snapshots.push(ManagedProfileSnapshot {
                source_id: source_id.to_string(),
                path,
                _tempdir: tempdir,
            });
        }
        Ok(snapshots)
    }
}

fn validate_split_copies(copies: usize) -> Result<()> {
    if !(2..=MAX_PROFILE_SPLIT_COPIES).contains(&copies) {
        return Err(VoidCrawlError::Other(format!(
            "profile split copies must be between 2 and {MAX_PROFILE_SPLIT_COPIES}"
        )));
    }
    Ok(())
}

pub(super) fn read_fork_manifest(path: &Path) -> StdResult<Manifest, ManagedProfileForkError> {
    let raw = match fs::read_to_string(path) {
        Ok(raw) => raw,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Manifest::default()),
        Err(error) => {
            return Err(fork_io_error(
                ManagedProfileForkOperation::ReadManifest,
                None,
                error,
            ));
        }
    };
    serde_json::from_str(&raw)
        .map_err(|_| ManagedProfileForkError::new(ManagedProfileForkErrorKind::InvalidManifest))
}

#[allow(
    clippy::needless_pass_by_value,
    reason = "the provider error is intentionally reduced to a secret-safe kind"
)]
pub(super) fn fork_io_error(
    operation: ManagedProfileForkOperation,
    child_index: Option<usize>,
    error: io::Error,
) -> ManagedProfileForkError {
    ManagedProfileForkError::new(ManagedProfileForkErrorKind::Io {
        operation,
        child_index,
        io_kind: error.kind(),
    })
}

pub(super) fn close_staging_directory(
    staging: tempfile::TempDir,
    staging_path: &Path,
) -> (bool, Option<io::ErrorKind>) {
    match staging.close() {
        Ok(()) => (true, None),
        Err(error) => {
            let retry_succeeded = match fs::remove_dir_all(staging_path) {
                Ok(()) => true,
                Err(cleanup_error) if cleanup_error.kind() == io::ErrorKind::NotFound => true,
                Err(_) => false,
            };
            (retry_succeeded, Some(error.kind()))
        }
    }
}

pub(super) fn remove_uncommitted_children(paths: &[PathBuf]) -> bool {
    paths.iter().all(|path| match fs::remove_dir_all(path) {
        Ok(()) => true,
        Err(error) if error.kind() == io::ErrorKind::NotFound => true,
        Err(_) => false,
    })
}

pub(super) fn remove_file_if_present(path: &Path) -> bool {
    match fs::remove_file(path) {
        Ok(()) => true,
        Err(error) if error.kind() == io::ErrorKind::NotFound => true,
        Err(_) => false,
    }
}
