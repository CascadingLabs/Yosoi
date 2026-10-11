use std::env;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};

use serde::{Serialize, de::DeserializeOwned};
use tokio::fs::{self, OpenOptions};
use tokio::io::{AsyncReadExt as _, AsyncWriteExt as _};
use tokio::task;
use uuid::Uuid;

use self::directory::{
    ensure_private_directory, ensure_root_directory, validate_private_directory,
    validate_private_file_permissions,
};
use self::publication::{PublishError, publish_and_sync};
use crate::internal::archive::refs::RecordKey;
use crate::internal::archive::wire::{MAX_RECORD_BYTES, RecordKind, decode_record, encode_record};
use crate::internal::archive::{Archive, ArchiveError};

mod directory;
mod document_payload;
mod payload;
mod publication;
#[cfg(test)]
mod tests;

const MAX_RECORD_READ_BYTES: u64 = 16_777_217;
#[cfg(unix)]
const PRIVATE_FILE_MODE: u32 = 0o600;

#[cfg(not(unix))]
pub async fn open(_root: &Path) -> Result<Archive, ArchiveError> {
    Err(ArchiveError::UnsupportedPlatform {
        platform: env::consts::OS,
    })
}

#[cfg(unix)]
pub async fn open(root: &Path) -> Result<Archive, ArchiveError> {
    if root.as_os_str().is_empty() {
        return Err(ArchiveError::EmptyRoot);
    }
    let root = if root.is_absolute() {
        root.to_path_buf()
    } else {
        env::current_dir()
            .map_err(|source| ArchiveError::io("resolve current directory", root, source))?
            .join(root)
    };
    ensure_root_directory(&root).await?;
    let root = fs::canonicalize(&root)
        .await
        .map_err(|source| ArchiveError::io("canonicalize Archive root", &root, source))?;
    let archive = Archive { root };

    archive
        .ensure_owned_directory(&archive.root.join("archive"))
        .await?;
    archive
        .ensure_owned_directory(&archive.format_root())
        .await?;
    archive
        .ensure_owned_directory(&archive.format_root().join("records"))
        .await?;
    archive
        .ensure_owned_directory(&archive.format_root().join("staging"))
        .await?;
    archive
        .ensure_owned_directory(&archive.format_root().join("records/policy"))
        .await?;
    Ok(archive)
}

impl Archive {
    pub(in crate::internal::archive) async fn write_record<T>(
        &self,
        kind: RecordKind,
        schema_version: u32,
        key: &RecordKey,
        value: &T,
    ) -> Result<(), ArchiveError>
    where
        T: DeserializeOwned + PartialEq + Serialize + Sync,
    {
        let bytes = encode_record(kind, schema_version, key, value)?;
        let observed = u64::try_from(bytes.len()).map_err(|_| ArchiveError::RecordTooLarge {
            maximum: MAX_RECORD_BYTES,
            observed: u64::MAX,
        })?;
        if observed > MAX_RECORD_BYTES {
            return Err(ArchiveError::RecordTooLarge {
                maximum: MAX_RECORD_BYTES,
                observed,
            });
        }

        let final_path = self.record_path(kind, key);
        let kind_parent = self.format_root().join("records").join(kind.directory());
        self.ensure_owned_directory(&kind_parent).await?;
        let final_parent = final_path.parent().ok_or(ArchiveError::InvalidLayout {
            reason: "record path has no parent directory",
        })?;
        self.ensure_owned_directory(final_parent).await?;

        let staging_parent = self.format_root().join("staging");
        self.validate_owned_directory(&staging_parent).await?;
        let staging_path = staging_parent.join(format!("{}.json.tmp", Uuid::new_v4()));
        let mut options = OpenOptions::new();
        options.create_new(true).write(true);
        #[cfg(unix)]
        options
            .mode(PRIVATE_FILE_MODE)
            .custom_flags(libc::O_NOFOLLOW);
        let mut staged = options
            .open(&staging_path)
            .await
            .map_err(|source| ArchiveError::io("create staged record", &staging_path, source))?;
        staged
            .write_all(&bytes)
            .await
            .map_err(|source| ArchiveError::io("write staged record", &staging_path, source))?;
        staged
            .sync_all()
            .await
            .map_err(|source| ArchiveError::io("sync staged record", &staging_path, source))?;
        drop(staged);

        let staged_for_task = staging_path.clone();
        let final_for_task = final_path.clone();
        let final_parent_for_task = final_parent.to_path_buf();
        let staging_parent_for_task = staging_parent.clone();
        let publication = task::spawn_blocking(move || {
            publish_and_sync(
                &staged_for_task,
                &final_for_task,
                &final_parent_for_task,
                &staging_parent_for_task,
            )
        })
        .await
        .map_err(|source| ArchiveError::FilesystemTask {
            operation: "publish and sync immutable record",
            source,
        })?;

        match publication {
            Ok(()) => Ok(()),
            Err(PublishError::AlreadyExists) => {
                remove_staging_best_effort(&staging_path).await;
                let existing = self.read_record::<T>(kind, schema_version, key).await?;
                if &existing == value {
                    Ok(())
                } else {
                    Err(ArchiveError::IdentityConflict {
                        kind: kind.as_str(),
                        key: key.to_string(),
                    })
                }
            }
            Err(PublishError::BeforeCommit(source)) => {
                remove_staging_best_effort(&staging_path).await;
                Err(ArchiveError::io(
                    "publish immutable record",
                    &final_path,
                    source,
                ))
            }
            Err(PublishError::CommitUncertain(source)) => Err(ArchiveError::CommitUncertain {
                kind: kind.as_str(),
                key: key.to_string(),
                source,
            }),
        }
    }

    pub(in crate::internal::archive) async fn read_record<T>(
        &self,
        kind: RecordKind,
        schema_version: u32,
        key: &RecordKey,
    ) -> Result<T, ArchiveError>
    where
        T: DeserializeOwned,
    {
        let path = self.record_path(kind, key);
        let parent = path.parent().ok_or(ArchiveError::InvalidLayout {
            reason: "record path has no parent directory",
        })?;
        if let Err(error) = self.validate_owned_directory(parent).await {
            if is_not_found(&error) {
                return Err(ArchiveError::RecordNotFound {
                    kind: kind.as_str(),
                    key: key.to_string(),
                });
            }
            return Err(error);
        }

        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(unix)]
        options.custom_flags(libc::O_NOFOLLOW);
        let file = match options.open(&path).await {
            Ok(file) => file,
            Err(source) if source.kind() == ErrorKind::NotFound => {
                return Err(ArchiveError::RecordNotFound {
                    kind: kind.as_str(),
                    key: key.to_string(),
                });
            }
            #[cfg(unix)]
            Err(source) if source.raw_os_error() == Some(libc::ELOOP) => {
                return Err(ArchiveError::UnsafeArchivePath {
                    path,
                    reason: "record file must not be a symbolic link",
                });
            }
            Err(source) => return Err(ArchiveError::io("open record", &path, source)),
        };
        let metadata = file
            .metadata()
            .await
            .map_err(|source| ArchiveError::io("inspect opened record", &path, source))?;
        if !metadata.is_file() {
            return Err(ArchiveError::NotRegularFile { path });
        }
        validate_private_file_permissions(&path, &metadata)?;
        if metadata.len() > MAX_RECORD_BYTES {
            return Err(ArchiveError::RecordTooLarge {
                maximum: MAX_RECORD_BYTES,
                observed: metadata.len(),
            });
        }

        let mut bytes = Vec::new();
        let mut bounded = file.take(MAX_RECORD_READ_BYTES);
        bounded
            .read_to_end(&mut bytes)
            .await
            .map_err(|source| ArchiveError::io("read bounded record", &path, source))?;
        let observed = u64::try_from(bytes.len()).map_err(|_| ArchiveError::RecordTooLarge {
            maximum: MAX_RECORD_BYTES,
            observed: u64::MAX,
        })?;
        if observed > MAX_RECORD_BYTES {
            return Err(ArchiveError::RecordTooLarge {
                maximum: MAX_RECORD_BYTES,
                observed,
            });
        }
        decode_record(kind, schema_version, key, &bytes)
    }

    fn record_path(&self, kind: RecordKind, key: &RecordKey) -> PathBuf {
        self.format_root()
            .join("records")
            .join(kind.directory())
            .join(key.shard())
            .join(format!("{}.json", key.as_str()))
    }

    async fn ensure_owned_directory(&self, path: &Path) -> Result<(), ArchiveError> {
        if !path.starts_with(&self.root) {
            return Err(ArchiveError::UnsafeArchivePath {
                path: path.to_path_buf(),
                reason: "path escapes the selected Archive root",
            });
        }
        ensure_private_directory(path, false).await?;
        self.validate_owned_directory(path).await
    }

    async fn validate_owned_directory(&self, path: &Path) -> Result<(), ArchiveError> {
        validate_private_directory(path).await?;
        let canonical = fs::canonicalize(path)
            .await
            .map_err(|source| ArchiveError::io("canonicalize Archive directory", path, source))?;
        if !canonical.starts_with(&self.root) {
            return Err(ArchiveError::UnsafeArchivePath {
                path: path.to_path_buf(),
                reason: "directory resolves outside the selected Archive root",
            });
        }
        Ok(())
    }
}

async fn remove_staging_best_effort(path: &Path) {
    let _ = fs::remove_file(path).await;
}

fn is_not_found(error: &ArchiveError) -> bool {
    matches!(
        error,
        ArchiveError::Io { source, .. } if source.kind() == ErrorKind::NotFound
    )
}
