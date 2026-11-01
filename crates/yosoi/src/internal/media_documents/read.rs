use std::path::Path;

use tokio::{fs::File, io::AsyncReadExt as _};

use super::{FileDocument, FileDocumentError, FileLimits, FileMetadata, factory::file_from_bytes};

/// Reads a regular file asynchronously with a hard-bounded `limit + 1` byte read.
///
/// Only the basename is retained as filename provenance; the full local path is
/// not copied into metadata. The bytes remain opaque and are not decoded.
pub async fn read_file(
    id: impl Into<String>,
    path: impl AsRef<Path>,
    limits: FileLimits,
) -> Result<FileDocument, FileDocumentError> {
    limits.validate()?;
    let path = path.as_ref();
    let file = File::open(path)
        .await
        .map_err(|source| FileDocumentError::Io {
            path: path.to_path_buf(),
            source,
        })?;
    let file_metadata = file
        .metadata()
        .await
        .map_err(|source| FileDocumentError::Io {
            path: path.to_path_buf(),
            source,
        })?;
    if !file_metadata.is_file() {
        return Err(FileDocumentError::NotRegularFile(path.to_path_buf()));
    }
    if file_metadata.len() > limits.max_bytes {
        return Err(FileDocumentError::TooLarge {
            maximum: limits.max_bytes,
            observed: file_metadata.len(),
        });
    }
    let read_limit =
        limits
            .max_bytes
            .checked_add(1)
            .ok_or(FileDocumentError::LimitExceedsHardMaximum {
                configured: limits.max_bytes,
                maximum: super::MAX_FILE_BYTES,
            })?;
    let mut bytes = Vec::new();
    file.take(read_limit)
        .read_to_end(&mut bytes)
        .await
        .map_err(|source| FileDocumentError::Io {
            path: path.to_path_buf(),
            source,
        })?;
    let observed = u64::try_from(bytes.len()).map_err(|_| FileDocumentError::TooLarge {
        maximum: limits.max_bytes,
        observed: u64::MAX,
    })?;
    if observed > limits.max_bytes {
        return Err(FileDocumentError::TooLarge {
            maximum: limits.max_bytes,
            observed,
        });
    }
    let mut metadata = FileMetadata::new();
    if let Some(filename) = path.file_name().and_then(|name| name.to_str()) {
        metadata = metadata.with_filename(filename)?;
    }
    file_from_bytes(id, bytes, metadata, limits)
}
