use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

/// Structural coordinate validation failure, without checking a live document.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum CoordinateError {
    /// A half-open range ends before its starting offset.
    #[error("coordinate range end cannot precede its start")]
    ReversedRange,
    /// A coordinate's string identity contains no non-whitespace text.
    #[error("coordinate identity cannot be empty")]
    EmptyIdentity,
    /// Rendered DOM node identity is zero rather than a positive snapshot-local ID.
    #[error("rendered DOM node identity must be greater than zero")]
    ZeroDomNodeId,
    /// A nonroot JSON Pointer does not start with `/`.
    #[error("JSON Pointer must be empty or begin with a slash")]
    InvalidJsonPointerSyntax,
    /// A JSON Pointer escape is neither `~0` nor `~1`.
    #[error("JSON Pointer tokens may escape only '~' as '~0' and '/' as '~1'")]
    InvalidJsonPointerEscape,
    /// An XML expanded-name path segment has an empty local name.
    #[error("expanded-name path segment local name cannot be empty")]
    EmptyExpandedLocalName,
    /// An XML same-name sibling index is zero rather than one-based.
    #[error("expanded-name path sibling index must be greater than zero")]
    ZeroExpandedSiblingIndex,
    /// An explicitly supplied XML expanded-name path contains no segments.
    #[error("expanded-name tree path cannot be empty")]
    EmptyExpandedNamePath,
    /// A tree child path is empty or contains a zero child index.
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
    /// Creates `[start, end)` byte offsets, allowing an empty range.
    ///
    /// Returns [`CoordinateError::ReversedRange`] when `end < start`. This
    /// validates ordering only; it does not check payload bounds or UTF-8 boundaries.
    pub const fn try_new(start: u64, end: u64) -> Result<Self, CoordinateError> {
        if start <= end {
            Ok(Self { start, end })
        } else {
            Err(CoordinateError::ReversedRange)
        }
    }

    /// Returns the inclusive starting byte offset in the owned source payload.
    pub const fn start(self) -> u64 {
        self.start
    }
    /// Returns the exclusive ending byte offset in the owned source payload.
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
    /// Creates `[start, end)` Unicode-scalar offsets, allowing an empty range.
    ///
    /// Returns [`CoordinateError::ReversedRange`] when `end < start`. Offsets
    /// count Unicode scalars rather than UTF-8 bytes or grapheme clusters;
    /// construction does not verify the range against any text.
    pub const fn try_new(start: u64, end: u64) -> Result<Self, CoordinateError> {
        if start <= end {
            Ok(Self { start, end })
        } else {
            Err(CoordinateError::ReversedRange)
        }
    }

    /// Returns the inclusive Unicode-scalar starting offset in decoded text.
    pub const fn start(self) -> u64 {
        self.start
    }
    /// Returns the exclusive Unicode-scalar ending offset in decoded text.
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
    /// Pairs byte and Unicode-scalar ranges without checking their correspondence.
    ///
    /// The caller is responsible for ensuring both refer to the same match in
    /// the retained source and decoded text; no document contents are inspected.
    pub const fn new(byte_range: ByteRange, scalar_range: TextRange) -> Self {
        Self {
            byte_range,
            scalar_range,
        }
    }

    /// Returns the exact owned-source byte offsets recorded for this match.
    pub const fn byte_range(self) -> ByteRange {
        self.byte_range
    }

    /// Returns the decoded-text Unicode-scalar offsets recorded for this match.
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
