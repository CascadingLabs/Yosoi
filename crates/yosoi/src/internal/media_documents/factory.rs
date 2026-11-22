use std::sync::Arc;

use super::{
    AudioDocument, BinaryDocument, FileDocument, FileDocumentError, FileLimits, FileMetadata,
    ImageDocument, VideoDocument,
    classify::{MediaKind, detected_kind},
    payload::MediaDocument,
};

/// Builds a media or binary document from bytes using the selected file size limit.
pub fn file_from_bytes(
    id: impl Into<String>,
    bytes: impl Into<Vec<u8>>,
    metadata: FileMetadata,
    limits: FileLimits,
) -> Result<FileDocument, FileDocumentError> {
    file_from_shared_bytes(id, Arc::new(bytes.into()), metadata, limits)
}

/// Creates a classified file value from a response-owned immutable shared payload.
pub fn file_from_shared_bytes(
    id: impl Into<String>,
    bytes: Arc<Vec<u8>>,
    metadata: FileMetadata,
    limits: FileLimits,
) -> Result<FileDocument, FileDocumentError> {
    let kind = detected_kind(bytes.as_slice());
    let inner = MediaDocument::new(id, bytes, metadata, limits, None)?;
    Ok(match kind {
        MediaKind::Image => FileDocument::Image(ImageDocument { inner }),
        MediaKind::Video => FileDocument::Video(VideoDocument { inner }),
        MediaKind::Audio => FileDocument::Audio(AudioDocument { inner }),
        MediaKind::Binary => FileDocument::Binary(BinaryDocument { inner }),
    })
}
