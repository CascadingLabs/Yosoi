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
