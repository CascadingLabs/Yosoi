//! Screen recording: capture a page as a sequence of timestamped frames,
//! optionally cropped to one or more regions, optionally encoded to an
//! animation or video.
//!
//! This is the moving-picture counterpart to [`Page::screenshot`], and the
//! options deliberately mirror [`ScreenshotOptions`](crate::ScreenshotOptions)
//! — same `viewport`, same `scroll`, same `bbox`, the same browser target
//! crop — so a caller who can screenshot a region can record it by changing
//! one call.
//!
//! # What the engine is, and what that costs
//!
//! Frames come from CDP's `Page.startScreencast` / `Page.screencastFrame`.
//! Three consequences follow from that choice, and callers should know all
//! three before reaching for this module:
//!
//! 1. **Viewport only.** A screencast frame is what's composited on screen.
//!    There is no `full_page: true` equivalent — the CDP surface simply doesn't
//!    offer one — so [`RecordingOptions`] has no `full_page` field. Use
//!    `viewport` to make the visible area bigger, or `scroll` to choose which
//!    part of a long page is on screen when recording starts.
//! 2. **Frames arrive on paint, not on a clock.** Chrome emits a frame when it
//!    swaps one, so a static page yields almost nothing and a busy page yields
//!    bursts. [`RecordingOptions::fps`] is therefore a *ceiling* applied
//!    client-side, never a guarantee. Every [`Frame`] carries its real
//!    [`Frame::offset`] from recording start, so a downstream encoder can
//!    resample honestly instead of pretending the rate was uniform.
//! 3. **It takes the browser's capture lock only when it has to.**
//!
//!    Chrome composites the frontmost tab *of a window*. Tabs opened by
//!    [`BrowserSession::new_page`](crate::BrowserSession::new_page) share one
//!    window, so the moment a sibling tab captures — which foregrounds it —
//!    the recorded tab stops painting and the screencast goes quiet. Measured
//!    on a continuously animating page over 3s:
//!
//!    | tab placement | foregrounded | frames |
//!    |---|---|---|
//!    | shared window | no  | 1 |
//!    | shared window | yes | 27 |
//!    | **own window** | **no** | **28** |
//!
//!    The `--disable-backgrounding-occluded-windows` /
//!    `--disable-renderer-backgrounding` launch flags do not rescue the
//!    shared-window case; occlusion *within* a window is a different
//!    mechanism.
//!
//!    So [`RecordingOptions::foreground`] defaults to `None`, meaning
//!    *detect*: [`Page::alone_in_window`] decides. A shared-window tab
//!    is foregrounded and holds the lock (correct, but serializes capture on
//!    that browser); a tab created by
//!    [`BrowserSession::new_page_in_window`](crate::BrowserSession::new_page_in_window)
//!    does neither and records at full rate concurrently with everything else.
//!    Neither case requires the caller to know any of this.
//!
//!    One sharp edge worth knowing: a plain `new_page` opens its tab in the
//!    *most recently active* window, so creating a page after
//!    `new_page_in_window` can drop it into that window and re-introduce the
//!    contention. Create the recording window last, or check
//!    [`Page::alone_in_window`].
//!
//!    Either way [`RecordingOptions::max_duration`] bounds the damage and
//!    defaults to 30s — an abandoned recording should neither hold the lock
//!    nor stream frames forever.
//!
//! # Regions
//!
//! Unlike a screenshot, which crops to at most one rectangle, a recording
//! can carry several: pass many [`RecordingOptions::selectors`] and each one
//! becomes its own [`RecordedRegion`] with its own cropped frame sequence,
//! all cut from the *same* underlying screencast. Recording three components
//! of a page costs one screencast, not three.
//!
//! Each selector is resolved to a rectangle **once, when recording starts**,
//! and that rectangle is then fixed for the whole recording. An element that
//! moves or resizes mid-recording will drift out of its crop; that is the
//! documented behavior, chosen to match `screenshot(selector: ...)`
//! semantics and to keep the per-frame cost at zero DOM round-trips.
//!
//! # Masks
//!
//! [`RecordingOptions::masks`] paints rectangles solid black in every frame
//! *before* anything is cropped, written, or encoded. It exists because a
//! recording harness has no other seam: between Chrome compositing a frame and
//! that frame hitting disk there is no point at which a downstream package can
//! intervene, so whatever is on screen — a typed password, a key in a settings
//! field, a customer name — is already in the artifact by the time anyone else
//! gets a say.
//!
//! **This module supplies the mechanism, not the judgment.** A mask is a
//! rectangle. There are no classifiers, no presets, no `input[type=password]`
//! special-casing, and nothing here decides what counts as sensitive or whether
//! a finished recording is safe to share. Callers name the regions; the
//! obfuscation harness that orchestrates them lives above this crate.
//! Correspondingly, masking a recording is not a claim that the recording is
//! clean — only that the named rectangles were covered, which
//! [`Recording::masks`] reports exactly.
//!
//! A [`MaskSpec`] is either a literal [`Bbox`] — for a caller that already
//! knows its rectangles and wants no DOM work at all — or a [`BrowserTarget`]
//! to resolve into one, via the same [`Page::resolve_target`] the crop
//! regions use.
//!
//! Unlike regions, selector masks **track**: they are re-resolved on a timer
//! (at most 5 Hz) and each frame is masked with the rectangles current when it
//! was captured. A crop that drifts is a cosmetic problem; a mask that drifts
//! uncovers the thing it was asked to cover, so two geometrically conservative
//! rules apply:
//!
//! * a frame is masked with the **union** of the current and previous tick's
//!   rectangles, so an element caught mid-scroll is covered in both places;
//! * a mask whose selector stops resolving keeps its last known rectangle
//!   rather than uncovering.
//!
//! Neither rule is a risk assessment — both are just "cover more, not less".
//! [`MaskReport`] carries the counts (`unresolved_ticks`, `stale_frames`) so
//! the caller can decide what a stale mask means for their artifact.
//!
//! One honest limitation: the pixels are covered in this process, after Chrome
//! has composited them and after the frame has been decoded here. They never
//! reach disk, an encoder, or a caller — but they do exist in memory first.
//!
//! # Output
//!
//! [`Recording`] always carries the frames. Encoding to GIF or to a video
//! container is opt-in and lives behind cargo features (`encode-gif`,
//! `encode-ffmpeg`), because the frame sequence is the substrate and the
//! container is a policy choice — see [`Encoding`].

use std::{
    fmt, fs,
    io::Cursor,
    num::NonZeroUsize,
    path::{Path, PathBuf},
    result::Result as StdResult,
    sync::Arc,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use base64::{Engine, engine::general_purpose::STANDARD as B64};
use chromiumoxide::{
    Page as CdpPage,
    cdp::browser_protocol::page::{
        EventScreencastFrame, ScreencastFrameAckParams, StartScreencastFormat,
        StartScreencastParams, StopScreencastParams,
    },
    listeners::{EventDelivery, EventListenerConfig, EventOverflowPolicy},
};
use futures::{Stream, StreamExt};
use image::{
    DynamicImage, GenericImageView, ImageFormat, Rgba, RgbaImage, codecs::jpeg::JpegEncoder,
    imageops, load_from_memory_with_format,
};
use serde::Serialize;
use tokio::{
    sync::{Mutex as AsyncMutex, OwnedMutexGuard, oneshot},
    task::{JoinHandle, spawn_blocking},
    time::{Instant as TokioInstant, sleep, sleep_until},
};
use yosoi_types::ByteCount;

use crate::{
    BrowserByteAccounting, BrowserByteAccountingError, BrowserByteDomain,
    BrowserByteMeasurementUnavailableReason, BrowserByteReport, BrowserByteReportError,
    DocumentEpoch, MeasuredBrowserBytes,
    error::{Result, VoidCrawlError},
    page::{Bbox, Page},
    selector::{BrowserTarget, TargetResolution},
    viewport::{ScrollTarget, Viewport},
};

fn unix_millis_now() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}

/// Default frame-rate ceiling: enough to read a UI interaction back, cheap
/// enough that a 30s recording stays in the low hundreds of frames.
pub const DEFAULT_FPS: u8 = 10;
/// Default hard stop. Also the capture-safety bound: a recording on a
/// shared-window tab holds the browser's capture lock, so an abandoned one
/// must not run forever.
pub const DEFAULT_MAX_DURATION: Duration = Duration::from_secs(30);
/// Default in-memory frame cap, independent of duration and fps. At the
/// defaults this is never reached; it bounds a pathological burst.
pub const DEFAULT_MAX_FRAMES: usize = 900;
/// Default JPEG quality for screencast frames.
pub const DEFAULT_QUALITY: u8 = 80;
/// Default outward padding, in CSS pixels, applied to every mask rectangle.
///
/// Antialiased text bleeds a little past its element box; two pixels covers
/// that without visibly eating the layout. Set
/// [`RecordingOptions::mask_pad`] to 0 for an exact rectangle.
pub const DEFAULT_MASK_PAD: u32 = 2;
/// Ceiling on how often tracked masks are re-resolved.
///
/// Each tick costs one
/// `Page::resolve_target` round-trip per tracked mask, so this stays well
/// below the frame rate: it bounds how far an element can move between a
/// resolve and the frame that uses it, and the current∪previous union covers
/// the gap.
pub const MASK_TRACK_HZ: u8 = 5;

fn deadline_after(duration: Duration) -> TokioInstant {
    TokioInstant::now()
        .checked_add(duration)
        .unwrap_or_else(TokioInstant::now)
}

/// Wire format Chrome encodes each screencast frame in.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum FrameFormat {
    /// Lossy, far smaller — the right default for motion.
    Jpeg,
    /// Lossless, much larger. Worth it for pixel-exact diffing of frames.
    Png,
}

impl FrameFormat {
    const fn as_cdp(self) -> StartScreencastFormat {
        match self {
            Self::Jpeg => StartScreencastFormat::Jpeg,
            Self::Png => StartScreencastFormat::Png,
        }
    }

    const fn as_image(self) -> ImageFormat {
        match self {
            Self::Jpeg => ImageFormat::Jpeg,
            Self::Png => ImageFormat::Png,
        }
    }

    /// File extension for a frame written to disk, without the dot.
    pub const fn extension(self) -> &'static str {
        match self {
            Self::Jpeg => "jpg",
            Self::Png => "png",
        }
    }
}

/// An optional post-processing step that turns the frame sequence into a
/// single playable artifact.
///
/// Both variants are feature-gated: a recording's *frames* are always
/// available, but this crate does not carry a codec stack by default.
/// Requesting an encoding whose feature is off is an
/// [`VoidCrawlError::RecordingEncodeError`], not a silent no-op — the frames
/// are still returned on the [`Recording`], so nothing is lost.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Encoding {
    /// Animated GIF, encoded in-process (cargo feature `encode-gif`).
    /// Self-contained and permissively licensed; large files, 256 colors.
    Gif,
    /// H.264 MP4 via an `ffmpeg` binary on PATH (cargo feature
    /// `encode-ffmpeg`). Small files, real video, external runtime
    /// dependency.
    Mp4,
    /// VP9 WebM via an `ffmpeg` binary on PATH (cargo feature
    /// `encode-ffmpeg`).
    WebM,
}

impl Encoding {
    pub const fn extension(self) -> &'static str {
        match self {
            Self::Gif => "gif",
            Self::Mp4 => "mp4",
            Self::WebM => "webm",
        }
    }
}

/// What a mask covers.
///
/// A mask is fundamentally a rectangle; the selector variant is a convenience
/// over that, not a second mechanism. A caller that already knows its
/// rectangles — from a page index, a previous resolve, a human clicking a box
/// — passes [`Fixed`](MaskRegion::Fixed) and this module does no DOM work at
/// all.
#[derive(Debug, Clone)]
pub enum MaskRegion {
    /// A literal viewport-relative rectangle in CSS pixels. Never tracked:
    /// what the caller gave is what gets covered.
    Fixed(Bbox),
    /// Resolved to a rectangle through [`Page::resolve_target`], and by
    /// default re-resolved while recording. A selector that resolves to
    /// nothing, is ambiguous, or is inherently non-visual (`jsonld`/`regex`)
    /// fails the recording before any frame is captured — an unresolvable
    /// mask must never be silently skipped.
    Selector(BrowserTarget),
}

/// One rectangle to paint black in every frame.
#[derive(Debug, Clone)]
pub struct MaskSpec {
    pub region: MaskRegion,
    /// Re-resolve this mask while recording (default `true`; ignored for
    /// [`MaskRegion::Fixed`]). Turning it off pins the mask to where the
    /// element was at the start — cheaper by one CDP round-trip per tick, and
    /// correct only when the element cannot move.
    pub track: bool,
    /// Name for this mask in [`MaskReport`]. Defaults to the selector's name
    /// or value, or `mask{index}`.
    pub label: Option<String>,
}

impl MaskSpec {
    /// Mask a literal rectangle.
    pub const fn bbox(bbox: Bbox) -> Self {
        Self {
            region: MaskRegion::Fixed(bbox),
            track: false,
            label: None,
        }
    }

    /// Mask whatever a selector resolves to, re-resolving while recording.
    pub const fn selector(entry: BrowserTarget) -> Self {
        Self {
            region: MaskRegion::Selector(entry),
            track: true,
            label: None,
        }
    }

    pub const fn with_track(mut self, track: bool) -> Self {
        self.track = track;
        self
    }

    pub fn with_label(mut self, label: impl Into<String>) -> Self {
        self.label = Some(label.into());
        self
    }

    /// Whether this mask is actually re-resolved: a fixed rectangle has
    /// nothing to re-resolve.
    const fn is_tracked(&self) -> bool {
        self.track && matches!(self.region, MaskRegion::Selector(_))
    }
}

/// What one mask actually did, so the caller can judge the artifact.
///
/// This crate covers what it is told to cover and reports the result; whether
/// `unresolved_ticks > 0` means "re-record", "discard", or "fine" is the
/// caller's call, not this module's.
#[derive(Debug, Clone, Serialize)]
pub struct MaskReport {
    pub label: String,
    /// The rectangle as first resolved, in CSS pixels. Later frames may have
    /// been masked with a different (or larger, unioned) rectangle if the mask
    /// was tracked.
    pub bbox: Bbox,
    /// Whether this mask was re-resolved during the recording.
    pub tracked: bool,
    /// Ticks on which re-resolution failed — the element went away, became
    /// hidden, or turned ambiguous. The mask kept its last known rectangle for
    /// those, so it covered *something*; whether it covered the right thing is
    /// unknowable from here.
    pub unresolved_ticks: usize,
    /// Frames captured while the most recent re-resolution had failed.
    pub stale_frames: usize,
}

/// Options for [`Page::record`] and [`Page::start_recording`].
///
/// Mirrors [`ScreenshotOptions`](crate::ScreenshotOptions) field-for-field
/// where the concepts carry over. The differences, all forced by the
/// screencast engine, are called out in the module docs: no `full_page`,
/// `bbox` is viewport-relative, and `selectors` is plural.
#[derive(Debug, Clone)]
pub struct RecordingOptions {
    /// Directory for artifacts — encoded outputs, and frames when
    /// `write_frames` is set. `None` keeps everything in memory.
    pub dir: Option<PathBuf>,
    /// Crop every frame to this region. **Viewport-relative**, unlike
    /// [`ScreenshotOptions::bbox`](crate::ScreenshotOptions::bbox), which is
    /// page-relative: a screencast frame only ever contains the viewport, so
    /// page coordinates outside it have nothing to crop from. Use `scroll`
    /// to bring the region on screen first. Mutually exclusive with
    /// `selectors`.
    pub bbox: Option<Bbox>,
    /// Crop to each of these selectors' resolved rectangles, producing one
    /// [`RecordedRegion`] per selector from a single screencast. Each is
    /// resolved once at start and then held fixed. Mutually exclusive with
    /// `bbox`. A selector that matches nothing, is ambiguous, or is
    /// inherently non-visual (`jsonld`/`regex`) fails the whole recording
    /// before any frame is captured, rather than silently yielding an empty
    /// region.
    pub selectors: Vec<BrowserTarget>,
    /// Rectangles to paint solid black in every frame, before cropping,
    /// writing, or encoding. Orthogonal to `bbox`/`selectors`: masks are not
    /// crops, and combining them is normal — crop to the form, mask the
    /// password field inside it.
    ///
    /// See the module docs on masks for the scope boundary (this is a
    /// mechanism, not a policy), the tracking rules, and the in-memory caveat.
    pub masks: Vec<MaskSpec>,
    /// Outward padding in CSS pixels on every mask rectangle, to swallow
    /// antialiasing at the edges. Defaults to [`DEFAULT_MASK_PAD`].
    pub mask_pad: u32,
    /// Record as this device/viewport, then restore whatever was active
    /// before — even on error. See [`Page::set_viewport`].
    pub viewport: Option<Viewport>,
    /// Scroll here before recording starts, and restore the original scroll
    /// position when it stops. Since the screencast is viewport-only, this
    /// is how you choose *which part* of a long page gets recorded.
    pub scroll: Option<ScrollTarget>,
    /// Frame-rate **ceiling**, applied client-side by dropping frames that
    /// arrive sooner than `1/fps` after the last kept one. Not a floor: see
    /// the module docs on paint-driven delivery. Must be >= 1.
    pub fps: u8,
    /// Hard stop. [`Page::record`] returns after exactly this long; a
    /// [`RecordingHandle`] stops itself at this point even if nothing calls
    /// [`RecordingHandle::stop`], so an abandoned recording can't hold the
    /// browser's capture lock forever.
    pub max_duration: Duration,
    /// In-memory frame cap. Frames past it are counted in
    /// [`Recording::frames_dropped`] rather than growing the heap without
    /// bound.
    pub max_frames: usize,
    /// Wire format for each frame.
    pub format: FrameFormat,
    /// JPEG quality, 0-100. Ignored for [`FrameFormat::Png`].
    pub quality: u8,
    /// Also write every frame to `dir` as `{region}/{index}.{ext}`.
    pub write_frames: bool,
    /// Whether to pin this tab to the foreground — and hold the browser-wide
    /// capture lock — for the recording, until it is stopped or its hard
    /// duration deadline expires.
    ///
    /// `None` (the default) decides automatically, via
    /// [`Page::alone_in_window`]:
    ///
    /// * **Tab shares its window** (as produced by
    ///   [`BrowserSession::new_page`](crate::BrowserSession::new_page)) →
    ///   foreground and lock. Chrome composites only a window's
    ///   frontmost tab, so without this the recording would collect 1 frame in
    ///   3s the moment a sibling captured. Sibling captures block until the
    ///   recording stops.
    /// * **Tab is alone in its window** (see
    ///   [`BrowserSession::new_page_in_window`](crate::BrowserSession::new_page_in_window))
    ///   → neither. Another window taking focus can't occlude it, so it records
    ///   at full rate while the rest of the browser stays free.
    ///
    /// `Some(true)` / `Some(false)` force the choice. Forcing `false` on a
    /// shared-window tab is the one genuinely broken combination — it yields
    /// a near-empty recording — so prefer leaving this `None` and putting the
    /// page in its own window when concurrency matters.
    ///
    /// The auto check costs one `Target.getTargets` and one
    /// `Browser.getWindowForTarget` per page target, once per recording.
    pub foreground: Option<bool>,
    /// Post-processing encodings to produce, each written to `dir`. Requires
    /// `dir` to be set.
    pub encode: Vec<Encoding>,
}

impl Default for RecordingOptions {
    fn default() -> Self {
        Self {
            dir: None,
            bbox: None,
            selectors: Vec::new(),
            masks: Vec::new(),
            mask_pad: DEFAULT_MASK_PAD,
            viewport: None,
            scroll: None,
            fps: DEFAULT_FPS,
            max_duration: DEFAULT_MAX_DURATION,
            max_frames: DEFAULT_MAX_FRAMES,
            format: FrameFormat::Jpeg,
            quality: DEFAULT_QUALITY,
            write_frames: false,
            foreground: None,
            encode: Vec::new(),
        }
    }
}

impl RecordingOptions {
    pub fn with_dir(mut self, dir: impl Into<PathBuf>) -> Self {
        self.dir = Some(dir.into());
        self
    }

    pub const fn with_bbox(mut self, bbox: Bbox) -> Self {
        self.bbox = Some(bbox);
        self
    }

    /// Add one more region to record. Call repeatedly for several regions.
    pub fn with_selector(mut self, selector: BrowserTarget) -> Self {
        self.selectors.push(selector);
        self
    }

    pub fn with_selectors(mut self, selectors: impl IntoIterator<Item = BrowserTarget>) -> Self {
        self.selectors.extend(selectors);
        self
    }

    /// Add one more rectangle to black out. Call repeatedly for several.
    pub fn with_mask(mut self, mask: MaskSpec) -> Self {
        self.masks.push(mask);
        self
    }

    pub fn with_masks(mut self, masks: impl IntoIterator<Item = MaskSpec>) -> Self {
        self.masks.extend(masks);
        self
    }

    pub const fn with_mask_pad(mut self, pad: u32) -> Self {
        self.mask_pad = pad;
        self
    }

    pub fn with_viewport(mut self, viewport: Viewport) -> Self {
        self.viewport = Some(viewport);
        self
    }

    pub const fn with_scroll(mut self, scroll: ScrollTarget) -> Self {
        self.scroll = Some(scroll);
        self
    }

    pub const fn with_fps(mut self, fps: u8) -> Self {
        self.fps = fps;
        self
    }

    pub const fn with_max_duration(mut self, max_duration: Duration) -> Self {
        self.max_duration = max_duration;
        self
    }

    pub const fn with_format(mut self, format: FrameFormat) -> Self {
        self.format = format;
        self
    }

    /// Force the foreground/capture-lock decision instead of letting it be
    /// detected. See [`RecordingOptions::foreground`].
    pub const fn with_foreground(mut self, foreground: bool) -> Self {
        self.foreground = Some(foreground);
        self
    }

    pub fn with_encoding(mut self, encoding: Encoding) -> Self {
        self.encode.push(encoding);
        self
    }

    /// Reject option combinations that can't mean anything, before any
    /// browser state is touched.
    fn validate(&self) -> Result<()> {
        if self.bbox.is_some() && !self.selectors.is_empty() {
            return Err(VoidCrawlError::RecordingError(
                "RecordingOptions: `bbox` and `selectors` are mutually exclusive".into(),
            ));
        }
        if self.fps == 0 {
            return Err(VoidCrawlError::RecordingError(
                "RecordingOptions: `fps` must be at least 1".into(),
            ));
        }
        if self.max_duration.is_zero() {
            return Err(VoidCrawlError::RecordingError(
                "RecordingOptions: `max_duration` must be greater than zero".into(),
            ));
        }
        if self.max_frames == 0 {
            return Err(VoidCrawlError::RecordingError(
                "RecordingOptions: `max_frames` must be at least 1".into(),
            ));
        }
        if !self.encode.is_empty() && self.dir.is_none() {
            return Err(VoidCrawlError::RecordingError(
                "RecordingOptions: `encode` requires `dir` to be set".into(),
            ));
        }
        if self.write_frames && self.dir.is_none() {
            return Err(VoidCrawlError::RecordingError(
                "RecordingOptions: `write_frames` requires `dir` to be set".into(),
            ));
        }
        Ok(())
    }
}

/// One captured frame.
#[derive(Clone, Serialize)]
pub struct Frame {
    /// Position in the sequence, 0-based, after fps throttling.
    pub index: usize,
    /// Real elapsed time from the start of the recording. Frames are *not*
    /// evenly spaced — encode against this, not against `index / fps`.
    pub offset: Duration,
    /// Encoded image bytes in the recording's [`FrameFormat`].
    #[serde(skip)]
    pub data: Vec<u8>,
}

impl Frame {
    /// Exact byte accounting for this retained encoded frame.
    pub fn byte_report(&self) -> StdResult<BrowserByteReport, BrowserByteReportError> {
        BrowserByteReport::from_known_extent(
            BrowserByteDomain::RecordingFrame,
            None,
            ByteCount::try_from_usize(self.data.len())?,
            ByteCount::try_from_usize(self.data.len())?,
        )
    }
}

impl fmt::Debug for Frame {
    /// Hand-written so a frame doesn't dump tens of kilobytes of pixels into
    /// a log line.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Frame")
            .field("index", &self.index)
            .field("offset", &self.offset)
            .field("bytes", &self.data.len())
            .finish()
    }
}

/// One recorded region: the whole viewport, an explicit `bbox`, or one
/// selector's resolved rectangle.
#[derive(Debug, Clone, Serialize)]
pub struct RecordedRegion {
    /// Human-readable name, derived from the selector (its `name`, else its
    /// `value`) or `"viewport"` / `"bbox"`. Also the on-disk subdirectory
    /// name when `write_frames` is set.
    pub label: String,
    /// The rectangle this region was cropped to, or `None` for the full
    /// frame. Resolved once at recording start — see the module docs on
    /// drift.
    pub bbox: Option<Bbox>,
    /// The frames for this region, cropped.
    pub frames: Vec<Frame>,
    /// Encoded artifacts produced for this region, if any.
    pub outputs: Vec<PathBuf>,
    /// File sizes observed immediately after each successful encoder returns,
    /// in the same order as [`Self::outputs`]. Kept private and out of serde:
    /// reports must describe capture-time artifacts, not files mutable by a
    /// caller after this recording is returned.
    #[serde(skip)]
    output_sizes: Vec<ByteCount>,
}

impl RecordedRegion {
    /// Complete, unbounded accounting for all retained encoded frames in this
    /// region. This is a measurement, not a byte-limit policy.
    pub fn byte_report(&self) -> StdResult<BrowserByteReport, BrowserByteReportError> {
        let bytes = checked_frame_bytes(&self.frames)?;
        BrowserByteReport::from_known_extent(BrowserByteDomain::RecordingFrame, None, bytes, bytes)
    }

    /// Complete, unbounded accounting for every successfully encoded artifact
    /// in [`Self::outputs`], in the same order. Sizes were captured when the
    /// encoder completed; this does not read the output paths again.
    pub fn output_byte_reports(&self) -> StdResult<Vec<BrowserByteReport>, BrowserByteReportError> {
        self.output_sizes
            .iter()
            .copied()
            .map(|bytes| {
                BrowserByteReport::from_known_extent(
                    BrowserByteDomain::EncodedRecording,
                    None,
                    bytes,
                    bytes,
                )
            })
            .collect()
    }
}

/// The result of a recording.
#[derive(Debug, Clone, Serialize)]
pub struct Recording {
    /// Wall-clock correlation captured when the screencast started.
    pub started_at_unix_ms: Option<u64>,
    /// Document epoch being shown when recording started.
    pub document_epoch: DocumentEpoch,
    /// One entry per requested region; exactly one (`"viewport"`) when
    /// neither `bbox` nor `selectors` was given.
    pub regions: Vec<RecordedRegion>,
    /// One entry per requested mask, in the order they were given. Empty when
    /// no masks were requested — and an empty list is not a statement that
    /// the recording contains nothing sensitive, only that nothing was asked
    /// to be covered.
    pub masks: Vec<MaskReport>,
    pub format: FrameFormat,
    /// Wall-clock span from screencast start to stop.
    pub duration: Duration,
    /// Frames kept, per region (every region has the same count).
    pub frames_captured: usize,
    /// Frames delivered by Chrome but discarded by bounds or invalid data.
    pub frames_dropped: usize,
    /// Frames discarded by the requested fps ceiling.
    pub frames_dropped_by_rate: usize,
    /// Frames discarded after the requested frame limit was reached.
    pub frames_dropped_by_limit: usize,
    /// Frames discarded by the bounded Chromium listener before they could be
    /// acknowledged or retained.
    pub frames_dropped_by_listener: usize,
    /// Delivered frames whose base64 payload could not be decoded.
    pub frame_decode_failures: usize,
    /// Screencast frame acknowledgements rejected by Chromium.
    pub frame_ack_failures: usize,
    /// Whether the CDP event stream ended before an explicit stop/deadline.
    pub stream_disconnected: bool,
    /// True only when no decode/ack/disconnect or stale-mask failure occurred.
    pub complete: bool,
    /// Original screencast frame dimensions, when at least one frame survived.
    pub frame_size_pixels: Option<(u32, u32)>,
    /// CSS viewport dimensions reported with the first retained frame.
    pub capture_viewport_css: Option<(f64, f64)>,
    /// The page's `devicePixelRatio` at capture time, for translating frame
    /// pixels back to CSS pixels.
    pub device_pixel_ratio: f64,
    /// Whether this recording pinned the tab to the foreground and held the
    /// browser's capture lock — the resolved value of
    /// [`RecordingOptions::foreground`], which is normally auto-detected.
    /// `false` means the recording ran concurrently with the rest of the
    /// browser.
    pub foregrounded: bool,
}

impl Recording {
    /// Complete, unbounded accounting for retained encoded frames across all
    /// regions. This is a measurement, not a byte-limit policy.
    pub fn byte_report(&self) -> StdResult<BrowserByteReport, BrowserByteReportError> {
        let bytes = self
            .regions
            .iter()
            .try_fold(ByteCount::new(0), |total, region| {
                let region_bytes = checked_frame_bytes(&region.frames)?;
                let bytes = total
                    .get()
                    .checked_add(region_bytes.get())
                    .ok_or(BrowserByteAccountingError::Overflow)?;
                Ok::<_, BrowserByteReportError>(ByteCount::new(bytes))
            })?;
        let has_unmeasured_frames =
            self.frames_dropped > 0 || self.frame_decode_failures > 0 || self.stream_disconnected;
        if !has_unmeasured_frames {
            return BrowserByteReport::from_known_extent(
                BrowserByteDomain::RecordingFrame,
                None,
                bytes,
                bytes,
            );
        }
        let zero = ByteCount::new(0);
        let accounting =
            BrowserByteAccounting::new(bytes, bytes, MeasuredBrowserBytes::Known { value: zero })?;
        let unknown = MeasuredBrowserBytes::Unavailable {
            reason: BrowserByteMeasurementUnavailableReason::CaptureEndedEarly,
        };
        BrowserByteReport::truncated(
            BrowserByteDomain::RecordingFrame,
            None,
            accounting,
            unknown,
            unknown,
        )
    }

    /// The measured frame rate actually achieved, which is at most
    /// [`RecordingOptions::fps`] and usually below it on a mostly-static
    /// page. Use this rather than the requested fps when reporting.
    pub fn effective_fps(&self) -> f64 {
        let secs = self.duration.as_secs_f64();
        if secs <= 0.0 {
            return 0.0;
        }
        let frames = f64::from(u32::try_from(self.frames_captured).unwrap_or(u32::MAX));
        frames / secs
    }
}

/// A recording in flight, returned by [`Page::start_recording`] and consumed
/// by [`RecordingHandle::stop`].
///
/// Deliberately holds no reference to the page — `stop` takes one — so the
/// handle can be parked in a registry between two separate calls (an MCP
/// `session_record_start` / `session_record_stop` pair) while the page it
/// belongs to stays behind its own lock. Same shape as [`DownloadCapture`]
/// for the same reason.
///
/// If the handle is dropped without `stop`, the collector task still winds
/// down at `max_duration` and releases anything it held, but the frames are
/// lost.
///
/// [`DownloadCapture`]: crate::DownloadCapture
#[derive(Debug)]
pub struct RecordingHandle {
    collector: JoinHandle<CollectedFrames>,
    stop_tx: Option<oneshot::Sender<()>>,
    /// Live mask geometry, `None` when no masks were requested. Shared with
    /// the tracker task and read by the collector when stamping frames.
    mask_state: Option<Arc<AsyncMutex<MaskState>>>,
    /// The re-resolution task, present only when at least one mask tracks.
    /// Stopped by `mask_stop_tx` and bounded by the same `max_duration` as
    /// the collector, so it cannot outlive the recording.
    mask_tracker: Option<JoinHandle<()>>,
    mask_stop_tx: Option<oneshot::Sender<()>>,
    /// The CDP handle for the recorded tab, kept so `stop` can halt the
    /// screencast without needing the wrapping [`Page`] first. Cheap to
    /// clone: `chromiumoxide::Page` is an `Arc` internally.
    cdp: CdpPage,
    /// Shared with the collector so the hard deadline can release the
    /// browser-wide capture lock even when the caller never calls `stop`.
    capture_guard: Option<Arc<AsyncMutex<Option<OwnedMutexGuard<()>>>>>,
    started: Instant,
    started_at_unix_ms: Option<u64>,
    document_epoch: DocumentEpoch,
    regions: Vec<(String, Option<Bbox>)>,
    restore_scroll: Option<(f64, f64)>,
    /// Three genuinely distinct states: `None` = no override was applied and
    /// nothing needs restoring; `Some(None)` = an override was applied over a
    /// page that had none, so clear it; `Some(Some(v))` = restore `v`.
    #[expect(
        clippy::option_option,
        reason = "outer = did we override, inner = what was there"
    )]
    restore_viewport: Option<Option<Viewport>>,
    /// The resolved foreground decision, reported on the [`Recording`].
    foregrounded: bool,
    opts: RecordingOptions,
}

/// Everything `begin_screencast` sets up, handed to the [`RecordingHandle`].
struct ScreencastStart {
    collector: JoinHandle<CollectedFrames>,
    stop_tx: oneshot::Sender<()>,
    /// Shared with the collector so the hard deadline can release the
    /// browser-wide capture lock even when the caller never calls `stop`.
    capture_guard: Option<Arc<AsyncMutex<Option<OwnedMutexGuard<()>>>>>,
    regions: Vec<(String, Option<Bbox>)>,
    mask_state: Option<Arc<AsyncMutex<MaskState>>>,
    mask_tracker: Option<JoinHandle<()>>,
    mask_stop_tx: Option<oneshot::Sender<()>>,
    restore_scroll: Option<(f64, f64)>,
    started_at: Instant,
    started_at_unix_ms: Option<u64>,
    foregrounded: bool,
}

/// What the collector task hands back.
#[derive(Debug)]
struct CollectedFrames {
    frames: Vec<RawFrame>,
    dropped_by_rate: usize,
    dropped_by_limit: usize,
    dropped_by_listener: usize,
    decode_failures: usize,
    ack_failures: usize,
    stream_disconnected: bool,
}

/// Live mask geometry, shared between the tracker task (which writes) and the
/// collector task (which stamps each kept frame).
#[derive(Debug)]
struct MaskState {
    entries: Vec<MaskEntry>,
}

#[derive(Debug)]
struct MaskEntry {
    label: String,
    /// The rectangle as first resolved, kept for the report.
    initial: Bbox,
    /// Most recent successfully resolved rectangle.
    current: Bbox,
    /// The one before it. Frames are masked with `current ∪ previous` so an
    /// element caught between two ticks is covered at both positions.
    previous: Bbox,
    tracked: bool,
    unresolved_ticks: usize,
    stale_frames: usize,
    /// Whether the most recent tick failed to resolve.
    stale: bool,
}

impl MaskState {
    const fn new(entries: Vec<MaskEntry>) -> Self {
        Self { entries }
    }

    /// The rectangles to apply to a frame captured now, counting a stale mask
    /// against the frame as it goes.
    fn stamp(&mut self) -> Vec<Bbox> {
        self.entries
            .iter_mut()
            .map(|e| {
                if e.stale {
                    e.stale_frames = e.stale_frames.saturating_add(1);
                }
                union(e.current, e.previous)
            })
            .collect()
    }

    fn record_resolved(&mut self, index: usize, bbox: Bbox) {
        if let Some(e) = self.entries.get_mut(index) {
            e.previous = e.current;
            e.current = bbox;
            e.stale = false;
        }
    }

    /// A tick that couldn't resolve keeps the last known rectangle: covering
    /// the wrong place beats uncovering.
    fn record_unresolved(&mut self, index: usize) {
        if let Some(e) = self.entries.get_mut(index) {
            e.unresolved_ticks = e.unresolved_ticks.saturating_add(1);
            e.stale = true;
        }
    }

    fn reports(&self) -> Vec<MaskReport> {
        self.entries
            .iter()
            .map(|e| MaskReport {
                label: e.label.clone(),
                bbox: e.initial,
                tracked: e.tracked,
                unresolved_ticks: e.unresolved_ticks,
                stale_frames: e.stale_frames,
            })
            .collect()
    }
}

/// The smallest rectangle containing both.
fn union(a: Bbox, b: Bbox) -> Bbox {
    let x = a.x.min(b.x);
    let y = a.y.min(b.y);
    let right = a.x.saturating_add(a.width).max(b.x.saturating_add(b.width));
    let bottom =
        a.y.saturating_add(a.height)
            .max(b.y.saturating_add(b.height));
    Bbox {
        x,
        y,
        width: right.saturating_sub(x),
        height: bottom.saturating_sub(y),
    }
}

#[derive(Debug)]
struct RawFrame {
    offset: Duration,
    data: Vec<u8>,
    /// Mask rectangles current when this frame was captured, in CSS pixels.
    /// Stamped per frame rather than fixed for the recording, because a mask
    /// that lags a scrolling element uncovers what it was asked to cover.
    masks: Vec<Bbox>,
    /// Width in CSS pixels of the surface this frame depicts, from the
    /// screencast metadata. Divided into the decoded image width, this gives
    /// the image-pixels-per-CSS-pixel scale needed to place a CSS-pixel crop
    /// rectangle — Chrome may downscale frames, so the ratio is not
    /// necessarily the devicePixelRatio.
    device_width: f64,
    device_height: f64,
}

async fn release_capture_guard(
    capture_guard: Option<Arc<AsyncMutex<Option<OwnedMutexGuard<()>>>>>,
) {
    if let Some(capture_guard) = capture_guard {
        capture_guard.lock().await.take();
    }
}

impl RecordingHandle {
    /// Stop the recording, restore the page's viewport and scroll position,
    /// and post-process the collected frames.
    ///
    /// `page` must be the page this recording was started on; passing a
    /// different one restores the wrong viewport and scroll position.
    pub async fn stop(mut self, page: &Page) -> Result<Recording> {
        let duration = self.started.elapsed();
        let capture_guard = self.capture_guard.take();

        // Signal the collector first so it stops acking, then tell Chrome to
        // stop producing. Both are best-effort: a page that navigated or
        // crashed mid-recording should still yield whatever was collected.
        if let Some(tx) = self.stop_tx.take() {
            let _ = tx.send(());
        }
        if let Some(tx) = self.mask_stop_tx.take() {
            let _ = tx.send(());
        }
        let _ = self.cdp.execute(StopScreencastParams::default()).await;

        let collected = self
            .collector
            .await
            .map_err(|e| VoidCrawlError::RecordingError(format!("collector task: {e}")))?;
        // Joined before the reports are read so the tracker can't be mid-tick
        // when the counts are taken.
        if let Some(tracker) = self.mask_tracker.take() {
            let _ = tracker.await;
        }
        let mask_reports = match &self.mask_state {
            Some(state) => state.lock().await.reports(),
            None => Vec::new(),
        };

        // Restore page state before any CPU-bound post-processing, so the
        // tab is usable again as early as possible.
        if let Some((x, y)) = self.restore_scroll {
            let _ = page
                .evaluate_js(&format!("window.scrollTo({x}, {y})"))
                .await;
        }
        if let Some(prev) = self.restore_viewport.take() {
            let _ = match prev {
                Some(v) => page.set_viewport(v).await,
                None => page.clear_viewport().await,
            };
        }
        let dpr = page
            .evaluate_js("window.devicePixelRatio")
            .await
            .ok()
            .and_then(|v| v.as_f64())
            .unwrap_or(1.0);

        // Released here rather than at end-of-scope so that, in the opt-in
        // `foreground` mode, other tabs can capture again as soon as this tab
        // is restored — without waiting on cropping and encoding.
        release_capture_guard(capture_guard.as_ref().map(Arc::clone)).await;
        drop(capture_guard);

        let mut recording = build_regions(
            collected,
            &self.regions,
            mask_reports,
            &self.opts,
            duration,
            dpr,
            self.foregrounded,
            self.started_at_unix_ms,
            self.document_epoch,
        )
        .await?;

        if let Some(dir) = self.opts.dir.clone() {
            write_artifacts(&mut recording, &dir, &self.opts).await?;
        }
        Ok(recording)
    }
}

impl Page {
    /// Record this page for [`RecordingOptions::max_duration`] and return the
    /// frames.
    ///
    /// The one-shot form, and the direct analogue of [`Page::screenshot`]:
    /// it starts a screencast, waits the full duration, and stops. Use
    /// [`Page::start_recording`] instead when you need to *drive* the page
    /// (click, type, navigate) while it records.
    ///
    /// ```no_run
    /// # async fn f(page: &void_crawl_core::Page) -> void_crawl_core::Result<()> {
    /// use std::time::Duration;
    ///
    /// use void_crawl_core::RecordingOptions;
    ///
    /// let rec =
    ///     page.record(RecordingOptions::default().with_max_duration(Duration::from_secs(5))).await?;
    /// println!("{} frames at {:.1} fps", rec.frames_captured, rec.effective_fps());
    /// # Ok(()) }
    /// ```
    pub async fn record(&self, opts: RecordingOptions) -> Result<Recording> {
        let duration = opts.max_duration;
        let handle = self.start_recording(opts).await?;
        sleep_until(deadline_after(duration)).await;
        handle.stop(self).await
    }

    /// Begin recording and return a handle to stop it.
    ///
    /// Drive the page normally in between — clicks, typing, and navigation
    /// all keep recording.
    ///
    /// By default the tab is pinned to the foreground and holds the
    /// browser-wide capture lock until [`RecordingHandle::stop`] or the hard
    /// duration deadline, so sibling tabs can't capture meanwhile. See
    /// [`RecordingOptions::foreground`] for how to record concurrently instead.
    ///
    /// ```no_run
    /// # async fn f(page: &void_crawl_core::Page) -> void_crawl_core::Result<()> {
    /// use void_crawl_core::RecordingOptions;
    ///
    /// let rec = page.start_recording(RecordingOptions::default()).await?;
    /// page.click_by_role("button", "Play", 0, false).await?;
    /// let out = rec.stop(page).await?;
    /// # Ok(()) }
    /// ```
    pub async fn start_recording(&self, opts: RecordingOptions) -> Result<RecordingHandle> {
        opts.validate()?;
        let document_epoch = self.top_level_document_scope().await?.epoch;

        // One-shot viewport override, snapshotted for exact restore — same
        // leak-proofing as `screenshot`, and doubly important here because a
        // recording lives long enough for another caller to notice.
        let restore_viewport = if let Some(ref viewport) = opts.viewport {
            let prev = self.current_viewport();
            self.set_viewport(viewport.clone()).await?;
            Some(prev)
        } else {
            None
        };

        // From here on, any failure has to undo the viewport override before
        // returning, so the work is factored into a closure-like block.
        let started = self.begin_screencast(&opts).await;
        match started {
            Ok(started) => Ok(RecordingHandle {
                collector: started.collector,
                stop_tx: Some(started.stop_tx),
                mask_state: started.mask_state,
                mask_tracker: started.mask_tracker,
                mask_stop_tx: started.mask_stop_tx,
                cdp: self.cdp().clone(),
                capture_guard: started.capture_guard,
                started: started.started_at,
                started_at_unix_ms: started.started_at_unix_ms,
                document_epoch,
                regions: started.regions,
                restore_scroll: started.restore_scroll,
                restore_viewport,
                foregrounded: started.foregrounded,
                opts,
            }),
            Err(e) => {
                if let Some(prev) = restore_viewport {
                    let _ = match prev {
                        Some(v) => self.set_viewport(v).await,
                        None => self.clear_viewport().await,
                    };
                }
                Err(e)
            }
        }
    }

    /// Scroll, resolve regions, take the capture lock, and start the CDP
    /// screencast plus its collector task.
    async fn begin_screencast(&self, opts: &RecordingOptions) -> Result<ScreencastStart> {
        let restore_scroll = match opts.scroll {
            Some(target) => {
                let prev = self.scroll_position().await?;
                self.scroll_to(target).await?;
                Some(prev)
            }
            None => None,
        };

        // Resolve every selector to a fixed rectangle *before* the screencast
        // starts, so a bad selector fails fast instead of after N seconds of
        // capture. Viewport-relative, matching the frames they'll crop.
        let regions = self.resolve_regions(opts).await?;

        // Same fail-fast rule, and for a stronger reason: a mask that can't be
        // resolved is not a missing crop, it's an uncovered region in an
        // artifact the caller believes is covered.
        let mask_state = self.resolve_masks(opts).await?;

        // A tab sharing its window stops painting the instant a sibling takes
        // focus, so it must hold the foreground (and therefore the lock) for
        // the whole recording. A tab alone in its window can't be occluded
        // that way and needs neither. When the check itself fails, assume the
        // constraining case: a slow recording beats an empty one.
        let foreground = match opts.foreground {
            Some(explicit) => explicit,
            None => !self.alone_in_window().await.unwrap_or(false),
        };

        let capture_guard = if foreground {
            let guard = self.capture_lock().lock_owned().await;
            self.cdp()
                .bring_to_front()
                .await
                .map_err(|e| VoidCrawlError::RecordingError(format!("bring to front: {e}")))?;
            Some(Arc::new(AsyncMutex::new(Some(guard))))
        } else {
            None
        };

        let events = self
            .cdp()
            .event_listener::<EventScreencastFrame>(EventListenerConfig::new(
                NonZeroUsize::new(opts.max_frames).ok_or_else(|| {
                    VoidCrawlError::RecordingError(
                        "screencast listener capacity must be positive".into(),
                    )
                })?,
                EventOverflowPolicy::DropNewest,
            ))
            .await
            .map_err(|e| VoidCrawlError::RecordingError(format!("screencast listener: {e}")))?;

        let mut params = StartScreencastParams::builder().format(opts.format.as_cdp());
        if matches!(opts.format, FrameFormat::Jpeg) {
            params = params.quality(i64::from(opts.quality));
        }
        self.cdp()
            .execute(params.build())
            .await
            .map_err(|e| VoidCrawlError::RecordingError(format!("startScreencast: {e}")))?;

        let started_at = Instant::now();
        let started_at_unix_ms = unix_millis_now();
        let (stop_tx, stop_rx) = oneshot::channel();
        let collector = spawn_collector(
            self.cdp().clone(),
            events,
            stop_rx,
            started_at,
            opts.fps,
            opts.max_frames,
            opts.max_duration,
            mask_state.clone(),
            capture_guard.clone(),
        );

        // Only worth a task when something can actually move: a recording of
        // fixed rectangles pays nothing for tracking it doesn't use.
        let tracked: Vec<(usize, BrowserTarget)> = opts
            .masks
            .iter()
            .enumerate()
            .filter(|(_, m)| m.is_tracked())
            .filter_map(|(i, m)| match &m.region {
                MaskRegion::Selector(entry) => Some((i, entry.clone())),
                MaskRegion::Fixed(_) => None,
            })
            .collect();
        let (mask_tracker, mask_stop_tx) = match (&mask_state, tracked.is_empty()) {
            (Some(state), false) => {
                let (tx, rx) = oneshot::channel();
                let interval = Duration::from_secs_f64(1.0 / f64::from(MASK_TRACK_HZ.max(1)));
                let task = spawn_mask_tracker(
                    self.clone_handle(),
                    tracked,
                    Arc::clone(state),
                    interval,
                    rx,
                    opts.max_duration,
                );
                (Some(task), Some(tx))
            }
            _ => (None, None),
        };

        Ok(ScreencastStart {
            collector,
            stop_tx,
            capture_guard,
            regions,
            mask_state,
            mask_tracker,
            mask_stop_tx,
            restore_scroll,
            started_at,
            started_at_unix_ms,
            foregrounded: foreground,
        })
    }

    /// Resolve every mask to a starting rectangle, or fail the recording.
    async fn resolve_masks(
        &self,
        opts: &RecordingOptions,
    ) -> Result<Option<Arc<AsyncMutex<MaskState>>>> {
        if opts.masks.is_empty() {
            return Ok(None);
        }

        let mut entries = Vec::with_capacity(opts.masks.len());
        for (i, mask) in opts.masks.iter().enumerate() {
            let (label, bbox) = match &mask.region {
                MaskRegion::Fixed(bbox) => (
                    mask.label.clone().unwrap_or_else(|| format!("mask{i}")),
                    *bbox,
                ),
                MaskRegion::Selector(entry) => {
                    if !entry.supports_geometry() {
                        return Err(VoidCrawlError::UnsupportedVisualTarget);
                    }
                    let label = mask
                        .label
                        .clone()
                        .unwrap_or_else(|| format!("mask_{}", region_label(entry, i)));
                    let bbox = match self.resolve_target(entry).await? {
                        TargetResolution::Resolved { bbox } => bbox,
                        TargetResolution::Empty { reason } => {
                            return Err(VoidCrawlError::ElementNotVisible(format!(
                                "recording mask {label:?}: {reason}"
                            )));
                        }
                        TargetResolution::Ambiguous { reason, .. } => {
                            return Err(VoidCrawlError::AmbiguousSelector(format!(
                                "recording mask {label:?}: {reason}"
                            )));
                        }
                    };
                    (label, bbox)
                }
            };
            entries.push(MaskEntry {
                label,
                initial: bbox,
                current: bbox,
                previous: bbox,
                tracked: mask.is_tracked(),
                unresolved_ticks: 0,
                stale_frames: 0,
                stale: false,
            });
        }
        Ok(Some(Arc::new(AsyncMutex::new(MaskState::new(entries)))))
    }

    /// Turn `bbox` / `selectors` / neither into the labeled crop rectangles
    /// the frames will be cut with.
    async fn resolve_regions(
        &self,
        opts: &RecordingOptions,
    ) -> Result<Vec<(String, Option<Bbox>)>> {
        if let Some(bbox) = opts.bbox {
            return Ok(vec![("bbox".to_string(), Some(bbox))]);
        }
        if opts.selectors.is_empty() {
            return Ok(vec![("viewport".to_string(), None)]);
        }

        let mut regions = Vec::with_capacity(opts.selectors.len());
        for (i, entry) in opts.selectors.iter().enumerate() {
            if !entry.supports_geometry() {
                return Err(VoidCrawlError::UnsupportedVisualTarget);
            }
            let label = region_label(entry, i);
            match self.resolve_target(entry).await? {
                TargetResolution::Resolved { bbox } => regions.push((label, Some(bbox))),
                TargetResolution::Empty { reason } => {
                    return Err(VoidCrawlError::ElementNotVisible(format!(
                        "recording region {label:?}: {reason}"
                    )));
                }
                TargetResolution::Ambiguous { reason, .. } => {
                    return Err(VoidCrawlError::AmbiguousSelector(format!(
                        "recording region {label:?}: {reason}"
                    )));
                }
            }
        }
        Ok(regions)
    }
}

/// A stable, filesystem-safe name for a region.
fn region_label(entry: &BrowserTarget, index: usize) -> String {
    let raw = entry
        .name
        .as_deref()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or(entry.value.as_str());
    let cleaned: String = raw
        .trim()
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect();
    let trimmed = cleaned.trim_matches('_');
    if trimmed.is_empty() {
        format!("region{index}")
    } else {
        // Keep labels short enough to stay well inside filename limits even
        // when a CSS selector is long.
        let short: String = trimmed.chars().take(48).collect();
        format!("{index}_{short}")
    }
}

/// Drain screencast events until stopped, throttled to `fps`.
///
/// Every frame is acked immediately whether or not it's kept: Chrome pauses
/// the screencast until the previous frame is acknowledged, so skipping an
/// ack for a throttled-away frame would stall the whole stream.
#[allow(clippy::too_many_arguments)]
fn spawn_collector(
    cdp: CdpPage,
    mut events: impl Stream<Item = EventDelivery<EventScreencastFrame>> + Unpin + Send + 'static,
    stop_rx: oneshot::Receiver<()>,
    started: Instant,
    fps: u8,
    max_frames: usize,
    max_duration: Duration,
    mask_state: Option<Arc<AsyncMutex<MaskState>>>,
    capture_guard: Option<Arc<AsyncMutex<Option<OwnedMutexGuard<()>>>>>,
) -> JoinHandle<CollectedFrames> {
    let min_gap = Duration::from_secs_f64(1.0 / f64::from(fps));
    tokio::spawn(async move {
        let mut frames: Vec<RawFrame> = Vec::new();
        let mut dropped_by_rate = 0usize;
        let mut dropped_by_limit = 0usize;
        let mut dropped_by_listener = 0usize;
        let mut decode_failures = 0usize;
        let mut ack_failures = 0usize;
        let mut stream_disconnected = false;
        let mut last_kept: Option<Instant> = None;
        let mut stop_rx = stop_rx;
        // The hard stop is enforced here too, not just by `record`, so a
        // handle that is never stopped still releases the browser.
        let deadline = sleep_until(deadline_after(max_duration));
        tokio::pin!(deadline);

        loop {
            let event = tokio::select! {
                biased;
                _ = &mut stop_rx => break,
                () = &mut deadline => {
                    // The collector owns the hard deadline. Stop Chrome and
                    // release the shared-window lock here so an abandoned
                    // handle cannot block the browser forever.
                    let _ = cdp.execute(StopScreencastParams::default()).await;
                    if let Some(guard) = &capture_guard {
                        guard.lock().await.take();
                    }
                    break;
                }
                event = events.next() => event,
            };
            let Some(delivery) = event else {
                stream_disconnected = true;
                break;
            };
            let event = match delivery {
                EventDelivery::Event(event) => event,
                EventDelivery::Lagged { dropped } => {
                    let dropped = usize::try_from(dropped.get()).unwrap_or(usize::MAX);
                    dropped_by_listener = dropped_by_listener.saturating_add(dropped);
                    continue;
                }
            };

            if cdp
                .execute(ScreencastFrameAckParams::new(event.session_id))
                .await
                .is_err()
            {
                ack_failures = ack_failures.saturating_add(1);
            }

            let now = Instant::now();
            if frames.len() >= max_frames {
                dropped_by_limit = dropped_by_limit.saturating_add(1);
                continue;
            }
            if let Some(last) = last_kept
                && now.duration_since(last) < min_gap
            {
                dropped_by_rate = dropped_by_rate.saturating_add(1);
                continue;
            }

            let encoded: &str = event.data.as_ref();
            match B64.decode(encoded) {
                Ok(data) => {
                    last_kept = Some(now);
                    // Stamped here, at capture time, rather than read once at
                    // the end: the whole point of tracking is that the frame
                    // is masked with where the element was when it painted.
                    let masks = match &mask_state {
                        Some(state) => state.lock().await.stamp(),
                        None => Vec::new(),
                    };
                    frames.push(RawFrame {
                        offset: now.duration_since(started),
                        data,
                        masks,
                        device_width: event.metadata.device_width,
                        device_height: event.metadata.device_height,
                    });
                }
                // A frame that doesn't decode is a lost frame, not a lost
                // recording.
                Err(_) => decode_failures = decode_failures.saturating_add(1),
            }
        }

        CollectedFrames {
            frames,
            dropped_by_rate,
            dropped_by_limit,
            dropped_by_listener,
            decode_failures,
            ack_failures,
            stream_disconnected,
        }
    })
}

/// Re-resolve tracked masks on a timer until stopped.
///
/// Runs on a second [`Page`] handle over the same tab, so the caller keeps
/// full use of theirs while a recording is in flight. Bounded by the same
/// `max_duration` as the collector: a handle that is never stopped must not
/// leave a task issuing CDP calls against the tab forever.
fn spawn_mask_tracker(
    page: Page,
    tracked: Vec<(usize, BrowserTarget)>,
    state: Arc<AsyncMutex<MaskState>>,
    interval: Duration,
    stop_rx: oneshot::Receiver<()>,
    max_duration: Duration,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        let mut stop_rx = stop_rx;
        let deadline = sleep_until(deadline_after(max_duration));
        tokio::pin!(deadline);

        loop {
            tokio::select! {
                biased;
                _ = &mut stop_rx => break,
                () = &mut deadline => break,
                // EVENT_DRIVEN_SLEEP_APPROVED: Tracked-mask refresh cadence is intrinsically periodic recording behavior with no browser invalidation event.
                () = sleep(interval) => {}
            }

            for (index, entry) in &tracked {
                match page.resolve_target(entry).await {
                    Ok(TargetResolution::Resolved { bbox }) => {
                        state.lock().await.record_resolved(*index, bbox);
                    }
                    // Empty, ambiguous, or a failed round-trip all mean the
                    // same thing here: this tick produced no rectangle, so
                    // keep covering where it was and count it.
                    _ => state.lock().await.record_unresolved(*index),
                }
            }
        }
    })
}

/// Mask, then cut each region's frames out of the shared raw frame sequence.
#[allow(clippy::too_many_arguments)]
async fn build_regions(
    collected: CollectedFrames,
    regions: &[(String, Option<Bbox>)],
    masks: Vec<MaskReport>,
    opts: &RecordingOptions,
    duration: Duration,
    device_pixel_ratio: f64,
    foregrounded: bool,
    started_at_unix_ms: Option<u64>,
    document_epoch: DocumentEpoch,
) -> Result<Recording> {
    let frames_captured = collected.frames.len();
    let frames_dropped_by_rate = collected.dropped_by_rate;
    let frames_dropped_by_limit = collected.dropped_by_limit;
    let frames_dropped_by_listener = collected.dropped_by_listener;
    let frame_decode_failures = collected.decode_failures;
    let frame_ack_failures = collected.ack_failures;
    let stream_disconnected = collected.stream_disconnected;
    let frames_dropped = frames_dropped_by_rate
        .saturating_add(frames_dropped_by_limit)
        .saturating_add(frames_dropped_by_listener)
        .saturating_add(frame_decode_failures);
    let frame_size_pixels = collected
        .frames
        .first()
        .and_then(|frame| image::load_from_memory(&frame.data).ok())
        .map(|image| image.dimensions());
    let capture_viewport_css = collected
        .frames
        .first()
        .map(|frame| (frame.device_width, frame.device_height));
    let complete = frame_decode_failures == 0
        && frame_ack_failures == 0
        && frames_dropped_by_listener == 0
        && !stream_disconnected
        && masks.iter().all(|mask| mask.stale_frames == 0);
    let regions_spec: Vec<(String, Option<Bbox>)> = regions.to_vec();
    let format = opts.format;
    let quality = opts.quality;
    let mask_pad = opts.mask_pad;

    // Decoding and re-encoding every frame for every region is CPU-bound and
    // can run to hundreds of megapixels; keep it off the async runtime's
    // worker threads.
    let built = spawn_blocking(move || {
        // Masking runs first and in place, so every region — and every
        // artifact written from one — is cut from an already-covered frame.
        // There is no ordering in which a region could see the original.
        let mut frames = collected.frames;
        mask_raw_frames(&mut frames, mask_pad, format, quality)?;
        crop_regions(&frames, &regions_spec, format, quality)
    })
    .await
    .map_err(|e| VoidCrawlError::RecordingError(format!("crop task: {e}")))??;

    Ok(Recording {
        started_at_unix_ms,
        document_epoch,
        regions: built,
        masks,
        format,
        duration,
        frames_captured,
        frames_dropped,
        frames_dropped_by_rate,
        frames_dropped_by_limit,
        frames_dropped_by_listener,
        frame_decode_failures,
        frame_ack_failures,
        stream_disconnected,
        complete,
        frame_size_pixels,
        capture_viewport_css,
        device_pixel_ratio,
        foregrounded,
    })
}

/// Paint every frame's mask rectangles solid black, in place.
///
/// The one pass in this module that must not degrade: a frame that fails to
/// decode fails the whole recording rather than being passed through
/// uncovered. Costs one decode + re-encode per frame — but only when masks
/// were requested, and once per frame rather than once per frame per region.
fn mask_raw_frames(raw: &mut [RawFrame], pad: u32, format: FrameFormat, quality: u8) -> Result<()> {
    for frame in raw.iter_mut() {
        if frame.masks.is_empty() {
            continue;
        }
        let img = load_from_memory_with_format(&frame.data, format.as_image()).map_err(|e| {
            VoidCrawlError::RecordingError(format!("decode frame for masking: {e}"))
        })?;
        let scale = if frame.device_width > 0.0 {
            f64::from(img.width()) / frame.device_width
        } else {
            1.0
        };
        let mut rgba = img.to_rgba8();
        mask_image(&mut rgba, &frame.masks, scale, pad);
        frame.data = encode_image(&DynamicImage::ImageRgba8(rgba), format, quality)?;
    }
    Ok(())
}

/// Fill each CSS-pixel rectangle with opaque black, scaled into frame pixels
/// and clamped to the frame.
fn mask_image(img: &mut RgbaImage, masks: &[Bbox], scale: f64, pad: u32) {
    let (img_w, img_h) = img.dimensions();
    let black = Rgba([0, 0, 0, 255]);
    for mask in masks {
        // Pad in CSS pixels, before scaling, so the option means the same
        // thing whatever the device pixel ratio is.
        let padded = Bbox {
            x: mask.x.saturating_sub(pad),
            y: mask.y.saturating_sub(pad),
            width: mask.width.saturating_add(pad.saturating_mul(2)),
            height: mask.height.saturating_add(pad.saturating_mul(2)),
        };
        let Some((x, y, w, h)) = scale_rect(padded, scale, img_w, img_h) else {
            continue;
        };
        for yy in y..y.saturating_add(h) {
            for xx in x..x.saturating_add(w) {
                img.put_pixel(xx, yy, black);
            }
        }
    }
}

/// Scale a CSS-pixel rectangle into frame pixels and clamp it to the frame.
/// `None` when nothing of it lands inside — Chrome may downscale frames, so
/// the ratio is the decoded width over the metadata `deviceWidth`, not the
/// devicePixelRatio.
fn scaled_pixel(value: f64) -> u32 {
    if !value.is_finite() || value <= 0.0 {
        return 0;
    }
    if value >= f64::from(u32::MAX) {
        return u32::MAX;
    }
    value.round().to_string().parse().unwrap_or(u32::MAX)
}

fn scale_rect(bbox: Bbox, scale: f64, img_w: u32, img_h: u32) -> Option<(u32, u32, u32, u32)> {
    let (x, y, w, h) = (
        scaled_pixel(f64::from(bbox.x) * scale),
        scaled_pixel(f64::from(bbox.y) * scale),
        scaled_pixel(f64::from(bbox.width) * scale),
        scaled_pixel(f64::from(bbox.height) * scale),
    );
    if x >= img_w || y >= img_h || w == 0 || h == 0 {
        return None;
    }
    Some((
        x,
        y,
        w.min(img_w.saturating_sub(x)),
        h.min(img_h.saturating_sub(y)),
    ))
}

fn checked_frame_bytes(frames: &[Frame]) -> StdResult<ByteCount, BrowserByteReportError> {
    frames.iter().try_fold(ByteCount::new(0), |total, frame| {
        let frame_bytes = ByteCount::try_from_usize(frame.data.len())?;
        let bytes = total
            .get()
            .checked_add(frame_bytes.get())
            .ok_or(BrowserByteAccountingError::Overflow)?;
        Ok(ByteCount::new(bytes))
    })
}

fn crop_regions(
    raw: &[RawFrame],
    regions: &[(String, Option<Bbox>)],
    format: FrameFormat,
    quality: u8,
) -> Result<Vec<RecordedRegion>> {
    let mut out = Vec::with_capacity(regions.len());
    for (label, bbox) in regions {
        let frames = match bbox {
            // No crop: hand the original bytes straight through, so an
            // uncropped recording never pays a decode.
            None => raw
                .iter()
                .enumerate()
                .map(|(index, f)| Frame {
                    index,
                    offset: f.offset,
                    data: f.data.clone(),
                })
                .collect(),
            Some(bbox) => {
                let mut frames = Vec::with_capacity(raw.len());
                for (index, f) in raw.iter().enumerate() {
                    let data = crop_frame(f, *bbox, format, quality)?;
                    frames.push(Frame {
                        index,
                        offset: f.offset,
                        data,
                    });
                }
                frames
            }
        };
        out.push(RecordedRegion {
            label: label.clone(),
            bbox: *bbox,
            frames,
            outputs: Vec::new(),
            output_sizes: Vec::new(),
        });
    }
    Ok(out)
}

/// Crop one frame to a CSS-pixel rectangle.
///
/// The frame's pixel dimensions need not match its CSS dimensions — Chrome
/// scales screencast output — so the rectangle is scaled by the ratio of the
/// decoded width to the metadata's `deviceWidth` before cropping. A region
/// partly outside the frame is clamped rather than erroring: a recording
/// where an element scrolls half out of view should still produce frames.
fn crop_frame(raw: &RawFrame, bbox: Bbox, format: FrameFormat, quality: u8) -> Result<Vec<u8>> {
    let img = load_from_memory_with_format(&raw.data, format.as_image())
        .map_err(|e| VoidCrawlError::RecordingError(format!("decode frame: {e}")))?;

    let scale = if raw.device_width > 0.0 {
        f64::from(img.width()) / raw.device_width
    } else {
        1.0
    };
    let (img_w, img_h) = img.dimensions();

    let (x, y, w, h) = (
        scaled_pixel(f64::from(bbox.x) * scale),
        scaled_pixel(f64::from(bbox.y) * scale),
        scaled_pixel(f64::from(bbox.width) * scale),
        scaled_pixel(f64::from(bbox.height) * scale),
    );
    let x = x.min(img_w.saturating_sub(1));
    let y = y.min(img_h.saturating_sub(1));
    let w = w.min(img_w.saturating_sub(x)).max(1);
    let h = h.min(img_h.saturating_sub(y)).max(1);

    let cropped = imageops::crop_imm(&img, x, y, w, h).to_image();
    encode_image(&DynamicImage::ImageRgba8(cropped), format, quality)
}

fn encode_image(img: &DynamicImage, format: FrameFormat, quality: u8) -> Result<Vec<u8>> {
    let mut buf = Vec::new();
    match format {
        FrameFormat::Jpeg => {
            // JPEG has no alpha channel; go through RGB8 explicitly rather
            // than letting the encoder reject an RGBA buffer.
            let rgb = img.to_rgb8();
            let mut encoder = JpegEncoder::new_with_quality(&mut buf, quality.clamp(1, 100));
            encoder
                .encode_image(&rgb)
                .map_err(|e| VoidCrawlError::RecordingError(format!("encode jpeg: {e}")))?;
        }
        FrameFormat::Png => {
            img.write_to(&mut Cursor::new(&mut buf), ImageFormat::Png)
                .map_err(|e| VoidCrawlError::RecordingError(format!("encode png: {e}")))?;
        }
    }
    Ok(buf)
}

/// Write frames and/or encoded artifacts to `dir`.
async fn write_artifacts(
    recording: &mut Recording,
    dir: &Path,
    opts: &RecordingOptions,
) -> Result<()> {
    fs::create_dir_all(dir)
        .map_err(|e| VoidCrawlError::RecordingError(format!("create {}: {e}", dir.display())))?;

    for region in &mut recording.regions {
        if opts.write_frames {
            let region_dir = dir.join(&region.label);
            fs::create_dir_all(&region_dir).map_err(|e| {
                VoidCrawlError::RecordingError(format!("create {}: {e}", region_dir.display()))
            })?;
            for frame in &region.frames {
                let path =
                    region_dir.join(format!("{:05}.{}", frame.index, opts.format.extension()));
                fs::write(&path, &frame.data).map_err(|e| {
                    VoidCrawlError::RecordingError(format!("write {}: {e}", path.display()))
                })?;
            }
        }

        for encoding in &opts.encode {
            let path = dir.join(format!("{}.{}", region.label, encoding.extension()));
            encode_region(region, *encoding, &path, opts).await?;
            let size = fs::metadata(&path)
                .map_err(|e| {
                    VoidCrawlError::RecordingEncodeError(format!(
                        "stat encoded output {}: {e}",
                        path.display()
                    ))
                })?
                .len();
            region.outputs.push(path);
            region.output_sizes.push(ByteCount::new(size));
        }
    }
    Ok(())
}

#[cfg_attr(
    not(any(feature = "encode-gif", feature = "encode-ffmpeg")),
    expect(
        unused_variables,
        clippy::unused_async,
        reason = "every encoder branch is feature-gated off in this build"
    )
)]
async fn encode_region(
    region: &RecordedRegion,
    encoding: Encoding,
    path: &Path,
    opts: &RecordingOptions,
) -> Result<()> {
    match encoding {
        Encoding::Gif => {
            #[cfg(feature = "encode-gif")]
            {
                let frames = region.frames.clone();
                let format = opts.format;
                let path = path.to_path_buf();
                spawn_blocking(move || encoders::gif(&frames, format, &path))
                    .await
                    .map_err(|e| VoidCrawlError::RecordingEncodeError(format!("gif task: {e}")))?
            }
            #[cfg(not(feature = "encode-gif"))]
            Err(VoidCrawlError::RecordingEncodeError(
                "GIF encoding requires the `encode-gif` cargo feature; the frames are still \
                 available on the returned Recording"
                    .into(),
            ))
        }
        Encoding::Mp4 | Encoding::WebM => {
            #[cfg(feature = "encode-ffmpeg")]
            {
                encoders::ffmpeg(region, encoding, path, opts).await
            }
            #[cfg(not(feature = "encode-ffmpeg"))]
            Err(VoidCrawlError::RecordingEncodeError(format!(
                "{} encoding requires the `encode-ffmpeg` cargo feature and an ffmpeg binary on \
                 PATH; the frames are still available on the returned Recording",
                encoding.extension()
            )))
        }
    }
}

#[cfg(any(feature = "encode-gif", feature = "encode-ffmpeg"))]
mod encoders;

#[cfg(test)]
#[path = "recording_partial_failure_tests.rs"]
mod partial_failure_tests;

#[cfg(test)]
#[allow(clippy::unwrap_used, reason = "test module")]
mod tests {
    use super::*;
    use crate::selector::BrowserTargetKind;

    fn bbox(x: u32, y: u32, width: u32, height: u32) -> Bbox {
        Bbox {
            x,
            y,
            width,
            height,
        }
    }

    /// A white canvas, so any black pixel is unambiguously ours.
    fn canvas(w: u32, h: u32) -> RgbaImage {
        RgbaImage::from_pixel(w, h, Rgba([255, 255, 255, 255]))
    }

    fn is_black(img: &RgbaImage, x: u32, y: u32) -> bool {
        img.get_pixel(x, y).0 == [0, 0, 0, 255]
    }

    #[tokio::test]
    async fn byte_reports_count_retained_frames_per_region_and_across_regions() {
        let first = b"first frame".to_vec();
        let second = b"a longer second frame".to_vec();
        let expected_region = u64::try_from(first.len() + second.len()).unwrap();
        let mut recording = build_regions(
            CollectedFrames {
                frames: vec![
                    RawFrame {
                        offset: Duration::ZERO,
                        data: first,
                        masks: Vec::new(),
                        device_width: 1.0,
                        device_height: 1.0,
                    },
                    RawFrame {
                        offset: Duration::from_millis(1),
                        data: second,
                        masks: Vec::new(),
                        device_width: 1.0,
                        device_height: 1.0,
                    },
                ],
                dropped_by_rate: 0,
                dropped_by_limit: 0,
                dropped_by_listener: 0,
                decode_failures: 0,
                ack_failures: 0,
                stream_disconnected: false,
            },
            &[("left".into(), None), ("right".into(), None)],
            Vec::new(),
            &RecordingOptions::default(),
            Duration::from_secs(1),
            1.0,
            false,
            None,
            DocumentEpoch::Known(1),
        )
        .await
        .unwrap();

        for region in &recording.regions {
            let report = region.byte_report().unwrap();
            assert_eq!(report.domain(), BrowserByteDomain::RecordingFrame);
            assert_eq!(report.accounting().retained().get(), expected_region);
        }
        let aggregate = recording.byte_report().unwrap();
        assert_eq!(aggregate.domain(), BrowserByteDomain::RecordingFrame);
        assert_eq!(aggregate.accounting().retained().get(), expected_region * 2);
        assert_eq!(aggregate.extent(), crate::BrowserPayloadExtent::Complete);

        recording.frames_dropped = 1;
        let incomplete = recording.byte_report().unwrap();
        assert!(matches!(
            incomplete.extent(),
            crate::BrowserPayloadExtent::Truncated {
                complete_bytes: MeasuredBrowserBytes::Unavailable { .. },
            }
        ));
        assert!(matches!(
            incomplete.additional_loss(),
            MeasuredBrowserBytes::Unavailable { .. }
        ));
    }

    #[test]
    fn masks_only_the_named_rectangle() {
        let mut img = canvas(100, 100);
        mask_image(&mut img, &[bbox(10, 10, 20, 20)], 1.0, 0);

        assert!(is_black(&img, 10, 10), "top-left corner of the mask");
        assert!(is_black(&img, 29, 29), "bottom-right corner of the mask");
        assert!(!is_black(&img, 9, 10), "one pixel left of the mask");
        assert!(!is_black(&img, 30, 30), "one pixel past the mask");
        assert!(!is_black(&img, 99, 99), "far corner");
    }

    #[test]
    fn pad_grows_the_mask_outward_in_css_pixels() {
        let mut img = canvas(100, 100);
        mask_image(&mut img, &[bbox(10, 10, 20, 20)], 1.0, 2);

        assert!(is_black(&img, 8, 8), "padded out by 2");
        assert!(is_black(&img, 31, 31), "padded out by 2 on the far side");
        assert!(!is_black(&img, 7, 8));
        assert!(!is_black(&img, 32, 32));
    }

    #[test]
    fn scales_css_pixels_into_frame_pixels() {
        // Chrome downscales screencast frames, so a 2x frame means a CSS
        // rectangle covers twice as many pixels.
        let mut img = canvas(200, 200);
        mask_image(&mut img, &[bbox(10, 10, 20, 20)], 2.0, 0);

        assert!(is_black(&img, 20, 20));
        assert!(is_black(&img, 59, 59));
        assert!(!is_black(&img, 19, 20));
        assert!(!is_black(&img, 60, 60));
    }

    #[test]
    fn clamps_a_mask_running_off_the_frame() {
        let mut img = canvas(50, 50);
        mask_image(&mut img, &[bbox(40, 40, 100, 100)], 1.0, 0);

        assert!(
            is_black(&img, 49, 49),
            "clamped to the frame edge, not skipped"
        );
        assert!(!is_black(&img, 39, 39));
    }

    #[test]
    fn a_mask_entirely_outside_the_frame_is_skipped_not_panicked() {
        let mut img = canvas(50, 50);
        mask_image(&mut img, &[bbox(80, 80, 10, 10)], 1.0, 0);
        assert!(!is_black(&img, 49, 49));
    }

    #[test]
    fn pad_at_the_origin_saturates_instead_of_wrapping() {
        let mut img = canvas(50, 50);
        mask_image(&mut img, &[bbox(1, 1, 5, 5)], 1.0, 4);
        assert!(
            is_black(&img, 0, 0),
            "clipped at 0 rather than wrapping to u32::MAX"
        );
        assert!(is_black(&img, 9, 9));
    }

    #[test]
    fn several_masks_all_apply() {
        let mut img = canvas(100, 100);
        mask_image(
            &mut img,
            &[bbox(0, 0, 10, 10), bbox(50, 50, 10, 10)],
            1.0,
            0,
        );
        assert!(is_black(&img, 5, 5));
        assert!(is_black(&img, 55, 55));
        assert!(!is_black(&img, 30, 30));
    }

    #[test]
    fn union_covers_both_positions() {
        // The scroll case: the element was at y=10 last tick and y=40 now, and
        // the frame in between must be covered at both.
        let joined = union(bbox(10, 40, 20, 20), bbox(10, 10, 20, 20));
        assert_eq!(joined, bbox(10, 10, 20, 50));
    }

    #[test]
    fn union_of_disjoint_rectangles_is_the_bounding_box() {
        assert_eq!(
            union(bbox(0, 0, 10, 10), bbox(90, 90, 10, 10)),
            bbox(0, 0, 100, 100)
        );
    }

    #[test]
    fn union_of_large_user_rectangles_does_not_overflow() {
        assert_eq!(
            union(bbox(u32::MAX, 0, u32::MAX, 1), bbox(0, 0, 1, 1)),
            bbox(0, 0, u32::MAX, 1)
        );
    }

    fn entry(bbox: Bbox, tracked: bool) -> MaskEntry {
        MaskEntry {
            label: "m".into(),
            initial: bbox,
            current: bbox,
            previous: bbox,
            tracked,
            unresolved_ticks: 0,
            stale_frames: 0,
            stale: false,
        }
    }

    #[test]
    fn stamping_uses_the_union_of_the_last_two_ticks() {
        let mut state = MaskState::new(vec![entry(bbox(10, 10, 20, 20), true)]);
        state.record_resolved(0, bbox(10, 40, 20, 20));

        assert_eq!(state.stamp(), vec![bbox(10, 10, 20, 50)]);
    }

    #[test]
    fn an_unresolved_tick_keeps_covering_and_is_counted() {
        let mut state = MaskState::new(vec![entry(bbox(10, 10, 20, 20), true)]);
        state.record_unresolved(0);
        let stamped = state.stamp();

        assert_eq!(
            stamped,
            vec![bbox(10, 10, 20, 20)],
            "still covered after the element vanished"
        );
        let report = &state.reports()[0];
        assert_eq!(report.unresolved_ticks, 1);
        assert_eq!(
            report.stale_frames, 1,
            "the frame is flagged, not silently trusted"
        );
    }

    #[test]
    fn recovering_from_a_stale_tick_stops_counting_stale_frames() {
        let mut state = MaskState::new(vec![entry(bbox(10, 10, 20, 20), true)]);
        state.record_unresolved(0);
        state.stamp();
        state.record_resolved(0, bbox(10, 10, 20, 20));
        state.stamp();

        let report = &state.reports()[0];
        assert_eq!(report.unresolved_ticks, 1);
        assert_eq!(report.stale_frames, 1);
    }

    #[test]
    fn the_report_keeps_the_rectangle_as_first_resolved() {
        let mut state = MaskState::new(vec![entry(bbox(1, 2, 3, 4), true)]);
        state.record_resolved(0, bbox(90, 90, 5, 5));

        assert_eq!(state.reports()[0].bbox, bbox(1, 2, 3, 4));
    }

    #[test]
    fn a_fixed_mask_is_reported_as_untracked() {
        let spec = MaskSpec::bbox(bbox(0, 0, 5, 5));
        assert!(!spec.is_tracked());
    }

    #[test]
    fn a_selector_mask_tracks_by_default_and_can_be_pinned() {
        let entry = BrowserTarget {
            kind: BrowserTargetKind::Css,
            value: "#password".into(),
            regex: None,
            name: None,
            nth: None,
            x: None,
            y: None,
        };
        assert!(MaskSpec::selector(entry.clone()).is_tracked());
        assert!(!MaskSpec::selector(entry).with_track(false).is_tracked());
    }

    #[test]
    fn masking_is_a_no_op_when_a_frame_carries_no_rectangles() {
        // Guards the fast path: an unmasked recording must not pay a decode.
        let mut frames = vec![RawFrame {
            offset: Duration::ZERO,
            data: b"not a decodable image".to_vec(),
            masks: Vec::new(),
            device_width: 100.0,
            device_height: 100.0,
        }];
        assert!(mask_raw_frames(&mut frames, 2, FrameFormat::Png, 80).is_ok());
    }

    #[test]
    fn an_undecodable_frame_fails_the_recording_rather_than_passing_through() {
        let mut frames = vec![RawFrame {
            offset: Duration::ZERO,
            data: b"not a decodable image".to_vec(),
            masks: vec![bbox(0, 0, 10, 10)],
            device_width: 100.0,
            device_height: 100.0,
        }];
        let err = mask_raw_frames(&mut frames, 0, FrameFormat::Png, 80).unwrap_err();
        assert!(matches!(err, VoidCrawlError::RecordingError(_)));
        assert_eq!(
            frames[0].data, b"not a decodable image",
            "left untouched, not emitted masked"
        );
    }
}
