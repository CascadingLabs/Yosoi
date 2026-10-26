//! Immutable local-video observations, lazy frame reads, and time-addressed references.
//!
//! FFprobe reads metadata; FFmpeg materializes individual frames with one worker.
//! Timeline navigation never grants browser/device control and does not imply OCR,
//! transcription, audio inspection, or that unsampled frames have been observed.
pub mod archive;
mod process;
mod timeline;
use super::{
    Coverage, PixelRect, SurfaceError,
    model::{
        self, Access, AddressToken, Capability, Descriptor, Observation, ObservationId, SourceId,
        SurfaceId,
    },
};
pub use archive::{FrameArchiveRef, VideoArchiveRef};
use image::{ImageFormat, ImageReader};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::VecDeque,
    env,
    io::{self, Cursor},
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use tempfile::TempDir;
use thiserror::Error;
use tokio::{fs, process::Command, sync::Mutex};

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
}
/// Materialized pixel evidence with metadata suitable for bounded agent replies.
#[derive(Clone, Debug)]
pub struct DecodedFrame {
    /// Source and time/pixel coordinate provenance.
    pub info: FrameInfo,
    /// Actual PNG bytes; these are intentionally not implicitly serialized into replies.
    pub png: Vec<u8>,
}
#[derive(Debug)]
struct Data {
    _snapshot: TempDir,
    path: PathBuf,
    metadata: VideoMetadata,
    policy: VideoPolicy,
    descriptor: Descriptor,
    observation: Observation,
    root: model::Reference,
    cache: Mutex<VecDeque<(u64, DecodedFrame)>>,
    ffmpeg: PathBuf,
}
/// A frozen local source with a lazy timeline and read-only frame capabilities.
#[derive(Clone, Debug)]
pub struct VideoSurface {
    data: Arc<Data>,
}
impl VideoSurface {
    /// Copies and probes one local file under explicit byte, duration and pixel limits.
    /// No full-video frame scan occurs. YOSOI_FFMPEG/YOSOI_FFPROBE select local executables.
    pub async fn open(path: impl AsRef<Path>, policy: VideoPolicy) -> Result<Self, VideoError> {
        policy.validate()?;
        let file = fs::File::open(path.as_ref()).await?;
        if !file.metadata().await?.is_file() {
            return Err(VideoError::Invalid(
                "video source must be a local regular file".into(),
            ));
        }
        let bytes = process::bounded_read(file, policy.max_source_bytes).await?;
        let snapshot = tempfile::tempdir()?;
        let frozen = snapshot.path().join("source.bin");
        fs::write(&frozen, &bytes).await?;
        let ffmpeg =
            env::var_os("YOSOI_FFMPEG").map_or_else(|| PathBuf::from("ffmpeg"), PathBuf::from);
        let ffprobe =
            env::var_os("YOSOI_FFPROBE").map_or_else(|| PathBuf::from("ffprobe"), PathBuf::from);
        let mut version = Command::new(&ffmpeg);
        version.args(["-version"]);
        let output = process::run(version, 64 * 1024, policy.tool_timeout_ms).await?;
        let decoder = String::from_utf8_lossy(&output.stdout)
            .lines()
            .next()
            .unwrap_or_default()
            .chars()
            .take(256)
            .collect::<String>();
        let mut probe = Command::new(ffprobe);
        probe.args(["-v","error","-threads","1","-format_whitelist","mov,matroska,webm,avi,mpegts,ogg","-protocol_whitelist","file,pipe","-show_entries","format=duration,start_time,format_name:stream=index,codec_type,codec_name,width,height,time_base,start_time,duration","-of","json"]).arg(&frozen);
        let output = process::run(probe, 1024 * 1024, policy.tool_timeout_ms).await?;
        let probe: Value = serde_json::from_slice(&output.stdout)
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        let streams = probe
            .get("streams")
            .and_then(Value::as_array)
            .ok_or_else(|| VideoError::Invalid("probe lacks streams".into()))?;
        let stream = streams
            .iter()
            .find(|v| v.get("codec_type").and_then(Value::as_str) == Some("video"))
            .ok_or_else(|| VideoError::Invalid("source has no video stream".into()))?;
        let duration = stream
            .get("duration")
            .and_then(Value::as_str)
            .or_else(|| probe.pointer("/format/duration").and_then(Value::as_str))
            .ok_or_else(|| VideoError::Invalid("source lacks duration".into()))?;
        let duration_us = u64::try_from(seconds_us(duration)?)
            .map_err(|_| VideoError::Invalid("negative duration".into()))?;
        let width = u32::try_from(
            stream
                .get("width")
                .and_then(Value::as_u64)
                .unwrap_or_default(),
        )
        .map_err(|_| VideoError::Invalid("invalid width".into()))?;
        let height = u32::try_from(
            stream
                .get("height")
                .and_then(Value::as_u64)
                .unwrap_or_default(),
        )
        .map_err(|_| VideoError::Invalid("invalid height".into()))?;
        let metadata = VideoMetadata {
            name: path
                .as_ref()
                .file_name()
                .map_or_else(|| "video".into(), |v| v.to_string_lossy().into_owned()),
            source_sha256: format!("{:x}", Sha256::digest(&bytes)),
            source_bytes: bytes.len(),
            container: probe
                .pointer("/format/format_name")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
                .into(),
            codec: stream
                .get("codec_name")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
                .into(),
            width,
            height,
            duration_us,
            duration_estimated: stream.get("duration").and_then(Value::as_str).is_none(),
            stream_start_us: seconds_us(
                stream
                    .get("start_time")
                    .and_then(Value::as_str)
                    .unwrap_or("0"),
            )?,
            time_base: stream
                .get("time_base")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
                .into(),
            audio_streams: streams
                .iter()
                .filter(|s| s.get("codec_type").and_then(Value::as_str) == Some("audio"))
                .count(),
            decoder,
        };
        Self::prepared(snapshot, frozen, metadata, policy, ffmpeg)
    }
    fn prepared(
        snapshot: TempDir,
        path: PathBuf,
        metadata: VideoMetadata,
        policy: VideoPolicy,
        ffmpeg: PathBuf,
    ) -> Result<Self, VideoError> {
        policy.validate()?;
        if !metadata.container.split(',').any(|name| {
            matches!(
                name,
                "mov" | "mp4" | "matroska" | "webm" | "avi" | "mpegts" | "ogg"
            )
        }) {
            return Err(VideoError::Invalid(
                "video snapshot requires a supported self-contained container".into(),
            ));
        }
        if metadata.width == 0
            || metadata.height == 0
            || metadata
                .width
                .checked_mul(metadata.height)
                .is_none_or(|v| v > 16_777_216)
            || metadata.duration_us == 0
            || metadata.duration_us > policy.max_duration_us
            || metadata.source_bytes > policy.max_source_bytes
        {
            return Err(VideoError::Limit(
                "source dimensions, duration or byte size",
            ));
        }
        let source = SourceId::new(format!("video:{}", metadata.source_sha256))?;
        let id = SurfaceId::new(format!("{}:visual", source.as_str()))?;
        let mut digest = Sha256::new();
        digest.update(b"yosoi-video-timeline-v1");
        digest.update(metadata.source_sha256.as_bytes());
        digest
            .update(serde_json::to_vec(&metadata).map_err(|e| VideoError::Invalid(e.to_string()))?);
        digest.update(serde_json::to_vec(&json!({"width":metadata.width,"height":metadata.height,"duration_us":metadata.duration_us,"start_us":metadata.stream_start_us,"decoder":metadata.decoder,"side":policy.frame_max_side,"interval":policy.min_interval_us})).map_err(|e|VideoError::Invalid(e.to_string()))?);
        let observation=Observation{id:ObservationId::new(format!("video-v1:{:x}",digest.finalize()))?,surface:id.clone(),coverage:Coverage{complete:false,reason:Some("visual timeline only; frames materialize on request; audio, OCR and transcription are not observed".into())}};
        let capabilities = ["overview", "inspect", "expand", "frame", "crop"]
            .into_iter()
            .map(|name| Capability {
                id: format!("video.{name}@1"),
                access: Access::Read,
                control_domain: None,
                input_schema: format!("yosoi.video.{name}.v1"),
            })
            .collect();
        let descriptor = Descriptor {
            id,
            source,
            representation: "yosoi.video.timeline.v1".into(),
            controllable: false,
            capabilities,
        };
        let root = model::Reference {
            observation: observation.id.clone(),
            address: AddressToken::new(format!("t:0:{}", metadata.duration_us))?,
        };
        Ok(Self {
            data: Arc::new(Data {
                _snapshot: snapshot,
                path,
                metadata,
                policy,
                descriptor,
                observation,
                root,
                cache: Mutex::new(VecDeque::new()),
                ffmpeg,
            }),
        })
    }
    /// Borrows demuxer metadata and its clock origin; this is not decoded frame evidence.
    pub fn metadata(&self) -> &VideoMetadata {
        &self.data.metadata
    }
    /// Borrows the effective processing limits, without exposing live authority.
    pub fn policy(&self) -> &VideoPolicy {
        &self.data.policy
    }
    /// Issues a request for the first frame at or after a stream-relative position.
    /// A position in the final frame tail may have no later frame; materialization then fails explicitly.
    pub fn at(&self, position_us: u64) -> Result<model::Reference, VideoError> {
        if position_us >= self.data.metadata.duration_us {
            return Err(VideoError::Invalid(
                "frame position is outside the video".into(),
            ));
        }
        Ok(model::Reference {
            observation: self.data.observation.id.clone(),
            address: AddressToken::new(format!("f:{position_us}"))?,
        })
    }
    /// Materializes one frame or previously addressed crop. At most four full frames are cached.
    /// The measured PTS is retained separately from the requested position.
    pub async fn frame(&self, reference: &model::Reference) -> Result<DecodedFrame, VideoError> {
        let address = self.address(reference)?;
        let (position, region) = match address {
            timeline::Address::Frame(position) => (position, None),
            timeline::Address::Region(position, rect) => (position, Some(rect)),
            timeline::Address::Interval(..) => {
                return Err(VideoError::Invalid(
                    "request a frame address before materializing pixels".into(),
                ));
            }
        };
        let mut cache = self.data.cache.lock().await;
        let full = if let Some((_, frame)) = cache.iter().find(|(time, _)| *time == position) {
            frame.clone()
        } else {
            let frame = self.decode(position).await?;
            if cache.len() >= 4 {
                cache.pop_front();
            }
            cache.push_back((position, frame.clone()));
            frame
        };
        drop(cache);
        if let Some(rect) = region {
            self.crop_pixels(full, rect, reference.clone())
        } else {
            Ok(full)
        }
    }
    /// Crops full decoded-frame pixels; nested crop coordinates are rejected as ambiguous.
    pub async fn crop(
        &self,
        reference: &model::Reference,
        rect: PixelRect,
    ) -> Result<DecodedFrame, VideoError> {
        let timeline::Address::Frame(position) = self.address(reference)? else {
            return Err(VideoError::Invalid(
                "crop requires a full-frame reference".into(),
            ));
        };
        let full = self.frame(reference).await?;
        let reference = model::Reference {
            observation: self.data.observation.id.clone(),
            address: AddressToken::new(format!(
                "r:{position}:{}:{}:{}:{}",
                rect.x, rect.y, rect.width, rect.height
            ))?,
        };
        self.crop_pixels(full, rect, reference)
    }
    fn crop_pixels(
        &self,
        full: DecodedFrame,
        rect: PixelRect,
        reference: model::Reference,
    ) -> Result<DecodedFrame, VideoError> {
        if rect.width == 0
            || rect.height == 0
            || rect
                .x
                .checked_add(rect.width)
                .is_none_or(|v| v > full.info.width)
            || rect
                .y
                .checked_add(rect.height)
                .is_none_or(|v| v > full.info.height)
        {
            return Err(VideoError::Invalid(
                "crop is outside decoded-frame pixels".into(),
            ));
        }
        let mut reader = ImageReader::new(Cursor::new(&full.png)).with_guessed_format()?;
        let mut limits = image::Limits::default();
        limits.max_image_width = Some(self.data.policy.frame_max_side);
        limits.max_image_height = Some(self.data.policy.frame_max_side);
        limits.max_alloc = Some(128 * 1024 * 1024);
        reader.limits(limits);
        let pixels = reader
            .decode()
            .map_err(|e| VideoError::Invalid(e.to_string()))?
            .crop_imm(rect.x, rect.y, rect.width, rect.height);
        let mut png = Cursor::new(Vec::new());
        pixels
            .write_to(&mut png, ImageFormat::Png)
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        let png = png.into_inner();
        if png.len() > self.data.policy.max_frame_bytes {
            return Err(VideoError::Limit("crop PNG bytes"));
        }
        let mut info = full.info;
        info.reference = reference;
        info.width = rect.width;
        info.height = rect.height;
        info.region = Some(rect);
        info.png_sha256 = format!("{:x}", Sha256::digest(&png));
        info.png_bytes = png.len();
        Ok(DecodedFrame { info, png })
    }
    async fn decode(&self, position: u64) -> Result<DecodedFrame, VideoError> {
        let mut version = Command::new(&self.data.ffmpeg);
        version.arg("-version");
        let version = process::run(version, 64 * 1024, self.data.policy.tool_timeout_ms).await?;
        let decoder = String::from_utf8_lossy(&version.stdout)
            .lines()
            .next()
            .unwrap_or_default()
            .chars()
            .take(256)
            .collect::<String>();
        if decoder != self.data.metadata.decoder {
            return Err(VideoError::Invalid(
                "decoder identity changed; create a new observation before decoding".into(),
            ));
        }
        let mut command = Command::new(&self.data.ffmpeg);
        let side = self.data.policy.frame_max_side;
        // A single PNG has no output timeline; measure source PTS before encoding.
        // Avoid version-specific fps_mode/vsync options on supported FFmpeg releases.
        command.args(["-hide_banner","-nostdin","-loglevel","info","-threads","1","-filter_threads","1","-format_whitelist","mov,matroska,webm,avi,mpegts,ogg","-protocol_whitelist","file,pipe","-ss"]).arg(format!("{}.{:06}",position/1_000_000,position%1_000_000)).arg("-copyts").arg("-i").arg(&self.data.path).args(["-map","0:v:0","-an","-vf"]).arg(format!("scale=w='min(iw,{side})':h='min(ih,{side})':force_original_aspect_ratio=decrease,showinfo")).args(["-frames:v","1","-c:v","png","-threads:v","1","-f","image2pipe","pipe:1"]);
        let output = process::run(
            command,
            self.data.policy.max_frame_bytes,
            self.data.policy.tool_timeout_ms,
        )
        .await?;
        let pts = String::from_utf8_lossy(&output.stderr)
            .lines()
            .filter(|line| line.contains("showinfo") && line.contains("pts_time:"))
            .flat_map(str::split_whitespace)
            .find_map(|token| token.strip_prefix("pts_time:"))
            .map(seconds_us)
            .transpose()?
            .ok_or(VideoError::NoFrameAtOrAfter {
                requested_us: position,
            })?;
        let (width, height) = ImageReader::new(Cursor::new(&output.stdout))
            .with_guessed_format()?
            .into_dimensions()
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if width == 0 || height == 0 || width > side || height > side {
            return Err(VideoError::Limit("decoded frame dimensions"));
        }
        let relative = pts
            .checked_sub(self.data.metadata.stream_start_us)
            .and_then(|v| u64::try_from(v).ok());
        let reference = self.at(position)?;
        let info = FrameInfo {
            reference,
            requested_us: position,
            source_pts_us: pts,
            position_us: relative,
            canvas_width: width,
            canvas_height: height,
            width,
            height,
            region: None,
            png_sha256: format!("{:x}", Sha256::digest(&output.stdout)),
            png_bytes: output.stdout.len(),
        };
        Ok(DecodedFrame {
            info,
            png: output.stdout,
        })
    }
}
fn seconds_us(value: &str) -> Result<i64, VideoError> {
    let seconds = value
        .parse::<f64>()
        .map_err(|_| VideoError::Invalid("invalid media timestamp".into()))?;
    if !seconds.is_finite() {
        return Err(VideoError::Invalid("nonfinite media timestamp".into()));
    }
    let duration = Duration::try_from_secs_f64(seconds.abs())
        .map_err(|_| VideoError::Invalid("media timestamp out of range".into()))?;
    let microseconds = i64::try_from(duration.as_micros())
        .map_err(|_| VideoError::Invalid("media timestamp out of range".into()))?;
    if seconds < 0.0 {
        microseconds
            .checked_neg()
            .ok_or_else(|| VideoError::Invalid("media timestamp out of range".into()))
    } else {
        Ok(microseconds)
    }
}

mod session;
pub use session::VideoSession;
