use std::io::ErrorKind;
use std::path::{Path, PathBuf};

use tokio::fs::{self, OpenOptions};
use tokio::io::{AsyncReadExt as _, AsyncWriteExt as _};
use tokio::task;
use uuid::Uuid;
use yosoi_types::{ArtifactId, CaptureId};
use yosoi_web_capture::WebArtifactRef;

#[cfg(unix)]
use super::PRIVATE_FILE_MODE;
use super::directory::validate_private_file_permissions;
use super::publication::{PublishError, publish_and_sync};
use crate::{Archive, ArchiveError};

impl Archive {
    pub(crate) async fn write_capture_payload(
        &self,
        capture_id: CaptureId,
        artifact: WebArtifactRef,
        bytes: &[u8],
    ) -> Result<(), ArchiveError> {
        let artifact_id = artifact.as_untyped().artifact_id();
        let final_path = self.capture_payload_path(capture_id, artifact_id);
        let final_parent = self.ensure_capture_payload_directory(capture_id).await?;
        let staging_parent = self.format_root().join("staging");
        self.validate_owned_directory(&staging_parent).await?;
        let staging_path = staging_parent.join(format!("{}.payload.tmp", Uuid::new_v4()));
        let mut options = OpenOptions::new();
        options.create_new(true).write(true);
        #[cfg(unix)]
        options
            .mode(PRIVATE_FILE_MODE)
            .custom_flags(libc::O_NOFOLLOW);
        let mut staged = options.open(&staging_path).await.map_err(|source| {
            ArchiveError::io("create staged Capture payload", &staging_path, source)
        })?;
        if let Err(source) = staged.write_all(bytes).await {
            remove_staging_best_effort(&staging_path).await;
            return Err(ArchiveError::io(
                "write staged Capture payload",
                &staging_path,
                source,
            ));
        }
        if let Err(source) = staged.sync_all().await {
            drop(staged);
            remove_staging_best_effort(&staging_path).await;
            return Err(ArchiveError::io(
                "sync staged Capture payload",
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
            operation: "publish and sync immutable Capture payload",
            source,
        })?;

        match publication {
            Ok(()) => Ok(()),
            Err(PublishError::AlreadyExists) => {
                remove_staging_best_effort(&staging_path).await;
                let existing = self
                    .read_capture_payload(capture_id, artifact, bytes_len(bytes)?)
                    .await?;
                if existing == bytes {
                    Ok(())
                } else {
                    Err(ArchiveError::CapturePayloadConflict {
                        capture_id,
                        artifact_id,
                    })
                }
            }
            Err(PublishError::BeforeCommit(source)) => {
                remove_staging_best_effort(&staging_path).await;
                Err(ArchiveError::io(
                    "publish immutable Capture payload",
                    &final_path,
                    source,
                ))
            }
            Err(PublishError::CommitUncertain(source)) => {
                Err(ArchiveError::CapturePayloadCommitUncertain {
                    capture_id,
                    artifact_id,
                    source,
                })
            }
        }
    }

    pub(crate) async fn read_capture_payload(
        &self,
        capture_id: CaptureId,
        artifact: WebArtifactRef,
        expected: u64,
    ) -> Result<Vec<u8>, ArchiveError> {
        let artifact_id = artifact.as_untyped().artifact_id();
        let path = self.capture_payload_path(capture_id, artifact_id);
        let parent = path.parent().ok_or(ArchiveError::InvalidLayout {
            reason: "Capture payload path has no parent directory",
        })?;
        if let Err(error) = self.validate_owned_directory(parent).await {
            if super::is_not_found(&error) {
                return Err(ArchiveError::CapturePayloadMissing {
                    capture_id,
                    artifact_id,
                });
            }
            return Err(error);
        }
        read_payload_file(&path, capture_id, artifact, expected).await
    }

    async fn ensure_capture_payload_directory(
        &self,
        capture_id: CaptureId,
    ) -> Result<PathBuf, ArchiveError> {
        let captures = self.format_root().join("captures");
        self.ensure_owned_directory(&captures).await?;
        let shard = capture_id.to_string().chars().take(2).collect::<String>();
        let shard = captures.join(shard);
        self.ensure_owned_directory(&shard).await?;
        let capture = shard.join(capture_id.to_string());
        self.ensure_owned_directory(&capture).await?;
        let payloads = capture.join("payloads");
        self.ensure_owned_directory(&payloads).await?;
        Ok(payloads)
    }

    pub(crate) fn capture_payload_path(
        &self,
        capture_id: CaptureId,
        artifact_id: ArtifactId,
    ) -> PathBuf {
        let capture = capture_id.to_string();
        let shard = capture.chars().take(2).collect::<String>();
        self.format_root()
            .join("captures")
            .join(shard)
            .join(capture)
            .join("payloads")
            .join(format!("{}.bin", artifact_id.get()))
    }
}

async fn read_payload_file(
    path: &Path,
    capture_id: CaptureId,
    artifact: WebArtifactRef,
    expected: u64,
) -> Result<Vec<u8>, ArchiveError> {
    let artifact_id = artifact.as_untyped().artifact_id();
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    options.custom_flags(libc::O_NOFOLLOW);
    let file = match options.open(path).await {
        Ok(file) => file,
        Err(source) if source.kind() == ErrorKind::NotFound => {
            return Err(ArchiveError::CapturePayloadMissing {
                capture_id,
                artifact_id,
            });
        }
        Err(source) if source.raw_os_error() == Some(libc::ELOOP) => {
            return Err(ArchiveError::UnsafeArchivePath {
                path: path.to_path_buf(),
                reason: "Capture payload must not be a symbolic link",
            });
        }
        Err(source) => return Err(ArchiveError::io("open Capture payload", path, source)),
    };
    let metadata = file
        .metadata()
        .await
        .map_err(|source| ArchiveError::io("inspect Capture payload", path, source))?;
    if !metadata.is_file() {
        return Err(ArchiveError::NotRegularFile {
            path: path.to_path_buf(),
        });
    }
    validate_private_file_permissions(path, &metadata)?;
    if metadata.len() != expected {
        return Err(length_mismatch(artifact, expected, metadata.len()));
    }
    let capacity =
        usize::try_from(expected).map_err(|_| ArchiveError::CaptureMaterializationTooLarge {
            maximum: crate::MAX_CAPTURE_MATERIALIZED_BYTES,
            observed: expected,
        })?;
    let mut bytes = Vec::with_capacity(capacity);
    let mut bounded = file.take(expected.saturating_add(1));
    bounded
        .read_to_end(&mut bytes)
        .await
        .map_err(|source| ArchiveError::io("read Capture payload", path, source))?;
    let observed = bytes_len(&bytes)?;
    if observed != expected {
        return Err(length_mismatch(artifact, expected, observed));
    }
    Ok(bytes)
}

fn bytes_len(bytes: &[u8]) -> Result<u64, ArchiveError> {
    u64::try_from(bytes.len()).map_err(|_| ArchiveError::CaptureMaterializationTooLarge {
        maximum: crate::MAX_CAPTURE_MATERIALIZED_BYTES,
        observed: u64::MAX,
    })
}

const fn length_mismatch(artifact: WebArtifactRef, expected: u64, observed: u64) -> ArchiveError {
    ArchiveError::CapturePayloadLengthMismatch {
        artifact,
        expected,
        observed,
    }
}

async fn remove_staging_best_effort(path: &Path) {
    let _ = fs::remove_file(path).await;
}
