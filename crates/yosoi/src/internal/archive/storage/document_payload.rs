use std::io::ErrorKind;
use std::path::{Path, PathBuf};

use tokio::fs::{OpenOptions, remove_file};
use tokio::io::{AsyncReadExt as _, AsyncWriteExt as _};
use tokio::task;
use uuid::Uuid;

#[cfg(unix)]
use super::PRIVATE_FILE_MODE;
use super::directory::validate_private_file_permissions;
use super::publication::{PublishError, publish_and_sync};
use crate::internal::archive::refs::RecordKey;
use crate::internal::archive::{Archive, ArchiveError, MAX_ARCHIVED_DOCUMENT_BYTES};

impl Archive {
    pub(in crate::internal::archive) async fn write_document_payload(
        &self,
        key: &RecordKey,
        bytes: &[u8],
    ) -> Result<(), ArchiveError> {
        let final_parent = self.ensure_document_payload_directory(key).await?;
        let final_path = final_parent.join("payload.bin");
        let staging_parent = self.format_root().join("staging");
        self.validate_owned_directory(&staging_parent).await?;
        let staging_path = staging_parent.join(format!("{}.document.tmp", Uuid::new_v4()));
        let mut options = OpenOptions::new();
        options.create_new(true).write(true);
        #[cfg(unix)]
        options
            .mode(PRIVATE_FILE_MODE)
            .custom_flags(libc::O_NOFOLLOW);
        let mut staged = options.open(&staging_path).await.map_err(|source| {
            ArchiveError::io("create staged Document payload", &staging_path, source)
        })?;
        if let Err(source) = staged.write_all(bytes).await {
            drop(staged);
            remove_staging_best_effort(&staging_path).await;
            return Err(ArchiveError::io(
                "write staged Document payload",
                &staging_path,
                source,
            ));
        }
        if let Err(source) = staged.sync_all().await {
            drop(staged);
            remove_staging_best_effort(&staging_path).await;
            return Err(ArchiveError::io(
                "sync staged Document payload",
                &staging_path,
                source,
            ));
        }
        drop(staged);

        let staged_for_task = staging_path.clone();
        let final_for_task = final_path.clone();
        let final_parent_for_task = final_parent.clone();
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
            operation: "publish and sync immutable Document payload",
            source,
        })?;

        match publication {
            Ok(()) => Ok(()),
            Err(PublishError::AlreadyExists) => {
                remove_staging_best_effort(&staging_path).await;
                let expected = bytes_len(bytes)?;
                let existing = self.read_document_payload(key, expected).await?;
                if existing == bytes {
                    Ok(())
                } else {
                    Err(ArchiveError::DocumentPayloadConflict {
                        key: key.to_string(),
                    })
                }
            }
            Err(PublishError::BeforeCommit(source)) => {
                remove_staging_best_effort(&staging_path).await;
                Err(ArchiveError::io(
                    "publish immutable Document payload",
                    &final_path,
                    source,
                ))
            }
            Err(PublishError::CommitUncertain(source)) => {
                Err(ArchiveError::DocumentPayloadCommitUncertain {
                    key: key.to_string(),
                    source,
                })
            }
        }
    }

    pub(in crate::internal::archive) async fn read_document_payload(
        &self,
        key: &RecordKey,
        expected: u64,
    ) -> Result<Vec<u8>, ArchiveError> {
        let path = self.document_payload_path(key);
        let parent = path.parent().ok_or(ArchiveError::InvalidLayout {
            reason: "Document payload path has no parent directory",
        })?;
        if let Err(error) = self.validate_owned_directory(parent).await {
            if super::is_not_found(&error) {
                return Err(ArchiveError::DocumentPayloadMissing {
                    key: key.to_string(),
                });
            }
            return Err(error);
        }
        read_document_file(&path, key, expected).await
    }

    async fn ensure_document_payload_directory(
        &self,
        key: &RecordKey,
    ) -> Result<PathBuf, ArchiveError> {
        let documents = self.format_root().join("documents");
        self.ensure_owned_directory(&documents).await?;
        let shard = documents.join(key.shard());
        self.ensure_owned_directory(&shard).await?;
        let document = shard.join(key.as_str());
        self.ensure_owned_directory(&document).await?;
        Ok(document)
    }

    pub(in crate::internal::archive) fn document_payload_path(&self, key: &RecordKey) -> PathBuf {
        self.format_root()
            .join("documents")
            .join(key.shard())
            .join(key.as_str())
            .join("payload.bin")
    }
}

async fn read_document_file(
    path: &Path,
    key: &RecordKey,
    expected: u64,
) -> Result<Vec<u8>, ArchiveError> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    options.custom_flags(libc::O_NOFOLLOW);
    let file = match options.open(path).await {
        Ok(file) => file,
        Err(source) if source.kind() == ErrorKind::NotFound => {
            return Err(ArchiveError::DocumentPayloadMissing {
                key: key.to_string(),
            });
        }
        #[cfg(unix)]
        Err(source) if source.raw_os_error() == Some(libc::ELOOP) => {
            return Err(ArchiveError::UnsafeArchivePath {
                path: path.to_path_buf(),
                reason: "Document payload must not be a symbolic link",
            });
        }
        Err(source) => return Err(ArchiveError::io("open Document payload", path, source)),
    };
    let metadata = file
        .metadata()
        .await
        .map_err(|source| ArchiveError::io("inspect Document payload", path, source))?;
    if !metadata.is_file() {
        return Err(ArchiveError::NotRegularFile {
            path: path.to_path_buf(),
        });
    }
    validate_private_file_permissions(path, &metadata)?;
    if metadata.len() != expected {
        return Err(length_mismatch(key, expected, metadata.len()));
    }
    let capacity = usize::try_from(expected).map_err(|_| ArchiveError::DocumentTooLarge {
        maximum: MAX_ARCHIVED_DOCUMENT_BYTES,
        observed: expected,
    })?;
    let mut bytes = Vec::with_capacity(capacity);
    let mut bounded = file.take(expected.saturating_add(1));
    bounded
        .read_to_end(&mut bytes)
        .await
        .map_err(|source| ArchiveError::io("read Document payload", path, source))?;
    let observed = bytes_len(&bytes)?;
    if observed != expected {
        return Err(length_mismatch(key, expected, observed));
    }
    Ok(bytes)
}

fn bytes_len(bytes: &[u8]) -> Result<u64, ArchiveError> {
    u64::try_from(bytes.len()).map_err(|_| ArchiveError::DocumentTooLarge {
        maximum: MAX_ARCHIVED_DOCUMENT_BYTES,
        observed: u64::MAX,
    })
}

fn length_mismatch(key: &RecordKey, expected: u64, observed: u64) -> ArchiveError {
    ArchiveError::DocumentPayloadLengthMismatch {
        key: key.to_string(),
        expected,
        observed,
    }
}

async fn remove_staging_best_effort(path: &Path) {
    let _ = remove_file(path).await;
}
