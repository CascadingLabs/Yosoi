use std::sync::Arc;

use crate::internal::documents::DocumentId;

use super::{
    FileDocumentError, FileLimits, FileMetadata, classify::MediaKind, payload::MediaDocument,
};

/// Immutable image bytes and their provenance.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ImageDocument {
    pub(super) inner: MediaDocument,
}

impl ImageDocument {
    /// Creates an image document with the default file size limit.
    pub fn from_bytes(
        id: impl Into<String>,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, FileDocumentError> {
        Self::from_bytes_with_limits(id, bytes, FileLimits::default())
    }

    /// Creates an image document with an explicit size limit.
    pub fn from_bytes_with_limits(
        id: impl Into<String>,
        bytes: impl Into<Vec<u8>>,
        limits: FileLimits,
    ) -> Result<Self, FileDocumentError> {
        Self::from_bytes_with_metadata(id, bytes, FileMetadata::new(), limits)
    }

    /// Creates an image document with provenance and an explicit size limit.
    ///
    /// This checks the signature with the pinned `infer` matcher and retains the bytes unchanged;
    /// it does not decode the image.
    pub fn from_bytes_with_metadata(
        id: impl Into<String>,
        bytes: impl Into<Vec<u8>>,
        metadata: FileMetadata,
        limits: FileLimits,
    ) -> Result<Self, FileDocumentError> {
        Ok(Self {
            inner: MediaDocument::new(
                id,
                Arc::new(bytes.into()),
                metadata,
                limits,
                Some(MediaKind::Image),
            )?,
        })
    }

    /// Returns the stable caller-provided document identity.
    pub const fn id(&self) -> &DocumentId {
        self.inner.id()
    }

    /// Returns retained file provenance, detected type and digest.
    pub const fn metadata(&self) -> &FileMetadata {
        self.inner.metadata()
    }

    /// Returns the exact immutable bytes without a copy.
    pub fn bytes(&self) -> &[u8] {
        self.inner.bytes()
    }

    /// Returns the retained payload length.
    pub const fn byte_len(&self) -> u64 {
        self.inner.byte_len()
    }

    /// Returns the lowercase SHA-256 digest of the exact retained payload.
    pub fn sha256(&self) -> &str {
        self.inner.sha256()
    }
}

/// Reconstructs a previously validated image Archive record without re-running detection.
pub fn from_archived_image(
    id: DocumentId,
    bytes: Arc<Vec<u8>>,
    metadata: FileMetadata,
) -> Result<ImageDocument, FileDocumentError> {
    Ok(ImageDocument {
        inner: MediaDocument::from_archived(id, bytes, metadata, MediaKind::Image)?,
    })
}
