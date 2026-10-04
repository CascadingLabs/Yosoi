use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum CoordinateError {
    #[error("coordinate range end cannot precede its start")]
    ReversedRange,
    #[error("coordinate identity cannot be empty")]
    EmptyIdentity,
    #[error("rendered DOM node identity must be greater than zero")]
    ZeroDomNodeId,
    #[error("JSON Pointer must be empty or begin with a slash")]
    InvalidJsonPointerSyntax,
    #[error("JSON Pointer tokens may escape only '~' as '~0' and '/' as '~1'")]
    InvalidJsonPointerEscape,
    #[error("expanded-name path segment local name cannot be empty")]
    EmptyExpandedLocalName,
    #[error("expanded-name path sibling index must be greater than zero")]
    ZeroExpandedSiblingIndex,
    #[error("expanded-name tree path cannot be empty")]
    EmptyExpandedNamePath,
    #[error("tree child path must be non-empty and one-based")]
    InvalidTreeChildPath,
}

/// Half-open byte range in the exact owned source payload, possibly empty.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ByteRange {
    start: u64,
    end: u64,
}

impl ByteRange {
    pub const fn try_new(start: u64, end: u64) -> Result<Self, CoordinateError> {
        if start <= end {
            Ok(Self { start, end })
        } else {
            Err(CoordinateError::ReversedRange)
        }
    }

    pub const fn start(self) -> u64 {
        self.start
    }
    pub const fn end(self) -> u64 {
        self.end
    }
}

impl<'de> Deserialize<'de> for ByteRange {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WireRange {
            start: u64,
            end: u64,
        }

        let wire = WireRange::deserialize(deserializer)?;
        Self::try_new(wire.start, wire.end).map_err(D::Error::custom)
    }
}

/// Half-open Unicode-scalar range in decoded text, possibly empty.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TextRange {
    start: u64,
    end: u64,
}

impl TextRange {
    pub const fn try_new(start: u64, end: u64) -> Result<Self, CoordinateError> {
        if start <= end {
            Ok(Self { start, end })
        } else {
            Err(CoordinateError::ReversedRange)
        }
    }

    pub const fn start(self) -> u64 {
        self.start
    }
    pub const fn end(self) -> u64 {
        self.end
    }
}

/// Both exact byte and Unicode-scalar offsets for a decoded-text match.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DecodedTextCoordinate {
    byte_range: ByteRange,
    scalar_range: TextRange,
}

impl DecodedTextCoordinate {
    pub const fn new(byte_range: ByteRange, scalar_range: TextRange) -> Self {
        Self {
            byte_range,
            scalar_range,
        }
    }

    pub const fn byte_range(self) -> ByteRange {
        self.byte_range
    }

    pub const fn scalar_range(self) -> TextRange {
        self.scalar_range
    }
}

impl<'de> Deserialize<'de> for TextRange {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WireRange {
            start: u64,
            end: u64,
        }

        let wire = WireRange::deserialize(deserializer)?;
        Self::try_new(wire.start, wire.end).map_err(D::Error::custom)
    }
}
