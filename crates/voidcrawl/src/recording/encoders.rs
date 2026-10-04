//! Optional post-processing of a recorded frame sequence into a single
//! playable artifact.
//!
//! Both encoders are feature-gated and neither is on by default. The frame
//! sequence is this crate's actual output — a container format is a policy
//! choice, and a caller who wants MP4 with specific flags is better served
//! piping [`Frame`] bytes into their own encoder than by options we'd have
//! to guess at.
//!
//! Frames are **not** evenly spaced (Chrome emits on paint), so both
//! encoders drive timing off each frame's real
//! [`offset`](super::Frame::offset) rather than assuming a constant rate.

#[cfg(feature = "encode-ffmpeg")]
use std::fmt::Write as _;
#[cfg(feature = "encode-gif")]
use std::io::BufWriter;
use std::{fs, path::Path, time::Duration};

#[cfg(feature = "encode-ffmpeg")]
use tokio::process::Command;

use super::Frame;
#[cfg(feature = "encode-gif")]
use super::FrameFormat;
#[cfg(feature = "encode-ffmpeg")]
use super::{Encoding, RecordedRegion, RecordingOptions};
use crate::error::{Result, VoidCrawlError};

/// Per-frame display duration, derived from the gap to the following frame.
/// The last frame inherits the previous gap, since nothing bounds it.
fn frame_delays(frames: &[Frame]) -> Vec<Duration> {
    let mut delays = Vec::with_capacity(frames.len());
    for pair in frames.windows(2) {
        // `windows(2)` always yields exactly two elements.
        let gap = match (pair.first(), pair.get(1)) {
            (Some(a), Some(b)) => b.offset.saturating_sub(a.offset),
            _ => Duration::from_millis(100),
        };
        delays.push(gap);
    }
    let last = delays.last().copied().unwrap_or(Duration::from_millis(100));
    delays.push(last);
    delays
}

/// Encode frames to an animated GIF, in-process.
///
/// GIF is 256 colors and stores frames as full images, so this is by far the
/// largest output of the three — fine for a short UI interaction, a poor
/// choice for a 30s recording of video content.
#[cfg(feature = "encode-gif")]
pub(super) fn gif(frames: &[Frame], format: FrameFormat, path: &Path) -> Result<()> {
    use image::{
        Delay, Frame as AnimationFrame,
        codecs::gif::{GifEncoder, Repeat},
        load_from_memory_with_format,
    };

    if frames.is_empty() {
        return Err(VoidCrawlError::RecordingEncodeError(
            "no frames were captured; nothing to encode".into(),
        ));
    }

    let file = fs::File::create(path).map_err(|e| {
        VoidCrawlError::RecordingEncodeError(format!("create {}: {e}", path.display()))
    })?;
    let mut encoder = GifEncoder::new(BufWriter::new(file));
    encoder
        .set_repeat(Repeat::Infinite)
        .map_err(|e| VoidCrawlError::RecordingEncodeError(format!("gif repeat: {e}")))?;

    let delays = frame_delays(frames);
    for (frame, delay) in frames.iter().zip(delays) {
        let img = load_from_memory_with_format(&frame.data, format.as_image())
            .map_err(|e| VoidCrawlError::RecordingEncodeError(format!("decode frame: {e}")))?;
        let buffer = img.to_rgba8();
        let animation_frame =
            AnimationFrame::from_parts(buffer, 0, 0, Delay::from_saturating_duration(delay));
        encoder
            .encode_frame(animation_frame)
            .map_err(|e| VoidCrawlError::RecordingEncodeError(format!("gif frame: {e}")))?;
    }
    Ok(())
}

/// Encode frames to MP4/WebM by shelling out to `ffmpeg`.
///
/// Uses the concat demuxer with explicit per-frame durations rather than
/// `-framerate`, so the output plays back at the speed the page actually
/// rendered instead of a uniform rate the capture never had.
///
/// Requires an `ffmpeg` binary on PATH. Its absence is reported as
/// [`VoidCrawlError::RecordingEncodeError`] with the frames still intact on
/// the [`Recording`](super::Recording).
#[cfg(feature = "encode-ffmpeg")]
pub(super) async fn ffmpeg(
    region: &RecordedRegion,
    encoding: Encoding,
    path: &Path,
    opts: &RecordingOptions,
) -> Result<()> {
    if region.frames.is_empty() {
        return Err(VoidCrawlError::RecordingEncodeError(
            "no frames were captured; nothing to encode".into(),
        ));
    }

    let staging = tempfile::tempdir()
        .map_err(|e| VoidCrawlError::RecordingEncodeError(format!("staging dir: {e}")))?;
    let ext = opts.format.extension();
    let delays = frame_delays(&region.frames);
    let mut concat = String::new();
    for (frame, delay) in region.frames.iter().zip(delays) {
        let name = format!("{:05}.{ext}", frame.index);
        let file = staging.path().join(&name);
        fs::write(&file, &frame.data).map_err(|e| {
            VoidCrawlError::RecordingEncodeError(format!("write {}: {e}", file.display()))
        })?;
        let _ = writeln!(concat, "file '{name}'\nduration {:.4}", delay.as_secs_f64());
    }
    // The concat demuxer ignores the final entry's duration unless the last
    // file is repeated, so repeat it.
    if let Some(last) = region.frames.last() {
        let _ = writeln!(concat, "file '{:05}.{ext}'", last.index);
    }
    let list = staging.path().join("frames.txt");
    fs::write(&list, concat).map_err(|e| {
        VoidCrawlError::RecordingEncodeError(format!("write {}: {e}", list.display()))
    })?;

    let codec: &[&str] = match encoding {
        Encoding::Mp4 => &["-c:v", "libx264", "-pix_fmt", "yuv420p"],
        Encoding::WebM => &["-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p"],
        Encoding::Gif => &[],
    };

    let output = Command::new("ffmpeg")
        .arg("-y")
        .args(["-f", "concat", "-safe", "0", "-i"])
        .arg(&list)
        // Odd pixel dimensions are rejected by yuv420p; a selector crop can
        // easily land on one, so round both axes down to even.
        .args(["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"])
        .args(codec)
        .arg(path)
        .output()
        .await
        .map_err(|e| {
            VoidCrawlError::RecordingEncodeError(format!(
                "running ffmpeg: {e} (is it installed and on PATH?)"
            ))
        })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let tail: String = stderr.lines().rev().take(8).collect::<Vec<_>>().join("\n");
        return Err(VoidCrawlError::RecordingEncodeError(format!(
            "ffmpeg exited with {}: {tail}",
            output.status
        )));
    }
    Ok(())
}
