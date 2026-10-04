#![cfg(test)]
#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use std::{fs, io, path::Path};

use crate::error::VoidCrawlError;

use super::super::{ProfileRegistry, STAGING_DIRECTORY};
use super::{
    ManagedProfileLeaseRelease, ManagedProfileStagingDisposition, ManagedProfileStagingErrorKind,
    ManagedProfileStagingOperation, StagedManagedProfile, StagingManifestPublisher,
};

#[derive(Clone, Copy)]
enum ManifestFailure {
    Write,
    Replace,
}

struct FaultingStagingManifestPublisher {
    manifest_failure: ManifestFailure,
    fail_rollback: bool,
}

impl StagingManifestPublisher for FaultingStagingManifestPublisher {
    fn write_temporary_manifest(&self, path: &Path, contents: &str) -> io::Result<()> {
        if matches!(self.manifest_failure, ManifestFailure::Write) {
            return Err(io::Error::other("injected manifest write failure"));
        }
        fs::write(path, contents)
    }

    fn replace_manifest(&self, temporary_path: &Path, manifest_path: &Path) -> io::Result<()> {
        if matches!(self.manifest_failure, ManifestFailure::Replace) {
            return Err(io::Error::other("injected manifest replace failure"));
        }
        fs::rename(temporary_path, manifest_path)
    }

    fn restore_staged_directory(
        &self,
        published_path: &Path,
        staged_path: &Path,
    ) -> io::Result<()> {
        if self.fail_rollback {
            return Err(io::Error::other("injected directory rollback failure"));
        }
        fs::rename(published_path, staged_path)
    }
}

fn staged_profile() -> (
    tempfile::TempDir,
    ProfileRegistry,
    StagedManagedProfile,
    ManagedProfileLeaseRelease,
) {
    let tempdir = tempfile::tempdir().expect("create temp directory");
    let registry = ProfileRegistry::new(tempdir.path());
    registry
        .create_profile("registered", None, vec![])
        .expect("create registered profile");
    let staged = registry
        .stage_profile("warming", None, vec![])
        .expect("create staged profile");
    let release = staged
        .acquire_lease()
        .expect("acquire staged profile lease")
        .release_after_confirmed_browser_close();
    (tempdir, registry, staged, release)
}

#[test]
fn unregistered_profile_inventory_ignores_internal_directories() {
    let tempdir = tempfile::tempdir().expect("create temp directory");
    let registry = ProfileRegistry::new(tempdir.path());
    for internal_directory in [
        STAGING_DIRECTORY,
        ".yosoi",
        ".snapshots",
        ".managed-profile-fork-active",
    ] {
        fs::create_dir(registry.root().join(internal_directory))
            .expect("create internal directory");
    }
    fs::create_dir(registry.root().join("orphan")).expect("create unregistered profile directory");

    assert_eq!(
        registry
            .list_unregistered_profiles()
            .expect("list unregistered profiles"),
        vec!["orphan"]
    );
}

#[test]
fn manifest_write_and_replace_failures_restore_private_staging() {
    for failure in [ManifestFailure::Write, ManifestFailure::Replace] {
        let (_tempdir, registry, staged, release) = staged_profile();
        let publisher = FaultingStagingManifestPublisher {
            manifest_failure: failure,
            fail_rollback: false,
        };

        let error = staged
            .publish_with_publisher(release, &publisher)
            .expect_err("injected manifest failure");

        assert!(matches!(
            error.kind,
            ManagedProfileStagingErrorKind::Io {
                operation: ManagedProfileStagingOperation::WriteManifestTemporary
                    | ManagedProfileStagingOperation::ReplaceManifest,
                io_kind: io::ErrorKind::Other,
            }
        ));
        assert_eq!(
            error.disposition,
            ManagedProfileStagingDisposition::StagedUnavailable
        );
        assert!(registry.root().join(".staging/warming").is_dir());
        assert!(!registry.root().join("warming").exists());
        assert_eq!(registry.list_profiles().expect("list profiles").len(), 1);
        assert_eq!(
            registry
                .list_staged_profiles()
                .expect("list staged profiles"),
            vec!["warming"]
        );
        assert!(
            registry
                .list_unregistered_profiles()
                .expect("list unregistered profiles")
                .is_empty()
        );
    }
}

#[test]
fn failed_directory_rollback_is_typed_and_inventory_visible_but_not_leasable() {
    let (_tempdir, registry, staged, release) = staged_profile();
    let publisher = FaultingStagingManifestPublisher {
        manifest_failure: ManifestFailure::Replace,
        fail_rollback: true,
    };

    let error = staged
        .publish_with_publisher(release, &publisher)
        .expect_err("injected replace and rollback failures");

    assert!(matches!(
        error.kind,
        ManagedProfileStagingErrorKind::PublicationRollbackFailed {
            publication_operation: ManagedProfileStagingOperation::ReplaceManifest,
            publication_io_kind: Some(io::ErrorKind::Other),
            rollback_io_kind: io::ErrorKind::Other,
        }
    ));
    assert_eq!(
        error.disposition,
        ManagedProfileStagingDisposition::RetainedUnavailable
    );
    assert!(!registry.root().join(".staging/warming").exists());
    assert!(registry.root().join("warming").is_dir());
    assert_eq!(registry.list_profiles().expect("list profiles").len(), 1);
    assert!(
        registry
            .list_staged_profiles()
            .expect("list staged profiles")
            .is_empty()
    );
    assert_eq!(
        registry
            .list_unregistered_profiles()
            .expect("list unregistered profiles"),
        vec!["warming"]
    );
    assert!(matches!(
        registry.acquire_profile("warming"),
        Err(VoidCrawlError::ProfileNotFound { .. })
    ));
}
