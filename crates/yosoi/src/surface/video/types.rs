//! Public video evidence and processing-policy values.
use crate::surface::{
    PixelRect, SurfaceError, model,
    pixels::{PixelArtifact, PixelArtifactInfo},
};
use serde::{Deserialize, Serialize};
use std::{
    fmt::{Debug, Formatter, Result as FmtResult},
    io,
};
use thiserror::Error;

/// Checked media preparation, scope, resource and decoder failures.
#[derive(Debug, Error)]
pub enum VideoError {
    /// Local snapshot or decoder I/O failed.
    #[error("video I/O failed: {0}")]
    Io(#[from] io::Error),
    /// Evidence addressing or media metadata was invalid.
    #[error("invalid video evidence: {0}")]
    Invalid(String),
    /// A declared resource limit was exceeded.
    #[error("video limit exceeded: {0}")]
    Limit(&'static str),
    /// The native decoder rejected the input or frame request.
    #[error("video tool failed: {0}")]
    Tool(String),
    /// Cancellation completed after terminating and reaping the owned decoder.
    #[error("video processing cancelled")]
    Cancelled,
    /// A bounded probe/decode wait elapsed and its child was terminated.
    #[error("video tool timed out")]
    Timeout,
    /// No frame starts at or after a requested position, including the final frame tail.
    #[error("no frame at or after {requested_us} microseconds")]
    NoFrameAtOrAfter {
        /// Requested position relative to the primary stream start.
        requested_us: u64,
    },
    /// A common evidence operation failed.
    #[error(transparent)]
    Surface(#[from] SurfaceError),
}
/// Processing bounds. Frame size and interval granularity affect interpretation identity.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct VideoPolicy {
    /// Maximum local source bytes copied into an owned immutable snapshot.
    pub max_source_bytes: usize,
    /// Maximum decoded frame side; the adapter never upscales smaller videos.
    pub frame_max_side: u32,
    /// Maximum encoded PNG bytes per materialized frame or crop.
    pub max_frame_bytes: usize,
    /// Smallest temporal interval automatically subdivided by exploration.
    pub min_interval_us: u64,
    /// Maximum accepted primary video duration.
    pub max_duration_us: u64,
    /// Timeout for each probe or decode process.
    pub tool_timeout_ms: u64,
}
impl Default for VideoPolicy {
    fn default() -> Self {
        Self {
            max_source_bytes: 32 * 1024 * 1024,
            frame_max_side: 1920,
            max_frame_bytes: 8 * 1024 * 1024,
            min_interval_us: 250_000,
            max_duration_us: 21_600_000_000,
            tool_timeout_ms: 30_000,
        }
    }
}
impl VideoPolicy {
    pub(super) fn validate(&self) -> Result<(), VideoError> {
        if self.max_source_bytes == 0
            || self.max_source_bytes > 128 * 1024 * 1024
            || !(32..=4096).contains(&self.frame_max_side)
            || self.max_frame_bytes == 0
            || self.max_frame_bytes > 32 * 1024 * 1024
            || self.min_interval_us == 0
            || self.max_duration_us == 0
            || !(1..=120_000).contains(&self.tool_timeout_ms)
        {
            return Err(VideoError::Invalid(
                "unsupported video policy bounds".into(),
            ));
        }
        Ok(())
    }
}
/// Primary video metadata. Positions are relative to this stream's start, not wall time.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VideoMetadata {
    /// Original source name, for display only; not an address used to reopen evidence.
    pub name: String,
    /// SHA-256 of the complete frozen source bytes.
    pub source_sha256: String,
    /// Original source byte length.
    pub source_bytes: usize,
    /// Demuxer-reported container formats.
    pub container: String,
    /// Primary video codec name.
    pub codec: String,
    /// Source raster width before optional frame scaling.
    pub width: u32,
    /// Source raster height before optional frame scaling.
    pub height: u32,
    /// Primary stream duration in microseconds.
    pub duration_us: u64,
    /// Whether duration fell back to container metadata and may include other streams.
    pub duration_estimated: bool,
    /// Primary stream start timestamp in microseconds, possibly nonzero or negative.
    pub stream_start_us: i64,
    /// Source time-base expression supplied by the demuxer.
    pub time_base: String,
    /// Number of audio streams; audio evidence is not decoded by this adapter.
    pub audio_streams: usize,
    /// Decoder version header used for this observation's interpretation profile.
    pub decoder: String,
}
/// PNG evidence metadata; binary bytes are returned separately from this DTO.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FrameInfo {
    /// Exact immutable video address that produced the frame or crop.
    pub reference: model::Reference,
    /// Requested position relative to primary stream start.
    pub requested_us: u64,
    /// Actual source PTS measured by the decoder, not copied from the requested time.
    pub source_pts_us: i64,
    /// Actual stream-relative position, absent for pre-roll before stream start.
    pub position_us: Option<u64>,
    /// Width of the full decoded frame's pixel coordinate space.
    pub canvas_width: u32,
    /// Height of the full decoded frame's pixel coordinate space.
    pub canvas_height: u32,
    /// Width of returned PNG pixels.
    pub width: u32,
    /// Height of returned PNG pixels.
    pub height: u32,
    /// Optional crop in full decoded-frame pixels, never original-source pixels implicitly.
    pub region: Option<PixelRect>,
    /// SHA-256 of the returned PNG bytes.
    pub png_sha256: String,
    /// Encoded PNG length, independent of text response budgets.
    pub png_bytes: usize,
    /// Checked shared pixel provenance, absent only in historical frame envelopes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pixel_artifact: Option<PixelArtifactInfo>,
}
/// Materialized pixel evidence with metadata suitable for bounded agent replies.
#[derive(Clone)]
pub struct DecodedFrame {
    /// Source and time/pixel coordinate provenance.
    pub info: FrameInfo,
    /// Actual PNG bytes; these are intentionally not implicitly serialized into replies.
    pub png: Vec<u8>,
    /// Exact typed pixel payload and provenance; absent in legacy frame envelopes.
    pub pixels: Option<PixelArtifact>,
}
impl Debug for DecodedFrame {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> FmtResult {
        formatter
            .debug_struct("DecodedFrame")
            .field("info", &self.info)
            .field("png_bytes", &self.png.len())
            .finish_non_exhaustive()
    }
}
