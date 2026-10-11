use std::{cell::Cell, fs, io};

use super::super::{
    ManagedProfile, ManagedProfileDescription, ManagedProfileLease, ProfileStatus,
    acquire_profile_lock, dir_size, path_entry_exists,
};
use super::{
    FilesystemStagingManifestPublisher, ManagedProfileLeaseRelease,
    ManagedProfileStagingDisposition, ManagedProfileStagingError, ManagedProfileStagingErrorKind,
    ManagedProfileStagingOperation, StagedManagedProfile, StagingManifestPublisher,
    staging_io_error, staging_lease_error, staging_publication_failure_context,
};

impl StagedManagedProfile {
    /// Acquires the exclusive profile lease used while Chromium warms this
    /// staged user-data directory. The profile remains absent from the registry.
    pub fn acquire_lease(&self) -> Result<ManagedProfileLease, ManagedProfileStagingError> {
        self.registry.with_staging_manifest(
            false,
            ManagedProfileStagingDisposition::RetainedUnavailable,
            |manifest| {
                if manifest.profiles.contains_key(&self.id) || !self.path.is_dir() {
                    return Err(ManagedProfileStagingError::new(
                        ManagedProfileStagingErrorKind::LeaseIdentityMismatch,
                        ManagedProfileStagingDisposition::RetainedUnavailable,
                    ));
                }
                acquire_profile_lock(&self.id, &self.path).map_err(staging_lease_error)
            },
        )
    }

    /// Makes the profile available only with the matching token produced after
    /// confirmed browser close and release of the staging lease.
    #[allow(
        clippy::needless_pass_by_value,
        reason = "the single-use release token is consumed to prevent replay"
    )]
    pub fn publish(
        self,
        release: ManagedProfileLeaseRelease,
    ) -> Result<ManagedProfileDescription, ManagedProfileStagingError> {
        self.publish_with_publisher(release, &FilesystemStagingManifestPublisher)
    }

    #[allow(
        clippy::needless_pass_by_value,
        reason = "the single-use release token is consumed to prevent replay"
    )]
    pub(super) fn publish_with_publisher(
        self,
        release: ManagedProfileLeaseRelease,
        publisher: &dyn StagingManifestPublisher,
    ) -> Result<ManagedProfileDescription, ManagedProfileStagingError> {
        if release.id != self.id || release.path != self.path {
            return Err(ManagedProfileStagingError::new(
                ManagedProfileStagingErrorKind::LeaseIdentityMismatch,
                ManagedProfileStagingDisposition::RetainedUnavailable,
            ));
        }

        let id = self.id.clone();
        let staged_path = self.path.clone();
        let profile_path = self.registry.profile_path(&id);
        let description = self.description.clone();
        let labels = self.labels.clone();
        let created_at = self.created_at;
        let directory_moved = Cell::new(false);
        let (profile, size, verification_lease) = self.registry.with_staging_manifest_recovering(
            true,
            ManagedProfileStagingDisposition::RetainedUnavailable,
            |manifest| {
                let destination_exists = path_entry_exists(&profile_path).map_err(|error| {
                    staging_io_error(
                        ManagedProfileStagingOperation::PublishDirectory,
                        ManagedProfileStagingDisposition::RetainedUnavailable,
                        error,
                    )
                })?;
                if manifest.profiles.contains_key(&id) || destination_exists {
                    return Err(ManagedProfileStagingError::new(
                        ManagedProfileStagingErrorKind::DuplicateProfileId,
                        ManagedProfileStagingDisposition::RetainedUnavailable,
                    ));
                }
                let verification_lease =
                    acquire_profile_lock(&id, &staged_path).map_err(staging_lease_error)?;
                let size = dir_size(&staged_path).map_err(|_| {
                    staging_io_error(
                        ManagedProfileStagingOperation::PublishDirectory,
                        ManagedProfileStagingDisposition::RetainedUnavailable,
                        io::Error::other("profile size could not be read"),
                    )
                })?;
                fs::rename(&staged_path, &profile_path).map_err(|error| {
                    staging_io_error(
                        ManagedProfileStagingOperation::PublishDirectory,
                        ManagedProfileStagingDisposition::RetainedUnavailable,
                        error,
                    )
                })?;
                directory_moved.set(true);
                let profile = ManagedProfile {
                    id: id.clone(),
                    path: profile_path.clone(),
                    created_at,
                    last_used_at: None,
                    labels: labels.clone(),
                    description: description.clone(),
                };
                manifest.profiles.insert(id.clone(), profile.clone());
                Ok((profile, size, verification_lease))
            },
            publisher,
            |mut error| {
                if !directory_moved.get() {
                    return error;
                }
                match publisher.restore_staged_directory(&profile_path, &staged_path) {
                    Ok(()) => {
                        error.disposition = ManagedProfileStagingDisposition::StagedUnavailable;
                        error
                    }
                    Err(rollback_error) => {
                        let (publication_operation, publication_io_kind) =
                            staging_publication_failure_context(&error.kind);
                        ManagedProfileStagingError::new(
                            ManagedProfileStagingErrorKind::PublicationRollbackFailed {
                                publication_operation,
                                publication_io_kind,
                                rollback_io_kind: rollback_error.kind(),
                            },
                            ManagedProfileStagingDisposition::RetainedUnavailable,
                        )
                    }
                }
            },
        )?;
        drop(verification_lease);
        Ok(ManagedProfileDescription {
            profile,
            size,
            status: ProfileStatus::Available,
        })
    }

    /// Removes a staged profile only after the matching browser-close token is
    /// supplied and the directory can be exclusively leased for cleanup.
    #[allow(
        clippy::needless_pass_by_value,
        reason = "the single-use release token is consumed to prevent replay"
    )]
    pub fn discard(
        self,
        release: ManagedProfileLeaseRelease,
    ) -> Result<ManagedProfileStagingDisposition, ManagedProfileStagingError> {
        if release.id != self.id || release.path != self.path {
            return Err(ManagedProfileStagingError::new(
                ManagedProfileStagingErrorKind::LeaseIdentityMismatch,
                ManagedProfileStagingDisposition::RetainedUnavailable,
            ));
        }
        self.registry.with_staging_manifest(
            false,
            ManagedProfileStagingDisposition::RetainedUnavailable,
            |manifest| {
                if manifest.profiles.contains_key(&self.id) {
                    return Err(ManagedProfileStagingError::new(
                        ManagedProfileStagingErrorKind::LeaseIdentityMismatch,
                        ManagedProfileStagingDisposition::RetainedUnavailable,
                    ));
                }
                let verification_lease =
                    acquire_profile_lock(&self.id, &self.path).map_err(staging_lease_error)?;
                drop(verification_lease);
                fs::remove_dir_all(&self.path).map_err(|error| {
                    staging_io_error(
                        ManagedProfileStagingOperation::RemoveStagingDirectory,
                        ManagedProfileStagingDisposition::RetainedUnavailable,
                        error,
                    )
                })?;
                Ok(ManagedProfileStagingDisposition::Discarded)
            },
        )
    }
}
