use std::{fmt, sync::Arc};

use crate::internal::{documents::DocumentId, types::Sha256Digest};

use super::{
    FileDocumentError, FileLimits,
    classify::{MediaKind, accepts_probe_validated_video, detected_kind, expected_type_name},
    metadata::FileMetadata,
};

#[derive(Clone, Eq, PartialEq)]
pub(super) struct MediaDocument {
    id: DocumentId,
    bytes: Arc<Vec<u8>>,
    byte_len: u64,
    metadata: FileMetadata,
    sha256: String,
}

impl MediaDocument {
    pub(super) fn new(
        id: impl Into<String>,
        bytes: Arc<Vec<u8>>,
        metadata: FileMetadata,
        limits: FileLimits,
        expected: Option<MediaKind>,
    ) -> Result<Self, FileDocumentError> {
        Self::build(id, bytes, metadata, limits, expected, None)
    }

    pub(super) fn new_probe_validated_video(
        id: impl Into<String>,
        bytes: Arc<Vec<u8>>,
        metadata: FileMetadata,
        limits: FileLimits,
        container: &str,
    ) -> Result<Self, FileDocumentError> {
        Self::build(
            id,
            bytes,
            metadata,
            limits,
            Some(MediaKind::Video),
            Some(container),
        )
    }

    fn build(
        id: impl Into<String>,
        bytes: Arc<Vec<u8>>,
        mut metadata: FileMetadata,
        limits: FileLimits,
        expected: Option<MediaKind>,
        probe_validated_video_container: Option<&str>,
    ) -> Result<Self, FileDocumentError> {
        limits.validate()?;
        metadata.validate()?;
        let byte_len = u64::try_from(bytes.len()).map_err(|_| FileDocumentError::TooLarge {
            maximum: limits.max_bytes,
            observed: u64::MAX,
        })?;
        if byte_len > limits.max_bytes {
            return Err(FileDocumentError::TooLarge {
                maximum: limits.max_bytes,
                observed: byte_len,
            });
        }
        let actual_kind = detected_kind(bytes.as_slice());
        let probe_validated_video = expected == Some(MediaKind::Video)
            && probe_validated_video_container
                .is_some_and(|container| accepts_probe_validated_video(container, actual_kind));
        if probe_validated_video_container.is_some() && !probe_validated_video {
            return Err(FileDocumentError::TypeMismatch {
                expected: "decoder-validated video container",
                detected: infer::get(bytes.as_slice()).map(|kind| kind.mime_type().to_owned()),
            });
        }
        if let Some(expected) = expected
            && actual_kind != expected
            && !probe_validated_video
        {
            return Err(FileDocumentError::TypeMismatch {
                expected: expected_type_name(expected),
                detected: infer::get(bytes.as_slice()).map(|kind| kind.mime_type().to_owned()),
            });
        }
        let id = DocumentId::try_new(id)?;
        let sha256 = metadata.complete_for_payload(bytes.as_slice());
        if let Some(container) = probe_validated_video_container {
            metadata.record_probe_validated_video_container(container);
        }
        Ok(Self {
            id,
            bytes,
            byte_len,
            metadata,
            sha256,
        })
    }

    pub(super) fn from_archived(
        id: DocumentId,
        bytes: Arc<Vec<u8>>,
        metadata: FileMetadata,
        expected: MediaKind,
    ) -> Result<Self, FileDocumentError> {
        metadata.validate()?;
        let byte_len = u64::try_from(bytes.len()).map_err(|_| FileDocumentError::TooLarge {
            maximum: super::MAX_FILE_BYTES,
            observed: u64::MAX,
        })?;
        if byte_len > super::MAX_FILE_BYTES {
            return Err(FileDocumentError::TooLarge {
                maximum: super::MAX_FILE_BYTES,
                observed: byte_len,
            });
        }
        let sha256 = Sha256Digest::digest(bytes.as_slice()).to_string();
        let detected_mime = infer::get(bytes.as_slice()).map(|kind| kind.mime_type());
        let signature_match = metadata.probe_validated_video_container().is_none()
            && detected_kind(bytes.as_slice()) == expected
            && stored_type_matches(&metadata, expected);
        let probe_validated_video = expected == MediaKind::Video
            && metadata
                .probe_validated_video_container()
                .is_some_and(|container| {
                    accepts_probe_validated_video(container, detected_kind(bytes.as_slice()))
                        && metadata.detected_media_type() == detected_mime
                });
        if !metadata.has_digest(&sha256) || !(signature_match || probe_validated_video) {
            return Err(FileDocumentError::ArchivedMetadataMismatch);
        }
        Ok(Self {
            id,
            bytes,
            byte_len,
            metadata,
            sha256,
        })
    }

    pub(super) const fn id(&self) -> &DocumentId {
        &self.id
    }

    pub(super) const fn metadata(&self) -> &FileMetadata {
        &self.metadata
    }

    pub(super) fn bytes(&self) -> &[u8] {
        self.bytes.as_slice()
    }

    pub(super) const fn byte_len(&self) -> u64 {
        self.byte_len
    }

    pub(super) fn sha256(&self) -> &str {
        &self.sha256
    }
}

impl fmt::Debug for MediaDocument {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("MediaDocument")
            .field("id", &self.id)
            .field("bytes", &"<redacted>")
            .field("byte_len", &self.byte_len)
            .field("metadata", &self.metadata)
            .field("sha256", &self.sha256)
            .finish()
    }
}

fn stored_type_matches(metadata: &FileMetadata, expected: MediaKind) -> bool {
    match expected {
        MediaKind::Image => metadata
            .detected_media_type()
            .is_some_and(|media_type| media_type.starts_with("image/")),
        MediaKind::Video => metadata
            .detected_media_type()
            .is_some_and(|media_type| media_type.starts_with("video/")),
        MediaKind::Audio => metadata
            .detected_media_type()
            .is_some_and(|media_type| media_type.starts_with("audio/")),
        MediaKind::Binary => true,
    }
}
