//! Frozen typed source ingestion and decoder-profile preparation.
use super::{
    Data, VideoError, VideoMetadata, VideoPolicy, VideoSurface, process, time::seconds_us,
};
use crate::surface::model;
use crate::{
    documents::{FileLimits, FileMetadata, VideoDocument},
    request::CancellationToken,
    surface::{
        Coverage,
        model::{
            Access, AddressToken, Capability, Descriptor, Observation, ObservationId, SourceId,
            SurfaceId,
        },
    },
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::VecDeque;
use std::{
    env,
    path::{Path, PathBuf},
    sync::Arc,
};
use tempfile::TempDir;
use tokio::sync::Mutex;
use tokio::{fs, process::Command};

impl VideoSurface {
    /// Copies and probes one local file under explicit byte, duration and pixel limits.
    /// Signature-recognized sources use the ordinary VideoDocument contract. Ogg and
    /// MPEG-TS sources require FFprobe to confirm a self-contained video stream before
    /// Rust records their decoder-validated container provenance. No full-video frame
    /// scan occurs. YOSOI_FFMPEG/YOSOI_FFPROBE select local executables.
    pub async fn open(path: impl AsRef<Path>, policy: VideoPolicy) -> Result<Self, VideoError> {
        Self::open_cancellable(path, policy, &CancellationToken::new()).await
    }
    /// Prepares a local file with cooperative cancellation and awaited decoder cleanup.
    pub async fn open_cancellable(
        path: impl AsRef<Path>,
        policy: VideoPolicy,
        cancellation: &CancellationToken,
    ) -> Result<Self, VideoError> {
        policy.validate()?;
        if cancellation.is_cancelled() {
            return Err(VideoError::Cancelled);
        }
        let file = fs::File::open(path.as_ref()).await?;
        if !file.metadata().await?.is_file() {
            return Err(VideoError::Invalid(
                "video source must be a local regular file".into(),
            ));
        }
        let bytes = process::bounded_read(file, policy.max_source_bytes).await?;
        let name = path.as_ref().file_name().map_or_else(
            || "video".to_owned(),
            |name| name.to_string_lossy().into_owned(),
        );
        let id = format!("video-source-{:x}", Sha256::digest(&bytes));
        let source_metadata = FileMetadata::new()
            .with_filename(name.clone())
            .map_err(|error| VideoError::Invalid(error.to_string()))?;
        let file_limits = FileLimits {
            max_bytes: u64::try_from(policy.max_source_bytes)
                .map_err(|_| VideoError::Limit("source bytes"))?,
        };
        if infer::get(&bytes).is_some_and(|kind| kind.matcher_type() == infer::MatcherType::Video) {
            let document =
                VideoDocument::from_bytes_with_metadata(id, bytes, source_metadata, file_limits)
                    .map_err(|error| VideoError::Invalid(error.to_string()))?;
            return Self::from_document_cancellable(&document, policy, cancellation).await;
        }
        // Preserve signature-ambiguous Ogg/MPEG-TS sources only after the bounded
        // FFprobe path confirms a self-contained video stream and container.
        Self::prepare_bytes(
            name,
            bytes,
            source_metadata,
            None,
            true,
            policy,
            cancellation,
        )
        .await
    }
    /// Prepares an immutable typed video without reacquiring its original source.
    ///
    /// Signature recognition is separate from demuxer validation. Preparation probes
    /// the retained bytes under this decoder policy and retains the original native
    /// document independently of the resulting observation and decoded frame cache.
    pub async fn from_document(
        document: &VideoDocument,
        policy: VideoPolicy,
    ) -> Result<Self, VideoError> {
        Self::from_document_cancellable(document, policy, &CancellationToken::new()).await
    }
    /// Prepares retained bytes with cancellation that settles owned decoder cleanup.
    pub async fn from_document_cancellable(
        document: &VideoDocument,
        policy: VideoPolicy,
        cancellation: &CancellationToken,
    ) -> Result<Self, VideoError> {
        policy.validate()?;
        if cancellation.is_cancelled() {
            return Err(VideoError::Cancelled);
        }
        if document.bytes().len() > policy.max_source_bytes {
            return Err(VideoError::Limit("source bytes"));
        }
        let name = document
            .metadata()
            .filename()
            .unwrap_or_else(|| document.id().as_str())
            .to_owned();
        Self::prepare_bytes(
            name,
            document.bytes().to_vec(),
            document.metadata().clone(),
            Some(document.clone()),
            false,
            policy,
            cancellation,
        )
        .await
    }
    async fn prepare_bytes(
        name: String,
        bytes: Vec<u8>,
        source_metadata: FileMetadata,
        source_document: Option<VideoDocument>,
        probe_validated_fallback: bool,
        policy: VideoPolicy,
        cancellation: &CancellationToken,
    ) -> Result<Self, VideoError> {
        let snapshot = Arc::new(tempfile::tempdir()?);
        let frozen = snapshot.path().join("source.bin");
        fs::write(&frozen, &bytes).await?;
        let ffmpeg =
            env::var_os("YOSOI_FFMPEG").map_or_else(|| PathBuf::from("ffmpeg"), PathBuf::from);
        let ffprobe =
            env::var_os("YOSOI_FFPROBE").map_or_else(|| PathBuf::from("ffprobe"), PathBuf::from);
        let mut version = Command::new(&ffmpeg);
        version.args(["-version"]);
        let output = process::run(
            version,
            64 * 1024,
            policy.tool_timeout_ms,
            cancellation,
            snapshot.clone(),
        )
        .await?;
        let decoder = String::from_utf8_lossy(&output.stdout)
            .lines()
            .next()
            .unwrap_or_default()
            .chars()
            .take(256)
            .collect::<String>();
        let mut probe = Command::new(ffprobe);
        probe.args(["-v","error","-threads","1","-format_whitelist","mov,matroska,webm,avi,mpegts,ogg","-protocol_whitelist","file,pipe","-show_entries","format=duration,start_time,format_name:stream=index,codec_type,codec_name,width,height,time_base,start_time,duration","-of","json"]).arg(&frozen);
        let output = process::run(
            probe,
            1024 * 1024,
            policy.tool_timeout_ms,
            cancellation,
            snapshot.clone(),
        )
        .await?;
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
            name,
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
        let source_document = match (source_document, probe_validated_fallback) {
            (Some(document), _) => Some(document),
            (None, true) => {
                validate_metadata(&metadata, &policy)?;
                let container =
                    decoder_validated_container(&metadata.container).ok_or_else(|| {
                        VideoError::Invalid(
                        "signature-ambiguous video container is not supported for typed ingestion"
                            .into(),
                    )
                    })?;
                Some(
                    VideoDocument::from_probe_validated_bytes(
                        format!("video-source-{:x}", Sha256::digest(&bytes)),
                        bytes,
                        source_metadata,
                        FileLimits {
                            max_bytes: u64::try_from(policy.max_source_bytes)
                                .map_err(|_| VideoError::Limit("source bytes"))?,
                        },
                        container,
                    )
                    .map_err(|error| VideoError::Invalid(error.to_string()))?,
                )
            }
            (None, false) => None,
        };
        Self::prepared(snapshot, frozen, metadata, policy, ffmpeg, source_document)
    }
    pub(super) fn prepared(
        snapshot: Arc<TempDir>,
        path: PathBuf,
        metadata: VideoMetadata,
        policy: VideoPolicy,
        ffmpeg: PathBuf,
        source_document: Option<VideoDocument>,
    ) -> Result<Self, VideoError> {
        policy.validate()?;
        validate_metadata(&metadata, &policy)?;
        if source_document
            .as_ref()
            .and_then(|document| document.metadata().probe_validated_video_container())
            .is_some_and(|container| {
                !metadata
                    .container
                    .split(',')
                    .map(str::trim)
                    .any(|observed| observed == container)
            })
        {
            return Err(VideoError::Invalid(
                "video probe provenance differs from the retained container".into(),
            ));
        }
        let source = if let Some(document) = source_document.as_ref() {
            let encoded = serde_json::to_vec(&(document.id().as_str(), document.sha256()))
                .map_err(|error| VideoError::Invalid(error.to_string()))?;
            SourceId::new(format!("video-document:v1:{:x}", Sha256::digest(encoded)))?
        } else {
            SourceId::new(format!("video:{}", metadata.source_sha256))?
        };
        let id = SurfaceId::new(format!("{}:visual", source.as_str()))?;
        let mut digest = Sha256::new();
        digest.update(b"yosoi-video-timeline-v1");
        if source_document.is_some() {
            digest.update(source.as_str().as_bytes());
        }
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
                source_document,
                snapshot,
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
}

fn validate_metadata(metadata: &VideoMetadata, policy: &VideoPolicy) -> Result<(), VideoError> {
    if !is_self_contained_video_container(&metadata.container) {
        return Err(VideoError::Invalid(
            "video snapshot requires a supported self-contained container".into(),
        ));
    }
    if metadata.width == 0
        || metadata.height == 0
        || metadata
            .width
            .checked_mul(metadata.height)
            .is_none_or(|value| value > 16_777_216)
        || metadata.duration_us == 0
        || metadata.duration_us > policy.max_duration_us
        || metadata.source_bytes > policy.max_source_bytes
    {
        return Err(VideoError::Limit(
            "source dimensions, duration or byte size",
        ));
    }
    Ok(())
}

fn is_self_contained_video_container(container: &str) -> bool {
    container.split(',').any(|name| {
        matches!(
            name.trim(),
            "mov" | "mp4" | "matroska" | "webm" | "avi" | "mpegts" | "ogg"
        )
    })
}

fn decoder_validated_container(container: &str) -> Option<&'static str> {
    container
        .split(',')
        .map(str::trim)
        .find_map(|name| match name {
            "ogg" => Some("ogg"),
            "mpegts" => Some("mpegts"),
            _ => None,
        })
}
