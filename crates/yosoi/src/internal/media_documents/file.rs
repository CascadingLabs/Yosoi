use crate::internal::documents::DocumentId;

use super::{
    audio::AudioDocument, binary::BinaryDocument, image::ImageDocument, video::VideoDocument,
};

/// An immutable file classified as image, video, audio or binary from its signature.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FileDocument {
    /// A detected image file.
    Image(ImageDocument),
    /// A detected video file.
    Video(VideoDocument),
    /// A detected audio file.
    Audio(AudioDocument),
    /// An unrecognized or other file type.
    Binary(BinaryDocument),
}

impl FileDocument {
    /// Returns the stable caller-provided document identity.
    pub const fn id(&self) -> &DocumentId {
        match self {
            Self::Image(document) => document.id(),
            Self::Video(document) => document.id(),
            Self::Audio(document) => document.id(),
            Self::Binary(document) => document.id(),
        }
    }

    /// Returns the retained file provenance, detected type and digest.
    pub const fn metadata(&self) -> &super::FileMetadata {
        match self {
            Self::Image(document) => document.metadata(),
            Self::Video(document) => document.metadata(),
            Self::Audio(document) => document.metadata(),
            Self::Binary(document) => document.metadata(),
        }
    }

    /// Returns the exact immutable bytes without a copy.
    pub fn bytes(&self) -> &[u8] {
        match self {
            Self::Image(document) => document.bytes(),
            Self::Video(document) => document.bytes(),
            Self::Audio(document) => document.bytes(),
            Self::Binary(document) => document.bytes(),
        }
    }

    /// Returns the retained payload length.
    pub const fn byte_len(&self) -> u64 {
        match self {
            Self::Image(document) => document.byte_len(),
            Self::Video(document) => document.byte_len(),
            Self::Audio(document) => document.byte_len(),
            Self::Binary(document) => document.byte_len(),
        }
    }

    /// Returns the lowercase SHA-256 digest of the exact retained payload.
    pub fn sha256(&self) -> &str {
        match self {
            Self::Image(document) => document.sha256(),
            Self::Video(document) => document.sha256(),
            Self::Audio(document) => document.sha256(),
            Self::Binary(document) => document.sha256(),
        }
    }
}
