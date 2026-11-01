use std::{
    fmt::{self, Display, Formatter},
    str::FromStr,
};

use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};

use super::{
    ARCHIVE_FORMAT_VERSION, ArchiveRefError, RecordKey, parse_reference_parts, parse_uuid_reference,
};

uuid_archive_ref!(
    ImageDocumentArchiveRef,
    "image-document",
    "Reference to one immutable archived ImageDocument."
);
uuid_archive_ref!(
    VideoDocumentArchiveRef,
    "video-document",
    "Reference to one immutable archived VideoDocument."
);
uuid_archive_ref!(
    AudioDocumentArchiveRef,
    "audio-document",
    "Reference to one immutable archived AudioDocument."
);
uuid_archive_ref!(
    BinaryDocumentArchiveRef,
    "binary-document",
    "Reference to one immutable archived BinaryDocument."
);

/// Runtime reference to one archived media or binary file variant.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum FileDocumentArchiveRef {
    /// Reference to an archived image document.
    Image(ImageDocumentArchiveRef),
    /// Reference to an archived video document.
    Video(VideoDocumentArchiveRef),
    /// Reference to an archived audio document.
    Audio(AudioDocumentArchiveRef),
    /// Reference to an archived binary document.
    Binary(BinaryDocumentArchiveRef),
}

impl FileDocumentArchiveRef {
    /// Returns the physical Archive format named by this reference.
    pub const fn format_version(&self) -> u32 {
        match self {
            Self::Image(reference) => reference.format_version(),
            Self::Video(reference) => reference.format_version(),
            Self::Audio(reference) => reference.format_version(),
            Self::Binary(reference) => reference.format_version(),
        }
    }

    /// Returns the opaque logical key, never a filesystem path.
    pub fn logical_key(&self) -> &str {
        match self {
            Self::Image(reference) => reference.logical_key(),
            Self::Video(reference) => reference.logical_key(),
            Self::Audio(reference) => reference.logical_key(),
            Self::Binary(reference) => reference.logical_key(),
        }
    }
}

impl Display for FileDocumentArchiveRef {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::Image(reference) => Display::fmt(reference, formatter),
            Self::Video(reference) => Display::fmt(reference, formatter),
            Self::Audio(reference) => Display::fmt(reference, formatter),
            Self::Binary(reference) => Display::fmt(reference, formatter),
        }
    }
}

impl FromStr for FileDocumentArchiveRef {
    type Err = ArchiveRefError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let (kind, _, _) = parse_reference_parts(value)?;
        match kind {
            "image-document" => value.parse().map(Self::Image),
            "video-document" => value.parse().map(Self::Video),
            "audio-document" => value.parse().map(Self::Audio),
            "binary-document" => value.parse().map(Self::Binary),
            _ => Err(ArchiveRefError::WrongKind {
                expected: "image-document, video-document, audio-document, or binary-document",
                found: kind.to_owned(),
            }),
        }
    }
}

impl Serialize for FileDocumentArchiveRef {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for FileDocumentArchiveRef {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        String::deserialize(deserializer)?
            .parse()
            .map_err(D::Error::custom)
    }
}
