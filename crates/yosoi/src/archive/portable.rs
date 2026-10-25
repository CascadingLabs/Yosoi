//! One bounded, immutable portable Surface outcome. No paths or executable authority.

use super::{Archive, ArchiveError};
use crate::surface::{Outcome, OutcomeRef};
use sha2::{Digest, Sha256};
use std::fmt::Display;
use std::{
    fs,
    io::{Read, Write},
    path::Path,
};
use tokio::task::spawn_blocking;
use uuid::Uuid;

const MAGIC: &[u8; 16] = b"YOSOI-SURFACE\0\0\x01";
const MAXIMUM: u64 = 256 * 1024 * 1024;

impl Archive {
    /// Exports one validated Surface outcome as a self-contained portable file.
    ///
    /// The file contains a version marker, SHA-256 and exact JSON payload. It
    /// includes retained sources and Plans, never the Archive directory or live
    /// authority. The destination must not exist. Publication is atomic through
    /// a same-directory hard link; filesystems without hard links return an error.
    /// A sync failure after publication reports an error with the file possibly
    /// present. Cancellation can leave a complete file, never a partial destination.
    pub async fn export_file(
        &self,
        reference: &OutcomeRef,
        path: impl AsRef<Path>,
    ) -> Result<(), ArchiveError> {
        let value = self.read(reference).await?;
        let bytes = serde_json::to_vec(&value).map_err(invalid)?;
        if u64::try_from(bytes.len()).map_err(invalid)? > MAXIMUM {
            return Err(invalid("portable payload exceeds 256 MiB"));
        }
        let path = path.as_ref().to_owned();
        spawn_blocking(move || {
            let parent = path
                .parent()
                .filter(|value| !value.as_os_str().is_empty())
                .unwrap_or_else(|| Path::new("."));
            let staging = parent.join(format!(".yosoi-export-{}", Uuid::new_v4()));
            let mut options = fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options.open(&staging).map_err(|error| {
                ArchiveError::io("create portable staging file", &staging, error)
            })?;
            let result = (|| {
                file.write_all(MAGIC)?;
                file.write_all(&Sha256::digest(&bytes))?;
                file.write_all(&bytes)?;
                file.sync_all()?;
                fs::hard_link(&staging, &path)?;
                fs::File::open(parent)?.sync_all()
            })();
            // Keep the original error if cleanup also fails. A successful export
            // must not leave owned staging files behind.
            let cleanup = fs::remove_file(&staging);
            result.and(cleanup).map_err(|error| {
                ArchiveError::io(
                    "publish portable file (destination may exist after sync failure)",
                    &path,
                    error,
                )
            })
        })
        .await
        .map_err(|source| ArchiveError::FilesystemTask {
            operation: "export portable file",
            source,
        })?
    }

    /// Validates a portable file and imports its outcome through normal `write`.
    ///
    /// No original directory, source file, browser, decoder or network is used.
    /// Integrity is checked before JSON interpretation, and all outcome limits
    /// are checked before persistence. SHA-256 detects corruption; it does not
    /// authenticate the file's author. Import grants no action permission.
    pub async fn import_file(&self, path: impl AsRef<Path>) -> Result<OutcomeRef, ArchiveError> {
        let path = path.as_ref().to_owned();
        let value = spawn_blocking(move || {
            let mut file = fs::File::open(&path)
                .map_err(|error| ArchiveError::io("open portable file", &path, error))?;
            let metadata = file
                .metadata()
                .map_err(|error| ArchiveError::io("inspect portable file", &path, error))?;
            if !metadata.is_file() {
                return Err(ArchiveError::NotRegularFile { path });
            }
            if metadata.len() > MAXIMUM.saturating_add(48) {
                return Err(invalid("portable file exceeds 256 MiB payload limit"));
            }
            let mut magic = [0_u8; 16];
            let mut digest = [0_u8; 32];
            file.read_exact(&mut magic)
                .and_then(|()| file.read_exact(&mut digest))
                .map_err(|error| ArchiveError::io("read portable header", &path, error))?;
            if &magic != MAGIC {
                return Err(invalid("unsupported portable Surface format"));
            }
            let mut bytes = Vec::new();
            file.take(MAXIMUM.saturating_add(1))
                .read_to_end(&mut bytes)
                .map_err(|error| ArchiveError::io("read portable payload", &path, error))?;
            let observed_digest: [u8; 32] = Sha256::digest(&bytes).into();
            if u64::try_from(bytes.len()).map_err(invalid)? > MAXIMUM || observed_digest != digest {
                return Err(invalid("portable payload length or digest mismatch"));
            }
            let value: Outcome = serde_json::from_slice(&bytes).map_err(invalid)?;
            value.validate().map_err(invalid)?;
            Ok(value)
        })
        .await
        .map_err(|source| ArchiveError::FilesystemTask {
            operation: "import portable file",
            source,
        })??;
        self.write(&value).await
    }
}

fn invalid(error: impl Display) -> ArchiveError {
    ArchiveError::InvalidSurfaceOutcome(error.to_string())
}
