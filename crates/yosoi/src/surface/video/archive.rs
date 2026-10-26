//! Frozen sources, verified pixels and offline video reconstruction.
use super::{DecodedFrame, FrameInfo, VideoError, VideoMetadata, VideoPolicy, VideoSurface};
use crate::{
    Archive,
    archive::DocumentArchiveRef,
    documents::Document,
    surface::model::{ObservationId, SurfaceRead},
};
use base64::{Engine, engine::general_purpose::STANDARD};
use image::ImageReader;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{env, io::Cursor, path::PathBuf};
use tokio::fs;

/// Normal Archive document reference retaining the complete video snapshot and its profile.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VideoArchiveRef {
    /// Existing immutable Archive Document reference, not a custom storage backend.
    pub document: DocumentArchiveRef,
    /// Interpretation identity required when reconstructing this timeline.
    pub observation: ObservationId,
}
/// Normal Archive document reference retaining actual decoded PNG evidence.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FrameArchiveRef {
    /// Existing immutable Archive Document reference containing PNG bytes and metadata.
    pub document: DocumentArchiveRef,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceEnvelope {
    schema: String,
    metadata: VideoMetadata,
    policy: VideoPolicy,
    content_base64: String,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FrameEnvelope {
    schema: String,
    info: FrameInfo,
    png_base64: String,
}
impl VideoSurface {
    /// Saves a complete bounded source using an existing JSON Document in the normal Archive.
    /// Binary bytes are explicitly base64 encoded; no archive format or record schema is changed.
    pub async fn write_to(&self, archive: &Archive) -> Result<VideoArchiveRef, VideoError> {
        let bytes = fs::read(&self.data.path).await?;
        let envelope = SourceEnvelope {
            schema: "yosoi.surface.video-source.v1".into(),
            metadata: self.data.metadata.clone(),
            policy: self.data.policy.clone(),
            content_base64: STANDARD.encode(bytes),
        };
        let document = Document::json(
            format!("video-source-{}", self.data.metadata.source_sha256),
            serde_json::to_vec(&envelope).map_err(|e| VideoError::Invalid(e.to_string()))?,
        )
        .map_err(|e| VideoError::Invalid(e.to_string()))?;
        let reference = archive
            .write_document(&document)
            .await
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        Ok(VideoArchiveRef {
            document: reference,
            observation: self.observation().id.clone(),
        })
    }
    /// Restores a timeline without the original file, FFprobe, a browser or network access.
    /// Frame decoding is a separate capability and still requires a compatible FFmpeg.
    pub async fn read_from(
        archive: &Archive,
        reference: &VideoArchiveRef,
    ) -> Result<Self, VideoError> {
        let document = archive
            .read_document(&reference.document)
            .await
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if document.bytes().len() > 180 * 1024 * 1024 {
            return Err(VideoError::Limit("archived video envelope"));
        }
        let envelope: SourceEnvelope = serde_json::from_slice(document.bytes())
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if envelope.schema != "yosoi.surface.video-source.v1" {
            return Err(VideoError::Invalid(
                "unsupported video source schema".into(),
            ));
        }
        envelope.policy.validate()?;
        let maximum = envelope
            .policy
            .max_source_bytes
            .checked_add(2)
            .and_then(|v| v.checked_div(3))
            .and_then(|v| v.checked_mul(4))
            .ok_or(VideoError::Limit("source envelope arithmetic"))?;
        if envelope.content_base64.len() > maximum {
            return Err(VideoError::Limit("archived source bytes"));
        }
        let bytes = STANDARD
            .decode(&envelope.content_base64)
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if bytes.len() != envelope.metadata.source_bytes
            || format!("{:x}", Sha256::digest(&bytes)) != envelope.metadata.source_sha256
        {
            return Err(VideoError::Invalid(
                "archived source identity mismatch".into(),
            ));
        }
        let snapshot = tempfile::tempdir()?;
        let path = snapshot.path().join("source.bin");
        fs::write(&path, bytes).await?;
        let ffmpeg =
            env::var_os("YOSOI_FFMPEG").map_or_else(|| PathBuf::from("ffmpeg"), PathBuf::from);
        let surface = Self::prepared(snapshot, path, envelope.metadata, envelope.policy, ffmpeg)?;
        if surface.observation().id != reference.observation {
            return Err(VideoError::Invalid(
                "restored video interpretation identity mismatch".into(),
            ));
        }
        Ok(surface)
    }
}
impl DecodedFrame {
    /// Archives actual PNG pixels and their measured timestamp through a normal JSON Document.
    pub async fn write_to(&self, archive: &Archive) -> Result<FrameArchiveRef, VideoError> {
        validate_pixels(self)?;
        let envelope = FrameEnvelope {
            schema: "yosoi.surface.video-frame.v1".into(),
            info: self.info.clone(),
            png_base64: STANDARD.encode(&self.png),
        };
        let document = Document::json(
            format!("video-frame-{}", self.info.png_sha256),
            serde_json::to_vec(&envelope).map_err(|e| VideoError::Invalid(e.to_string()))?,
        )
        .map_err(|e| VideoError::Invalid(e.to_string()))?;
        Ok(FrameArchiveRef {
            document: archive
                .write_document(&document)
                .await
                .map_err(|e| VideoError::Invalid(e.to_string()))?,
        })
    }
    /// Restores and verifies observed pixels without a video decoder or original source file.
    pub async fn read_from(
        archive: &Archive,
        reference: &FrameArchiveRef,
    ) -> Result<Self, VideoError> {
        let document = archive
            .read_document(&reference.document)
            .await
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if document.bytes().len() > 48 * 1024 * 1024 {
            return Err(VideoError::Limit("archived frame envelope"));
        }
        let envelope: FrameEnvelope = serde_json::from_slice(document.bytes())
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if envelope.schema != "yosoi.surface.video-frame.v1"
            || envelope.info.png_bytes > 32 * 1024 * 1024
        {
            return Err(VideoError::Invalid("unsupported archived frame".into()));
        }
        let maximum = envelope
            .info
            .png_bytes
            .checked_add(2)
            .and_then(|v| v.checked_div(3))
            .and_then(|v| v.checked_mul(4))
            .ok_or(VideoError::Limit("frame envelope arithmetic"))?;
        if envelope.png_base64.len() > maximum {
            return Err(VideoError::Limit("archived frame bytes"));
        }
        let png = STANDARD
            .decode(envelope.png_base64)
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if png.len() != envelope.info.png_bytes
            || format!("{:x}", Sha256::digest(&png)) != envelope.info.png_sha256
        {
            return Err(VideoError::Invalid(
                "archived pixel identity mismatch".into(),
            ));
        }
        let (width, height) = ImageReader::new(Cursor::new(&png))
            .with_guessed_format()?
            .into_dimensions()
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if width != envelope.info.width || height != envelope.info.height {
            return Err(VideoError::Invalid(
                "archived frame dimensions mismatch".into(),
            ));
        }
        let frame = Self {
            info: envelope.info,
            png,
        };
        validate_pixels(&frame)?;
        Ok(frame)
    }
}

fn validate_pixels(frame: &DecodedFrame) -> Result<(), VideoError> {
    let info = &frame.info;
    if info.width == 0
        || info.height == 0
        || info.canvas_width == 0
        || info.canvas_height == 0
        || info.width > 4096
        || info.height > 4096
        || info.canvas_width > 4096
        || info.canvas_height > 4096
        || frame.png.len() > 32 * 1024 * 1024
        || frame.png.len() != info.png_bytes
        || format!("{:x}", Sha256::digest(&frame.png)) != info.png_sha256
    {
        return Err(VideoError::Invalid(
            "invalid frame pixel metadata or digest".into(),
        ));
    }
    if let Some(rect) = info.region {
        if rect.width != info.width
            || rect.height != info.height
            || rect
                .x
                .checked_add(rect.width)
                .is_none_or(|right| right > info.canvas_width)
            || rect
                .y
                .checked_add(rect.height)
                .is_none_or(|bottom| bottom > info.canvas_height)
        {
            return Err(VideoError::Invalid(
                "crop metadata is outside its decoded canvas".into(),
            ));
        }
    } else if info.width != info.canvas_width || info.height != info.canvas_height {
        return Err(VideoError::Invalid(
            "full frame dimensions differ from canvas".into(),
        ));
    }
    let dimensions = ImageReader::new(Cursor::new(&frame.png))
        .with_guessed_format()?
        .into_dimensions()
        .map_err(|error| VideoError::Invalid(error.to_string()))?;
    if dimensions != (info.width, info.height) {
        return Err(VideoError::Invalid(
            "frame pixel dimensions differ from metadata".into(),
        ));
    }
    Ok(())
}

#[cfg(feature = "surface-connections")]
mod replay {
    use super::{
        Archive, DecodedFrame, FrameArchiveRef, SurfaceRead, VideoArchiveRef, VideoSurface,
    };
    use crate::automation_record::AutomationRecord;
    use crate::surface::{
        Budget,
        connection::Result,
        model::{ReadOperation, ReadRequest},
    };
    use serde_json::{Value, json};
    use std::{fs, io, path::Path};
    pub(in crate::surface) async fn replay_loaded(
        archive: &Archive,
        record: &AutomationRecord,
        repeat: usize,
        query: Option<&str>,
        output: Option<&Path>,
    ) -> Result<Value> {
        if query.is_some() {
            return Err(io::Error::other(
                "video does not advertise text search; use saved frame evidence",
            )
            .into());
        }
        let source = record
            .operations()
            .iter()
            .find(|op| op.kind == "surface.video.source")
            .and_then(|op| op.result.as_ref())
            .ok_or_else(|| io::Error::other("archived video source reference absent"))?;
        let reference: VideoArchiveRef = serde_json::from_value(source.clone())?;
        let frames = record
            .operations()
            .iter()
            .filter(|op| op.kind == "surface.video.frame")
            .map(|op| {
                serde_json::from_value::<FrameArchiveRef>(
                    op.result
                        .clone()
                        .ok_or_else(|| io::Error::other("frame reference absent"))?,
                )
                .map_err(Into::into)
            })
            .collect::<Result<Vec<_>>>()?;
        if let Some(directory) = output {
            fs::create_dir_all(directory)?;
        }
        let mut summaries = Vec::new();
        let mut observation = None;
        for iteration in 0..repeat {
            let video = VideoSurface::read_from(archive, &reference).await?;
            video.read(&ReadRequest {
                operation: ReadOperation::Overview,
                budget: Budget::default(),
                continuation: None,
            })?;
            for (index, reference) in frames.iter().enumerate() {
                let frame = DecodedFrame::read_from(archive, reference).await?;
                if frame.info.reference.observation != video.observation().id {
                    return Err(io::Error::other(
                        "frame belongs to a different archived video observation",
                    )
                    .into());
                }
                if iteration == 0 {
                    let path = output.map(|directory| {
                        directory.join(format!("frame-{}.png", frame.info.png_sha256))
                    });
                    if let Some(path) = &path {
                        fs::write(path, &frame.png)?;
                    }
                    if index < 8 {
                        summaries.push(json!({"frame":frame.info,"path":path}));
                    }
                }
            }
            observation = Some(video.observation().clone());
        }
        Ok(
            json!({"mode":"offline","representation":"yosoi.video.timeline.v1","controllable":false,"browser_started":false,"decoder_started":false,"record":record.id(),"iterations":repeat,"observation":observation,"frames_verified":frames.len(),"frames":summaries,"frames_omitted":frames.len().saturating_sub(8)}),
        )
    }
}
#[cfg(feature = "surface-connections")]
pub(in crate::surface) use replay::replay_loaded;

#[cfg(feature = "surface-connections")]
mod collection {
    use crate::{
        Archive,
        automation_record::{AutomationRecord, OperationStatus},
        surface::{archive::Recording, connection::Result},
    };
    use serde_json::{Value, json};
    use std::path::Path;
    use uuid::Uuid;
    impl Recording {
        pub async fn open_video(root: &Path, output: &Path, descriptor: Value) -> Result<Self> {
            let archive = Archive::open(root).await?;
            let mut recording = Self {
                archive,
                record: AutomationRecord::new(
                    format!("surface-{}", Uuid::new_v4()),
                    Vec::new(),
                    Vec::new(),
                )?,
                output: output.to_owned(),
                handle: None,
                sequence: 0,
            };
            recording.push("surface.video.run",OperationStatus::Observed,json!({"schema":"yosoi.surface.video-run.v1","descriptor":descriptor,"recording_policy":{"mode":"archive","source_and_pixels":true}}),None,None)?;
            Ok(recording)
        }
        pub const fn archive(&self) -> &Archive {
            &self.archive
        }
        pub async fn evidence(&mut self, kind: &str, value: Value) -> Result<()> {
            self.push(kind, OperationStatus::Observed, value, None, None)?;
            self.checkpoint().await?;
            Ok(())
        }
        pub async fn close_video(&mut self) -> Result<()> {
            self.push(
                "surface.closed",
                OperationStatus::Observed,
                json!({"resources_released":true,"browser_started":false}),
                None,
                None,
            )?;
            self.checkpoint().await?;
            Ok(())
        }
    }
}
