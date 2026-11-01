use std::sync::Arc;

use crate::internal::documents::DocumentId;

use super::{
    FileDocumentError, FileLimits, FileMetadata,
    classify::{MediaKind, detected_kind},
    payload::MediaDocument,
};

/// Immutable video bytes and their provenance.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VideoDocument {
    pub(super) inner: MediaDocument,
}

impl VideoDocument {
    /// Reports whether the pinned signature matcher classifies these bytes as video.
    pub(crate) fn has_video_signature(bytes: &[u8]) -> bool {
        detected_kind(bytes) == MediaKind::Video
    }

    /// Creates a typed source after FFprobe confirms an Ogg or MPEG-TS video stream.
    /// The ordinary public byte constructors remain signature-gated.
    pub(crate) fn from_probe_validated_bytes(
        id: impl Into<String>,
        bytes: impl Into<Vec<u8>>,
        metadata: FileMetadata,
        limits: FileLimits,
        container: &str,
    ) -> Result<Self, FileDocumentError> {
        Ok(Self {
            inner: MediaDocument::new_probe_validated_video(
                id,
                Arc::new(bytes.into()),
                metadata,
                limits,
                container,
            )?,
        })
    }

    /// Creates a video document with the default file size limit.
    pub fn from_bytes(
        id: impl Into<String>,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, FileDocumentError> {
        Self::from_bytes_with_limits(id, bytes, FileLimits::default())
    }

    /// Creates a video document with an explicit size limit.
    pub fn from_bytes_with_limits(
        id: impl Into<String>,
        bytes: impl Into<Vec<u8>>,
        limits: FileLimits,
    ) -> Result<Self, FileDocumentError> {
        Self::from_bytes_with_metadata(id, bytes, FileMetadata::new(), limits)
    }

    /// Creates a video document with provenance and an explicit size limit.
    ///
    /// This checks the signature with the pinned `infer` matcher and retains the bytes unchanged;
    /// it does not decode the video. Signature-ambiguous Ogg and MPEG-TS cannot be authored
    /// through this constructor; the video Surface can retain them after its bounded FFprobe
    /// validation confirms a self-contained video stream.
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
                Some(MediaKind::Video),
            )?,
        })
    }

    /// Copies this exact payload under a new identity and optional caller metadata.
    ///
    /// Signature-ambiguous Ogg and MPEG-TS documents retain their existing
    /// FFprobe-confirmed container basis. Caller metadata cannot create that basis;
    /// detected MIME and digest are recomputed from the unchanged payload. Omitted
    /// metadata retains the current value; omitted limits use the default file limit.
    pub fn copy_with_metadata(
        &self,
        id: impl Into<String>,
        metadata: Option<FileMetadata>,
        limits: Option<FileLimits>,
    ) -> Result<Self, FileDocumentError> {
        let metadata = metadata.unwrap_or_else(|| self.metadata().clone());
        let limits = limits.unwrap_or_default();
        if let Some(container) = self.metadata().probe_validated_video_container() {
            return Self::from_probe_validated_bytes(
                id,
                self.bytes().to_vec(),
                metadata,
                limits,
                container,
            );
        }
        Self::from_bytes_with_metadata(id, self.bytes().to_vec(), metadata, limits)
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

/// Reconstructs a previously validated video Archive record without re-running detection.
pub fn from_archived_video(
    id: DocumentId,
    bytes: Arc<Vec<u8>>,
    metadata: FileMetadata,
) -> Result<VideoDocument, FileDocumentError> {
    Ok(VideoDocument {
        inner: MediaDocument::from_archived(id, bytes, metadata, MediaKind::Video)?,
    })
}
