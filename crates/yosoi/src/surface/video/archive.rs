//! Frozen video sources, verified PNG evidence and decoder-free archive replay.
use super::{DecodedFrame, FrameInfo, VideoError, VideoMetadata, VideoPolicy, VideoSurface};
use crate::{
    Archive,
    archive::{DocumentArchiveRef, VideoDocumentArchiveRef},
    documents::{Document, DocumentProfile},
    surface::{
        model::{ObservationId, SurfaceRead},
        pixels::{PixelArtifact, PixelArtifactArchiveRef},
    },
};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{env, path::PathBuf, sync::Arc};
use tokio::fs;

/// Archive metadata selecting typed source bytes and a frozen interpretation profile.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VideoArchiveRef {
    /// Metadata record selecting the native payload, or a legacy complete source envelope.
    pub document: DocumentArchiveRef,
    /// Interpretation identity required when reconstructing this timeline.
    pub observation: ObservationId,
}
/// Archive metadata selecting checked pixel evidence or a legacy PNG envelope.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FrameArchiveRef {
    /// Metadata record selecting raw typed PNG pixels and their measured provenance.
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
struct TypedSourceEnvelope {
    schema: String,
    metadata: VideoMetadata,
    policy: VideoPolicy,
    source: VideoDocumentArchiveRef,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FrameEnvelope {
    schema: String,
    info: FrameInfo,
    png_base64: String,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct TypedFrameEnvelope {
    schema: String,
    info: FrameInfo,
    pixels: PixelArtifactArchiveRef,
}
impl VideoSurface {
    /// Saves typed source bytes through native Archive storage and a small interpretation record.
    /// Historical sources keep their versioned envelope compatibility path.
    pub async fn write_to(&self, archive: &Archive) -> Result<VideoArchiveRef, VideoError> {
        if let Some(source) = self.source_document() {
            let source = archive
                .write(source)
                .await
                .map_err(|error| VideoError::Invalid(error.to_string()))?;
            let envelope = TypedSourceEnvelope {
                schema: "yosoi.surface.video-source.v2".into(),
                metadata: self.data.metadata.clone(),
                policy: self.data.policy.clone(),
                source,
            };
            let document = Document::json(
                format!("video-profile-{}", self.data.metadata.source_sha256),
                serde_json::to_vec(&envelope)
                    .map_err(|error| VideoError::Invalid(error.to_string()))?,
            )
            .map_err(|error| VideoError::Invalid(error.to_string()))?;
            return Ok(VideoArchiveRef {
                document: archive
                    .write_document(&document)
                    .await
                    .map_err(|error| VideoError::Invalid(error.to_string()))?,
                observation: self.observation().id.clone(),
            });
        }
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
    /// Typed and legacy metadata records must declare the source JSON Document profile.
    pub async fn read_from(
        archive: &Archive,
        reference: &VideoArchiveRef,
    ) -> Result<Self, VideoError> {
        let document = archive
            .read_document(&reference.document)
            .await
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if document.profile() != DocumentProfile::source_json() {
            return Err(VideoError::Invalid(
                "video source envelope requires the source JSON profile".into(),
            ));
        }
        if document.bytes().len() > 180 * 1024 * 1024 {
            return Err(VideoError::Limit("archived video envelope"));
        }
        if let Ok(envelope) = serde_json::from_slice::<TypedSourceEnvelope>(document.bytes()) {
            if envelope.schema != "yosoi.surface.video-source.v2" {
                return Err(VideoError::Invalid(
                    "unsupported typed source schema".into(),
                ));
            }
            envelope.policy.validate()?;
            let source = archive
                .read(&envelope.source)
                .await
                .map_err(|error| VideoError::Invalid(error.to_string()))?;
            if source.bytes().len() != envelope.metadata.source_bytes
                || source.sha256() != envelope.metadata.source_sha256
                || source.bytes().len() > envelope.policy.max_source_bytes
            {
                return Err(VideoError::Invalid(
                    "typed source identity or limit mismatch".into(),
                ));
            }
            let snapshot = Arc::new(tempfile::tempdir()?);
            let path = snapshot.path().join("source.bin");
            fs::write(&path, source.bytes()).await?;
            let ffmpeg =
                env::var_os("YOSOI_FFMPEG").map_or_else(|| PathBuf::from("ffmpeg"), PathBuf::from);
            let surface = Self::prepared(
                snapshot,
                path,
                envelope.metadata,
                envelope.policy,
                ffmpeg,
                Some(source),
            )?;
            if surface.observation().id != reference.observation {
                return Err(VideoError::Invalid(
                    "restored typed video interpretation identity mismatch".into(),
                ));
            }
            return Ok(surface);
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
        let snapshot = Arc::new(tempfile::tempdir()?);
        let path = snapshot.path().join("source.bin");
        fs::write(&path, bytes).await?;
        let ffmpeg =
            env::var_os("YOSOI_FFMPEG").map_or_else(|| PathBuf::from("ffmpeg"), PathBuf::from);
        let surface = Self::prepared(
            snapshot,
            path,
            envelope.metadata,
            envelope.policy,
            ffmpeg,
            None,
        )?;
        if surface.observation().id != reference.observation {
            return Err(VideoError::Invalid(
                "restored video interpretation identity mismatch".into(),
            ));
        }
        Ok(surface)
    }
}
impl DecodedFrame {
    /// Archives measured frame metadata and raw typed pixel evidence through normal Archive.
    /// Historical untyped frames preserve the legacy envelope compatibility path.
    pub async fn write_to(&self, archive: &Archive) -> Result<FrameArchiveRef, VideoError> {
        validate_pixels(self)?;
        if let Some(pixels) = self.pixel_artifact()? {
            let pixels = pixels
                .write_to(archive)
                .await
                .map_err(|error| VideoError::Invalid(error.to_string()))?;
            let envelope = TypedFrameEnvelope {
                schema: "yosoi.surface.video-frame.v2".into(),
                info: self.info.clone(),
                pixels,
            };
            let document = Document::json(
                format!("video-frame-profile-{}", self.info.png_sha256),
                serde_json::to_vec(&envelope)
                    .map_err(|error| VideoError::Invalid(error.to_string()))?,
            )
            .map_err(|error| VideoError::Invalid(error.to_string()))?;
            return Ok(FrameArchiveRef {
                document: archive
                    .write_document(&document)
                    .await
                    .map_err(|error| VideoError::Invalid(error.to_string()))?,
            });
        }
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
    /// Typed and legacy metadata records must declare the source JSON Document profile.
    pub async fn read_from(
        archive: &Archive,
        reference: &FrameArchiveRef,
    ) -> Result<Self, VideoError> {
        let document = archive
            .read_document(&reference.document)
            .await
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if document.profile() != DocumentProfile::source_json() {
            return Err(VideoError::Invalid(
                "video frame envelope requires the source JSON profile".into(),
            ));
        }
        if document.bytes().len() > 48 * 1024 * 1024 {
            return Err(VideoError::Limit("archived frame envelope"));
        }
        if let Ok(envelope) = serde_json::from_slice::<TypedFrameEnvelope>(document.bytes()) {
            if envelope.schema != "yosoi.surface.video-frame.v2" {
                return Err(VideoError::Invalid("unsupported typed frame schema".into()));
            }
            let pixels = PixelArtifact::read_from(archive, &envelope.pixels)
                .await
                .map_err(|error| VideoError::Invalid(error.to_string()))?;
            if envelope.info.pixel_artifact.as_ref() != Some(pixels.info()) {
                return Err(VideoError::Invalid(
                    "frame and retained pixel provenance differ".into(),
                ));
            }
            let frame = Self {
                info: envelope.info,
                png: pixels.bytes().to_vec(),
                pixels: Some(pixels),
            };
            validate_pixels(&frame)?;
            frame
                .pixel_artifact()?
                .ok_or_else(|| VideoError::Invalid("typed frame lacks pixels".into()))?;
            return Ok(frame);
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
        let frame = Self {
            info: envelope.info,
            png,
            pixels: None,
        };
        validate_pixels(&frame)?;
        Ok(frame)
    }
}

mod recording;
mod validate;
pub(in crate::surface) use recording::replay_loaded;
use validate::validate_pixels;
