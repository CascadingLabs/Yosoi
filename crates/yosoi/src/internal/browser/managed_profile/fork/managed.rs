use std::{
    collections::BTreeSet,
    fs::{self, OpenOptions},
    result::Result as StdResult,
};

use super::super::copy::copy_snapshot_recursively_bounded;
use super::super::{
    ManagedProfile, ManagedProfileDescription, ManagedProfileLease, ProfileRegistry, ProfileStatus,
    is_valid_name, now_epoch_secs, path_entry_exists,
};
use super::{
    MAX_PROFILE_SPLIT_COPIES, ManagedProfileForkBatch, ManagedProfileForkError,
    ManagedProfileForkErrorKind, ManagedProfileForkOperation, close_staging_directory,
    fork_io_error, read_fork_manifest, remove_file_if_present, remove_uncommitted_children,
};

impl ProfileRegistry {
    /// Fork a leased managed profile into registered child profiles.
    ///
    /// The caller must already hold the source lease. This method borrows that
    /// lease for the whole operation and never attempts to reacquire its lock.
    /// Child directories are copied under a private staging directory, checked
    /// against the aggregate byte quota, and made visible in the manifest only
    /// after every copy has completed. The manifest lock prevents another
    /// registry client from leasing a child between the directory moves and
    /// the atomic manifest replacement.
    pub fn fork_managed_profile(
        &self,
        source_lease: &ManagedProfileLease,
        child_ids: &[String],
        aggregate_byte_quota: u64,
    ) -> StdResult<ManagedProfileForkBatch, ManagedProfileForkError> {
        if child_ids.is_empty() || child_ids.len() > MAX_PROFILE_SPLIT_COPIES {
            return Err(ManagedProfileForkError::new(
                ManagedProfileForkErrorKind::InvalidCopyCount {
                    requested: child_ids.len(),
                    max: MAX_PROFILE_SPLIT_COPIES,
                },
            ));
        }

        let mut unique_ids = BTreeSet::new();
        for (child_index, child_id) in child_ids.iter().enumerate() {
            if !is_valid_name(child_id) {
                let mut error =
                    ManagedProfileForkError::new(ManagedProfileForkErrorKind::InvalidChildId {
                        child_index,
                    });
                error.facts.child_index = Some(child_index);
                return Err(error);
            }
            if !unique_ids.insert(child_id) {
                let mut error =
                    ManagedProfileForkError::new(ManagedProfileForkErrorKind::DuplicateChildId {
                        child_index,
                    });
                error.facts.child_index = Some(child_index);
                return Err(error);
            }
        }

        fs::create_dir_all(&self.root).map_err(|error| {
            ManagedProfileForkError::new(ManagedProfileForkErrorKind::Io {
                operation: ManagedProfileForkOperation::CreateRegistryRoot,
                child_index: None,
                io_kind: error.kind(),
            })
        })?;

        let lock_path = self.root.join(".manifest.lock");
        let manifest_lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)
            .map_err(|error| {
                ManagedProfileForkError::new(ManagedProfileForkErrorKind::Io {
                    operation: ManagedProfileForkOperation::OpenManifestLock,
                    child_index: None,
                    io_kind: error.kind(),
                })
            })?;
        manifest_lock.lock().map_err(|error| {
            ManagedProfileForkError::new(ManagedProfileForkErrorKind::Io {
                operation: ManagedProfileForkOperation::LockManifest,
                child_index: None,
                io_kind: error.kind(),
            })
        })?;

        let manifest_path = self.manifest_path();
        let mut manifest = read_fork_manifest(&manifest_path)?;
        let Some(source) = manifest.profiles.get(source_lease.id()).cloned() else {
            return Err(ManagedProfileForkError::new(
                ManagedProfileForkErrorKind::LeaseNotRegistered,
            ));
        };
        if source.id != source_lease.id() || source.path != source_lease.path() {
            return Err(ManagedProfileForkError::new(
                ManagedProfileForkErrorKind::LeaseNotRegistered,
            ));
        }
        if !source.path.is_dir() {
            return Err(ManagedProfileForkError::new(
                ManagedProfileForkErrorKind::SourceMissing,
            ));
        }

        let mut child_paths = Vec::with_capacity(child_ids.len());
        for (child_index, child_id) in child_ids.iter().enumerate() {
            let child_path = self.profile_path(child_id);
            if manifest.profiles.contains_key(child_id)
                || path_entry_exists(&child_path).map_err(|error| {
                    fork_io_error(
                        ManagedProfileForkOperation::ReadDestinationMetadata,
                        Some(child_index),
                        error,
                    )
                })?
            {
                let mut error =
                    ManagedProfileForkError::new(ManagedProfileForkErrorKind::ChildAlreadyExists {
                        child_index,
                    });
                error.facts.child_index = Some(child_index);
                return Err(error);
            }
            child_paths.push(child_path);
        }

        let staging = tempfile::Builder::new()
            .prefix(".managed-profile-fork-")
            .tempdir_in(&self.root)
            .map_err(|error| {
                fork_io_error(ManagedProfileForkOperation::CreateStagingRoot, None, error)
            })?;
        let staging_root = staging.path().to_path_buf();
        let mut copied_bytes = 0_u64;
        let mut child_byte_counts = Vec::with_capacity(child_ids.len());

        for child_index in 0..child_ids.len() {
            let staged_child = staging_root.join(format!("child-{child_index}"));
            match copy_snapshot_recursively_bounded(
                &source.path,
                &staged_child,
                child_index,
                aggregate_byte_quota,
                &mut copied_bytes,
            ) {
                Ok(child_bytes) => child_byte_counts.push(child_bytes),
                Err(mut error) => {
                    error.facts.child_index = Some(child_index);
                    error.facts.copied_bytes = copied_bytes;
                    error.facts.cleanup_succeeded =
                        close_staging_directory(staging, &staging_root).0;
                    return Err(error);
                }
            }
        }

        let mut moved_child_paths = Vec::with_capacity(child_paths.len());
        for (child_index, child_path) in child_paths.iter().enumerate() {
            let staged_child = staging_root.join(format!("child-{child_index}"));
            let destination_exists = match path_entry_exists(child_path) {
                Ok(exists) => exists,
                Err(io_error) => {
                    let moved_cleanup_succeeded = remove_uncommitted_children(&moved_child_paths);
                    let stage_cleanup_succeeded = close_staging_directory(staging, &staging_root).0;
                    let mut error = fork_io_error(
                        ManagedProfileForkOperation::ReadDestinationMetadata,
                        Some(child_index),
                        io_error,
                    );
                    error.facts.child_index = Some(child_index);
                    error.facts.copied_bytes = copied_bytes;
                    error.facts.cleanup_succeeded =
                        moved_cleanup_succeeded && stage_cleanup_succeeded;
                    return Err(error);
                }
            };
            if destination_exists {
                let moved_cleanup_succeeded = remove_uncommitted_children(&moved_child_paths);
                let mut error =
                    ManagedProfileForkError::new(ManagedProfileForkErrorKind::ChildAlreadyExists {
                        child_index,
                    });
                error.facts.child_index = Some(child_index);
                error.facts.copied_bytes = copied_bytes;
                let stage_cleanup_succeeded = close_staging_directory(staging, &staging_root).0;
                error.facts.cleanup_succeeded = moved_cleanup_succeeded && stage_cleanup_succeeded;
                return Err(error);
            }
            if let Err(io_error) = fs::rename(&staged_child, child_path) {
                let removed = remove_uncommitted_children(&moved_child_paths);
                let stage_cleanup_succeeded = close_staging_directory(staging, &staging_root).0;
                let mut error = fork_io_error(
                    ManagedProfileForkOperation::MoveChildIntoPlace,
                    Some(child_index),
                    io_error,
                );
                error.facts.child_index = Some(child_index);
                error.facts.copied_bytes = copied_bytes;
                error.facts.cleanup_succeeded = removed && stage_cleanup_succeeded;
                return Err(error);
            }
            moved_child_paths.push(child_path.clone());
        }

        let (staging_cleanup_succeeded, staging_error_kind) =
            close_staging_directory(staging, &staging_root);
        if let Some(io_kind) = staging_error_kind {
            let removed = remove_uncommitted_children(&moved_child_paths);
            let mut error = ManagedProfileForkError::new(ManagedProfileForkErrorKind::Io {
                operation: ManagedProfileForkOperation::RemoveStagingRoot,
                child_index: None,
                io_kind,
            });
            error.facts.copied_bytes = copied_bytes;
            error.facts.cleanup_succeeded = removed && staging_cleanup_succeeded;
            return Err(error);
        }

        let mut children = Vec::with_capacity(child_ids.len());
        for ((child_id, child_path), size) in child_ids
            .iter()
            .zip(child_paths.iter())
            .zip(child_byte_counts.iter())
        {
            let child = ManagedProfile {
                id: child_id.clone(),
                path: child_path.clone(),
                created_at: now_epoch_secs(),
                last_used_at: None,
                labels: source.labels.clone(),
                description: source.description.clone(),
            };
            children.push(ManagedProfileDescription {
                profile: child,
                size: *size,
                status: ProfileStatus::Available,
            });
        }
        for child in &children {
            manifest
                .profiles
                .insert(child.profile.id.clone(), child.profile.clone());
        }

        let Ok(serialized_manifest) = serde_json::to_string_pretty(&manifest) else {
            let removed = remove_uncommitted_children(&moved_child_paths);
            let mut error = ManagedProfileForkError::new(
                ManagedProfileForkErrorKind::ManifestSerializationFailed,
            );
            error.facts.copied_bytes = copied_bytes;
            error.facts.cleanup_succeeded = removed;
            return Err(error);
        };
        let temporary_manifest_path = manifest_path.with_extension("json.tmp");
        if let Err(io_error) = fs::write(&temporary_manifest_path, serialized_manifest) {
            let temp_removed = remove_file_if_present(&temporary_manifest_path);
            let children_removed = remove_uncommitted_children(&moved_child_paths);
            let mut error = fork_io_error(
                ManagedProfileForkOperation::WriteManifestTemporary,
                None,
                io_error,
            );
            error.facts.copied_bytes = copied_bytes;
            error.facts.cleanup_succeeded = temp_removed && children_removed;
            return Err(error);
        }
        if let Err(io_error) = fs::rename(&temporary_manifest_path, &manifest_path) {
            let temp_removed = remove_file_if_present(&temporary_manifest_path);
            let children_removed = remove_uncommitted_children(&moved_child_paths);
            let mut error =
                fork_io_error(ManagedProfileForkOperation::ReplaceManifest, None, io_error);
            error.facts.copied_bytes = copied_bytes;
            error.facts.cleanup_succeeded = temp_removed && children_removed;
            return Err(error);
        }

        Ok(ManagedProfileForkBatch {
            source_id: source.id,
            children,
            copied_bytes,
        })
    }
}
