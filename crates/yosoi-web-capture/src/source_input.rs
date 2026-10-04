use std::{fmt, sync::Arc};
use thiserror::Error;
use yosoi_types::Sha256Digest;

mod acquired_payload;
pub use acquired_payload::{
    AcquiredPayloadAccounting, AcquiredPayloadError, AcquiredPayloadOutcome, AcquiredPayloadState,
};

/// Completeness of bytes retained for provider-neutral source interpretation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetainedSourceExtent {
    Complete,
    Truncated,
}

/// Concrete provider-neutral retained bytes supplied to source interpretation.
#[derive(Eq, PartialEq)]
pub struct RetainedSource {
    bytes: RetainedSourceBytes,
    digest: Sha256Digest,
    extent: RetainedSourceExtent,
}

impl fmt::Debug for RetainedSource {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RetainedSource")
            .field("byte_len", &self.bytes().len())
            .field("digest", &self.digest)
            .field("extent", &self.extent)
            .field("bytes", &"<redacted>")
            .finish()
    }
}

#[derive(Debug, Eq, PartialEq)]
enum RetainedSourceBytes {
    Owned(Vec<u8>),
    Shared(Arc<[u8]>),
}

impl RetainedSourceBytes {
    fn as_slice(&self) -> &[u8] {
        match self {
            Self::Owned(bytes) => bytes,
            Self::Shared(bytes) => bytes,
        }
    }

    fn into_vec(self) -> Vec<u8> {
        match self {
            Self::Owned(bytes) => bytes,
            Self::Shared(bytes) => bytes.to_vec(),
        }
    }
}

impl RetainedSource {
    pub fn complete(bytes: Vec<u8>) -> Self {
        let digest = Sha256Digest::digest(&bytes);
        Self {
            bytes: RetainedSourceBytes::Owned(bytes),
            digest,
            extent: RetainedSourceExtent::Complete,
        }
    }

    pub fn new(bytes: Vec<u8>, extent: RetainedSourceExtent) -> Self {
        let digest = Sha256Digest::digest(&bytes);
        Self {
            bytes: RetainedSourceBytes::Owned(bytes),
            digest,
            extent,
        }
    }

    pub(crate) fn from_shared(bytes: Arc<[u8]>, extent: RetainedSourceExtent) -> Self {
        let digest = Sha256Digest::digest(&bytes);
        Self {
            bytes: RetainedSourceBytes::Shared(bytes),
            digest,
            extent,
        }
    }

    pub fn bytes(&self) -> &[u8] {
        self.bytes.as_slice()
    }
    pub fn into_bytes(self) -> Vec<u8> {
        self.bytes.into_vec()
    }
    pub const fn digest(&self) -> Sha256Digest {
        self.digest
    }
    pub const fn extent(&self) -> RetainedSourceExtent {
        self.extent
    }
}

/// Maximum byte length retained for a source media-type declaration.
pub const MAX_SOURCE_MEDIA_TYPE_BYTES: usize = 1_024;

/// A media-type declaration whose byte length has been validated.
///
/// The representation is private so an oversized value cannot bypass the
/// provider-neutral acquisition bound.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundedSourceMediaType(String);

impl BoundedSourceMediaType {
    pub fn try_from_text(value: impl Into<String>) -> Result<Self, SourceMediaTypeTooLong> {
        let value = value.into();
        if value.len() > MAX_SOURCE_MEDIA_TYPE_BYTES {
            Err(SourceMediaTypeTooLong)
        } else {
            Ok(Self(value))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("source media type exceeds 1,024 bytes")]
pub struct SourceMediaTypeTooLong;

/// Provider-neutral observation of a single media-type declaration.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SourceMediaType {
    Absent,
    Value(BoundedSourceMediaType),
    InvalidEncoding,
    TooLong,
    Duplicate,
}

impl SourceMediaType {
    pub fn from_text(value: impl Into<String>) -> Self {
        BoundedSourceMediaType::try_from_text(value).map_or(Self::TooLong, Self::Value)
    }

    pub fn value(&self) -> Option<&str> {
        match self {
            Self::Value(value) => Some(value.as_str()),
            Self::Absent | Self::InvalidEncoding | Self::TooLong | Self::Duplicate => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum RetainedSourceReplayError {
    #[error("source artifact has no retained payload")]
    BytesUnavailable,
    #[error("source artifact retained size differs from the supplied payload")]
    SizeMismatch,
    #[error("source artifact digest differs from the supplied payload")]
    DigestMismatch,
}

impl RetainedSource {
    pub fn from_artifact_payload(
        source: &crate::SourceArtifact,
        bytes: Vec<u8>,
    ) -> Result<Self, RetainedSourceReplayError> {
        let metadata = source.metadata();
        let retained = metadata
            .extent()
            .retained_bytes()
            .ok_or(RetainedSourceReplayError::BytesUnavailable)?;
        let actual =
            u64::try_from(bytes.len()).map_err(|_| RetainedSourceReplayError::SizeMismatch)?;
        if retained.get() != actual {
            return Err(RetainedSourceReplayError::SizeMismatch);
        }
        let digest = Sha256Digest::digest(&bytes);
        if metadata.content_digest() != Some(digest) {
            return Err(RetainedSourceReplayError::DigestMismatch);
        }
        let extent = match metadata.extent() {
            crate::ArtifactByteExtent::Complete { .. } => RetainedSourceExtent::Complete,
            crate::ArtifactByteExtent::Truncated(_) => RetainedSourceExtent::Truncated,
            crate::ArtifactByteExtent::Discarded { .. }
            | crate::ArtifactByteExtent::Unavailable => {
                return Err(RetainedSourceReplayError::BytesUnavailable);
            }
        };
        Ok(Self {
            bytes: RetainedSourceBytes::Owned(bytes),
            digest,
            extent,
        })
    }
}
