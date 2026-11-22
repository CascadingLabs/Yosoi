use crate::{archive::DocumentArchiveRef, documents::ImageDocument, surface::PixelRect};
use serde::{Deserialize, Serialize};

/// Pixel coordinate plane declared by an artifact.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PixelCoordinateKind {
    /// Coordinates in the encoded image's raster, before EXIF orientation.
    OriginalRaster,
    /// Coordinates in a decoder-produced canvas, such as a video frame.
    DecodedCanvas,
    /// Coordinates in a resized or cropped output image.
    DerivedCanvas,
}

/// Orientation action already applied before the named coordinate plane.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PixelOrientation {
    /// EXIF orientation metadata was retained but not applied to the raster.
    ExifUnapplied,
    /// The source decoder applied its orientation metadata.
    DecoderApplied,
    /// The source has no orientation metadata, such as a browser screenshot.
    NotApplicable,
    /// The producer cannot establish the source orientation behavior.
    Unknown,
}

/// Dimensions and coordinate meaning of one exact pixel plane.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PixelCoordinateSpace {
    /// Coordinate plane kind.
    pub kind: PixelCoordinateKind,
    /// Plane width in pixels.
    pub width: u32,
    /// Plane height in pixels.
    pub height: u32,
    /// Orientation handling that defines this plane.
    pub orientation: PixelOrientation,
}

/// Producer that owns the exact root pixels represented by this artifact.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PixelSource {
    /// A typed image document with a caller identity and exact payload digest.
    ImageDocument {
        /// Stable document identity, independent of Surface preparation.
        document_id: String,
        /// SHA-256 of the exact original encoded image bytes.
        sha256: String,
    },
    /// A browser screenshot captured from one exact observation.
    BrowserScreenshot {
        /// Producer-issued screenshot identity.
        identity: String,
    },
    /// A frame decoded from one exact frozen video observation.
    VideoFrame {
        /// Stable typed video document identity.
        source_document_id: String,
        /// SHA-256 of the complete frozen video source bytes.
        source_sha256: String,
        /// Exact observation identity used to address this decoded frame.
        observation: String,
        /// Exact native frame address, retained without coordinate reinterpretation.
        reference: String,
        /// Requested stream-relative frame position in microseconds.
        requested_us: u64,
        /// Measured source PTS in microseconds.
        source_pts_us: i64,
    },
    /// A pre-typed archived video frame whose typed source document identity is unavailable.
    LegacyVideoFrame {
        /// Complete frozen video digest when the legacy envelope recorded it.
        source_sha256: Option<String>,
        /// Exact observation identity retained by the legacy frame envelope.
        observation: String,
        /// Exact native frame address retained by the legacy frame envelope.
        reference: String,
        /// Requested stream-relative frame position in microseconds.
        requested_us: u64,
        /// Measured source PTS in microseconds.
        source_pts_us: i64,
    },
}

/// Explicit pixel operation that produced a derived artifact.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PixelOperation {
    /// The exact source raster, without resizing or cropping.
    Source,
    /// A bounded aspect-preserving overview resize.
    Overview {
        /// Maximum width or height used to choose the output dimensions.
        max_side: u32,
        /// Resampling kernel name, fixed by the operation version.
        filter: String,
    },
    /// An explicitly sized resize.
    Resize {
        /// Requested output width in pixels.
        width: u32,
        /// Requested output height in pixels.
        height: u32,
        /// Resampling kernel name, fixed by the operation version.
        filter: String,
    },
    /// A crop from the declared parent coordinate space.
    Crop {
        /// Bounds in parent pixel coordinates, with exclusive right/bottom edges.
        rect: PixelRect,
    },
}

/// Rational map from output pixel edges to the immediate parent pixel edges.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PixelEdgeTransform {
    /// Parent-x units per output-x unit numerator.
    pub scale_x_numerator: u32,
    /// Output-x units per parent-x unit denominator.
    pub scale_x_denominator: u32,
    /// Parent-y units per output-y unit numerator.
    pub scale_y_numerator: u32,
    /// Output-y units per parent-y unit denominator.
    pub scale_y_denominator: u32,
    /// Parent-space x translation in pixels.
    pub translate_x: u32,
    /// Parent-space y translation in pixels.
    pub translate_y: u32,
}

/// Versioned operation and coordinate map for one artifact.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PixelTransform {
    /// Transform schema version. Version 1 maps pixel edges using integer ratios.
    pub version: u32,
    /// Operation and its caller-visible parameters.
    pub operation: PixelOperation,
    /// Exact identity of the parent artifact, absent only for source pixels.
    pub parent_identity: Option<String>,
    /// Exact digest of the parent artifact pixels, absent only for source pixels.
    pub parent_sha256: Option<String>,
    /// Parent artifact media type, absent only for source pixels.
    pub parent_media_type: Option<String>,
    /// Parent coordinate space, absent only for source pixels.
    pub parent_space: Option<PixelCoordinateSpace>,
    /// Output-edge to parent-edge transform, absent only for source pixels.
    pub output_to_parent: Option<PixelEdgeTransform>,
}

/// Provenance and pixel metadata for an immutable encoded artifact.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PixelArtifactInfo {
    /// Pixel artifact schema version.
    pub version: u32,
    /// Identity bound to source, pixels, and transform metadata.
    pub identity: String,
    /// SHA-256 of exact encoded artifact bytes.
    pub sha256: String,
    /// Encoded MIME type.
    pub media_type: String,
    /// Width of the encoded artifact in pixels.
    pub width: u32,
    /// Height of the encoded artifact in pixels.
    pub height: u32,
    /// Root source and its original coordinate plane.
    pub source: PixelSource,
    /// Coordinate meaning of the returned artifact pixels.
    pub coordinate_space: PixelCoordinateSpace,
    /// Root source coordinate space used by all derived coordinates.
    pub source_space: PixelCoordinateSpace,
    /// Versioned source-to-artifact operation.
    pub transform: PixelTransform,
}

/// Original or derived encoded pixels plus checked provenance metadata.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PixelArtifact {
    pub(super) document: ImageDocument,
    pub(super) info: PixelArtifactInfo,
}

/// Typed Archive reference for one pixel artifact record.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PixelArtifactArchiveRef {
    /// Metadata Document selecting the raw typed image payload and its provenance.
    pub document: DocumentArchiveRef,
}
