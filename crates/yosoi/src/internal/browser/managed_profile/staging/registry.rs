use std::{
    convert::identity,
    fs::{self, OpenOptions},
    io,
};

use super::super::{
    Manifest, ProfileRegistry, STAGING_DIRECTORY, is_valid_name, now_epoch_secs, path_entry_exists,
    seed_standalone_profile,
};
use super::{
    FilesystemStagingManifestPublisher, ManagedProfileStagingDisposition,
    ManagedProfileStagingError, ManagedProfileStagingErrorKind, ManagedProfileStagingOperation,
    StagedManagedProfile, StagingManifestPublisher, staging_io_error,
};

impl ProfileRegistry {
    /// Reserves an identifier and seeds a profile below the private staging
    /// root without adding it to the leasable registry manifest.
    pub fn stage_profile(
        &self,
        id: &str,
        description: Option<String>,
        labels: Vec<String>,
    ) -> Result<StagedManagedProfile, ManagedProfileStagingError> {
        if !is_valid_name(id) {
            return Err(ManagedProfileStagingError::new(
                ManagedProfileStagingErrorKind::InvalidProfileId,
                ManagedProfileStagingDisposition::NotCreated,
            ));
        }
        let id = id.to_owned();
        let staged_path = self.staged_profile_path(&id);
        let profile_path = self.profile_path(&id);
        let registry = self.clone();
        self.with_staging_manifest(
            false,
            ManagedProfileStagingDisposition::NotCreated,
            move |manifest| {
                let final_exists = path_entry_exists(&profile_path).map_err(|error| {
                    staging_io_error(
                        ManagedProfileStagingOperation::ReserveProfileId,
                        ManagedProfileStagingDisposition::NotCreated,
                        error,
                    )
                })?;
                let staged_exists = path_entry_exists(&staged_path).map_err(|error| {
                    staging_io_error(
                        ManagedProfileStagingOperation::ReserveProfileId,
                        ManagedProfileStagingDisposition::NotCreated,
                        error,
                    )
                })?;
                if manifest.profiles.contains_key(&id) || final_exists || staged_exists {
                    return Err(ManagedProfileStagingError::new(
                        ManagedProfileStagingErrorKind::DuplicateProfileId,
                        ManagedProfileStagingDisposition::NotCreated,
                    ));
                }
                fs::create_dir_all(registry.staging_root()).map_err(|error| {
                    staging_io_error(
                        ManagedProfileStagingOperation::CreateStagingRoot,
                        ManagedProfileStagingDisposition::NotCreated,
                        error,
                    )
                })?;
                fs::create_dir(&staged_path).map_err(|error| {
                    if error.kind() == io::ErrorKind::AlreadyExists {
                        ManagedProfileStagingError::new(
                            ManagedProfileStagingErrorKind::DuplicateProfileId,
                            ManagedProfileStagingDisposition::NotCreated,
                        )
                    } else {
                        staging_io_error(
                            ManagedProfileStagingOperation::ReserveProfileId,
                            ManagedProfileStagingDisposition::NotCreated,
                            error,
                        )
                    }
                })?;
                if seed_standalone_profile(&staged_path).is_err() {
                    let cleanup = fs::remove_dir_all(&staged_path).is_ok();
                    return Err(staging_io_error(
                        ManagedProfileStagingOperation::SeedProfile,
                        if cleanup {
                            ManagedProfileStagingDisposition::NotCreated
                        } else {
                            ManagedProfileStagingDisposition::RetainedUnavailable
                        },
                        io::Error::other("profile seed failed"),
                    ));
                }
                Ok(StagedManagedProfile {
                    registry,
                    id,
                    path: staged_path,
                    description,
                    labels,
                    created_at: now_epoch_secs(),
                })
            },
        )
    }

    /// Lists hidden, unregistered staging identifiers for later lifecycle
    /// classification. It never reports them as available profiles.
    pub fn list_staged_profiles(&self) -> Result<Vec<String>, ManagedProfileStagingError> {
        self.with_staging_manifest(
            false,
            ManagedProfileStagingDisposition::RetainedUnavailable,
            |_| {
                let root = self.staging_root();
                let entries = match fs::read_dir(&root) {
                    Ok(entries) => entries,
                    Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Vec::new()),
                    Err(error) => {
                        return Err(staging_io_error(
                            ManagedProfileStagingOperation::ReadManifest,
                            ManagedProfileStagingDisposition::RetainedUnavailable,
                            error,
                        ));
                    }
                };
                let mut ids = Vec::new();
                for entry in entries {
                    let entry = entry.map_err(|error| {
                        staging_io_error(
                            ManagedProfileStagingOperation::ReadManifest,
                            ManagedProfileStagingDisposition::RetainedUnavailable,
                            error,
                        )
                    })?;
                    if !entry
                        .file_type()
                        .map_err(|error| {
                            staging_io_error(
                                ManagedProfileStagingOperation::ReadManifest,
                                ManagedProfileStagingDisposition::RetainedUnavailable,
                                error,
                            )
                        })?
                        .is_dir()
                    {
                        continue;
                    }
                    let id = entry.file_name().to_string_lossy().into_owned();
                    if is_valid_name(&id) {
                        ids.push(id);
                    }
                }
                ids.sort();
                Ok(ids)
            },
        )
    }

    /// Lists final profile directories that are absent from the registry
    /// manifest. These directories remain unavailable until reconciliation
    /// explicitly resolves them.
    pub fn list_unregistered_profiles(&self) -> Result<Vec<String>, ManagedProfileStagingError> {
        self.with_staging_manifest(
            false,
            ManagedProfileStagingDisposition::RetainedUnavailable,
            |manifest| {
                let entries = fs::read_dir(&self.root).map_err(|error| {
                    staging_io_error(
                        ManagedProfileStagingOperation::ListUnregisteredFinalDirectories,
                        ManagedProfileStagingDisposition::RetainedUnavailable,
                        error,
                    )
                })?;
                let mut ids = Vec::new();
                for entry in entries {
                    let entry = entry.map_err(|error| {
                        staging_io_error(
                            ManagedProfileStagingOperation::ListUnregisteredFinalDirectories,
                            ManagedProfileStagingDisposition::RetainedUnavailable,
                            error,
                        )
                    })?;
                    if !entry
                        .file_type()
                        .map_err(|error| {
                            staging_io_error(
                                ManagedProfileStagingOperation::ListUnregisteredFinalDirectories,
                                ManagedProfileStagingDisposition::RetainedUnavailable,
                                error,
                            )
                        })?
                        .is_dir()
                    {
                        continue;
                    }
                    let id = entry.file_name().to_string_lossy().into_owned();
                    if is_valid_name(&id)
                        && !manifest.profiles.contains_key(&id)
                        && !is_reserved_internal_directory_name(&id)
                    {
                        ids.push(id);
                    }
                }
                ids.sort();
                Ok(ids)
            },
        )
    }

    pub(super) fn with_staging_manifest<T>(
        &self,
        write_manifest: bool,
        failure_disposition: ManagedProfileStagingDisposition,
        action: impl FnOnce(&mut Manifest) -> Result<T, ManagedProfileStagingError>,
    ) -> Result<T, ManagedProfileStagingError> {
        self.with_staging_manifest_recovering(
            write_manifest,
            failure_disposition,
            action,
            &FilesystemStagingManifestPublisher,
            identity,
        )
    }

    pub(super) fn with_staging_manifest_recovering<T>(
        &self,
        write_manifest: bool,
        failure_disposition: ManagedProfileStagingDisposition,
        action: impl FnOnce(&mut Manifest) -> Result<T, ManagedProfileStagingError>,
        publisher: &dyn StagingManifestPublisher,
        recover_publication_failure: impl FnOnce(
            ManagedProfileStagingError,
        ) -> ManagedProfileStagingError,
    ) -> Result<T, ManagedProfileStagingError> {
        fs::create_dir_all(&self.root).map_err(|error| {
            staging_io_error(
                ManagedProfileStagingOperation::CreateRegistryRoot,
                failure_disposition,
                error,
            )
        })?;
        let lock_path = self.root.join(".manifest.lock");
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)
            .map_err(|error| {
                staging_io_error(
                    ManagedProfileStagingOperation::OpenManifestLock,
                    failure_disposition,
                    error,
                )
            })?;
        lock.lock().map_err(|error| {
            staging_io_error(
                ManagedProfileStagingOperation::LockManifest,
                failure_disposition,
                error,
            )
        })?;

        let manifest_path = self.manifest_path();
        let mut manifest = match fs::read_to_string(&manifest_path) {
            Ok(raw) => serde_json::from_str(&raw).map_err(|_| {
                ManagedProfileStagingError::new(
                    ManagedProfileStagingErrorKind::InvalidManifest,
                    failure_disposition,
                )
            })?,
            Err(error) if error.kind() == io::ErrorKind::NotFound => Manifest::default(),
            Err(error) => {
                return Err(staging_io_error(
                    ManagedProfileStagingOperation::ReadManifest,
                    failure_disposition,
                    error,
                ));
            }
        };
        let result = action(&mut manifest)?;
        if write_manifest {
            let commit_result = (|| {
                let serialized = serde_json::to_string_pretty(&manifest).map_err(|_| {
                    ManagedProfileStagingError::new(
                        ManagedProfileStagingErrorKind::ManifestSerializationFailed,
                        ManagedProfileStagingDisposition::RetainedUnavailable,
                    )
                })?;
                let temporary_path = manifest_path.with_extension("json.tmp");
                publisher
                    .write_temporary_manifest(&temporary_path, &serialized)
                    .map_err(|error| {
                        staging_io_error(
                            ManagedProfileStagingOperation::WriteManifestTemporary,
                            ManagedProfileStagingDisposition::RetainedUnavailable,
                            error,
                        )
                    })?;
                publisher
                    .replace_manifest(&temporary_path, &manifest_path)
                    .map_err(|error| {
                        staging_io_error(
                            ManagedProfileStagingOperation::ReplaceManifest,
                            ManagedProfileStagingDisposition::RetainedUnavailable,
                            error,
                        )
                    })
            })();
            if let Err(error) = commit_result {
                return Err(recover_publication_failure(error));
            }
        }
        Ok(result)
    }
}

fn is_reserved_internal_directory_name(name: &str) -> bool {
    name == STAGING_DIRECTORY
        || name == ".yosoi"
        || name == ".snapshots"
        || name.starts_with(".managed-profile-fork-")
}
