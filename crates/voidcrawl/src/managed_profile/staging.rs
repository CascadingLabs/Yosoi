use std::{
    fmt, fs, io,
    path::{Path, PathBuf},
};

use crate::error::VoidCrawlError;

use super::{ManagedProfileLease, ProfileRegistry};

mod profile;
mod registry;

#[cfg(test)]
#[path = "staging_tests.rs"]
mod staging_publication_tests;

/// Filesystem operation associated with an unpublished managed profile.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ManagedProfileStagingOperation {
    CreateRegistryRoot,
    OpenManifestLock,
    LockManifest,
    ReadManifest,
    ParseManifest,
    CreateStagingRoot,
    ReserveProfileId,
    SeedProfile,
    AcquireLease,
    PublishDirectory,
    SerializeManifest,
    WriteManifestTemporary,
    ReplaceManifest,
    RemoveStagingDirectory,
    ListUnregisteredFinalDirectories,
}

/// Safe disposition of the staged profile after an operation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ManagedProfileStagingDisposition {
    NotCreated,
    StagedUnavailable,
    PublishedAvailable,
    Discarded,
    RetainedUnavailable,
}

/// Secret and path-free reason for a managed-profile staging failure.
#[derive(Debug, thiserror::Error)]
pub enum ManagedProfileStagingErrorKind {
    #[error("profile identifier is invalid")]
    InvalidProfileId,
    #[error("profile identifier is already registered, staged, or reserved")]
    DuplicateProfileId,
    #[error("staged profile lease does not belong to this staged profile")]
    LeaseIdentityMismatch,
    #[error("profile lease remains active")]
    LeaseStillActive,
    #[error("staged profile registry manifest is invalid")]
    InvalidManifest,
    #[error("staged profile manifest could not be serialized")]
    ManifestSerializationFailed,
    #[error(
        "manifest publication failed during {publication_operation:?} and directory rollback failed"
    )]
    PublicationRollbackFailed {
        publication_operation: ManagedProfileStagingOperation,
        publication_io_kind: Option<io::ErrorKind>,
        rollback_io_kind: io::ErrorKind,
    },
    #[error("filesystem operation {operation:?} failed with {io_kind:?}")]
    Io {
        operation: ManagedProfileStagingOperation,
        io_kind: io::ErrorKind,
    },
}

/// Typed staging failure with an explicit safe disposition for recovery.
#[derive(Debug, thiserror::Error)]
#[error("managed-profile staging failed: {kind}")]
pub struct ManagedProfileStagingError {
    pub kind: ManagedProfileStagingErrorKind,
    pub disposition: ManagedProfileStagingDisposition,
}

impl ManagedProfileStagingError {
    const fn new(
        kind: ManagedProfileStagingErrorKind,
        disposition: ManagedProfileStagingDisposition,
    ) -> Self {
        Self { kind, disposition }
    }
}

trait StagingManifestPublisher {
    fn write_temporary_manifest(&self, path: &Path, contents: &str) -> io::Result<()>;
    fn replace_manifest(&self, temporary_path: &Path, manifest_path: &Path) -> io::Result<()>;
    fn restore_staged_directory(&self, published_path: &Path, staged_path: &Path)
    -> io::Result<()>;
}

struct FilesystemStagingManifestPublisher;

impl StagingManifestPublisher for FilesystemStagingManifestPublisher {
    fn write_temporary_manifest(&self, path: &Path, contents: &str) -> io::Result<()> {
        fs::write(path, contents)
    }

    fn replace_manifest(&self, temporary_path: &Path, manifest_path: &Path) -> io::Result<()> {
        fs::rename(temporary_path, manifest_path)
    }

    fn restore_staged_directory(
        &self,
        published_path: &Path,
        staged_path: &Path,
    ) -> io::Result<()> {
        fs::rename(published_path, staged_path)
    }
}

/// Unpublished profile directory reserved beneath the registry's private
/// staging directory. Dropping this handle leaves the directory unavailable
/// so a later lifecycle classifier can inspect it.
pub struct StagedManagedProfile {
    pub(super) registry: ProfileRegistry,
    pub(super) id: String,
    pub(super) path: PathBuf,
    pub(super) description: Option<String>,
    pub(super) labels: Vec<String>,
    pub(super) created_at: u64,
}

impl fmt::Debug for StagedManagedProfile {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("StagedManagedProfile")
            .field("id", &self.id)
            .field("state", &"staged_unavailable")
            .finish_non_exhaustive()
    }
}

impl StagedManagedProfile {
    pub fn id(&self) -> &str {
        &self.id
    }
}

/// Token returned only by the explicit confirmed-close release path.
pub struct ManagedProfileLeaseRelease {
    pub(super) id: String,
    pub(super) path: PathBuf,
}

impl fmt::Debug for ManagedProfileLeaseRelease {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ManagedProfileLeaseRelease")
            .field("id", &self.id)
            .field("path", &"<redacted>")
            .finish()
    }
}

impl ManagedProfileLease {
    /// Releases this profile lease after the caller has confirmed its browser
    /// process closed. The returned token is required to publish or discard a
    /// staged profile.
    pub fn release_after_confirmed_browser_close(self) -> ManagedProfileLeaseRelease {
        let release = ManagedProfileLeaseRelease {
            id: self.id.clone(),
            path: self.path.clone(),
        };
        drop(self);
        release
    }
}

#[allow(
    clippy::needless_pass_by_value,
    reason = "the provider error is intentionally reduced to a secret-safe kind"
)]
fn staging_io_error(
    operation: ManagedProfileStagingOperation,
    disposition: ManagedProfileStagingDisposition,
    error: io::Error,
) -> ManagedProfileStagingError {
    ManagedProfileStagingError::new(
        ManagedProfileStagingErrorKind::Io {
            operation,
            io_kind: error.kind(),
        },
        disposition,
    )
}

const fn staging_publication_failure_context(
    kind: &ManagedProfileStagingErrorKind,
) -> (ManagedProfileStagingOperation, Option<io::ErrorKind>) {
    match kind {
        ManagedProfileStagingErrorKind::ManifestSerializationFailed => {
            (ManagedProfileStagingOperation::SerializeManifest, None)
        }
        ManagedProfileStagingErrorKind::Io {
            operation:
                operation @ (ManagedProfileStagingOperation::WriteManifestTemporary
                | ManagedProfileStagingOperation::ReplaceManifest),
            io_kind,
        } => (*operation, Some(*io_kind)),
        _ => (ManagedProfileStagingOperation::PublishDirectory, None),
    }
}

#[allow(
    clippy::needless_pass_by_value,
    reason = "the provider error is intentionally reduced to a secret-safe disposition"
)]
fn staging_lease_error(error: VoidCrawlError) -> ManagedProfileStagingError {
    match error {
        VoidCrawlError::ProfileBusy { .. } => ManagedProfileStagingError::new(
            ManagedProfileStagingErrorKind::LeaseStillActive,
            ManagedProfileStagingDisposition::RetainedUnavailable,
        ),
        _ => staging_io_error(
            ManagedProfileStagingOperation::AcquireLease,
            ManagedProfileStagingDisposition::RetainedUnavailable,
            io::Error::other("staged profile lease acquisition failed"),
        ),
    }
}
