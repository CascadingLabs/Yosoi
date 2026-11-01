//! Surface values join the existing sealed Archive dispatch.

mod closure;

use super::{Archive, ArchiveError};
use crate::internal::archive::{ArchiveReference, ArchiveValue, sealed};
use crate::{
    documents::{Document, DocumentProfile},
    surface::{Outcome, OutcomeRef},
};
use closure::{hydrate, rehydrate};

const MAX_OUTCOME_BYTES: usize = 256 * 1024 * 1024;

impl sealed::Value for Outcome {}
impl ArchiveValue for Outcome {
    type Reference = OutcomeRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<OutcomeRef, ArchiveError> {
        value
            .validate()
            .map_err(|error| ArchiveError::InvalidSurfaceOutcome(error.to_string()))?;
        let mut retained = value.clone();
        rehydrate(archive, &mut retained).await?;
        let bytes = serde_json::to_vec(&retained)
            .map_err(|error| ArchiveError::InvalidSurfaceOutcome(error.to_string()))?;
        if bytes.len() > MAX_OUTCOME_BYTES {
            return Err(ArchiveError::InvalidSurfaceOutcome(
                "encoded outcome exceeds 256 MiB".into(),
            ));
        }
        let document = Document::json(format!("surface-outcome-{}", value.record.id()), bytes)
            .map_err(ArchiveError::InvalidDocument)?;
        Ok(OutcomeRef {
            document: archive.write_document(&document).await?,
            version: 1,
        })
    }
}

impl sealed::Reference for OutcomeRef {}
impl ArchiveReference for OutcomeRef {
    type Value = Outcome;

    async fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> Result<Outcome, ArchiveError> {
        if reference.version != 1 {
            return Err(ArchiveError::InvalidSurfaceOutcome(
                "unsupported outcome reference version".into(),
            ));
        }
        let document = archive.read_document(&reference.document).await?;
        if document.profile() != DocumentProfile::source_json()
            || document.bytes().len() > MAX_OUTCOME_BYTES
        {
            return Err(ArchiveError::InvalidSurfaceOutcome(
                "invalid outcome document profile or size".into(),
            ));
        }
        let mut value: Outcome = serde_json::from_slice(document.bytes())
            .map_err(|error| ArchiveError::InvalidSurfaceOutcome(error.to_string()))?;
        hydrate(archive, &mut value).await?;
        value
            .validate()
            .map_err(|error| ArchiveError::InvalidSurfaceOutcome(error.to_string()))?;
        Ok(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        archive::FileDocumentArchiveRef,
        automation_record::{OperationReceipt, OperationStatus},
        documents::{FileDocument, VideoDocument},
        surface::{ArchiveLimits, ArchivedSource},
    };
    use serde_json::json;
    use std::error::Error;

    const MP4_SIGNATURE: [u8; 12] = [0, 0, 0, 16, b'f', b't', b'y', b'p', b'm', b'p', b'4', b'2'];

    #[tokio::test]
    async fn portable_outcome_rewrites_registered_typed_video_dependency()
    -> Result<(), Box<dyn Error>> {
        let original_root = tempfile::tempdir()?;
        let portable_root = tempfile::tempdir()?;
        let archive = Archive::open(original_root.path()).await?;
        let video = VideoDocument::from_bytes("typed-video-source", MP4_SIGNATURE.to_vec())?;
        let original_video_ref = archive.write(&video).await?;
        let video_ref = FileDocumentArchiveRef::Video(original_video_ref.clone());
        let profile = Document::json(
            "video-profile",
            serde_json::to_vec(&json!({
                "schema": "yosoi.surface.video-source.v2",
                "metadata": {"source_sha256": video.sha256()},
                "policy": {"frame_max_side": 1920},
                "source": original_video_ref.to_string(),
            }))?,
        )?;
        let original_profile_ref = archive.write_document(&profile).await?;
        let mut video_source = ArchivedSource::new_file_document(
            original_video_ref.to_string(),
            &FileDocument::Video(video.clone()),
            None,
        );
        video_source.file_archive = Some(video_ref);
        let mut profile_source =
            ArchivedSource::new(original_profile_ref.to_string(), &profile, None);
        profile_source.document_archive = Some(original_profile_ref.clone());
        let mut outcome = Outcome::new("portable-video", ArchiveLimits::default())?
            .with_source(video_source)?
            .with_source(profile_source)?;
        outcome.record.push_operation(OperationReceipt {
            browser: None,
            id: "portable-video:0".into(),
            kind: "surface.video.source".into(),
            status: OperationStatus::Observed,
            result: Some(json!({"document":original_profile_ref.to_string()})),
            observation: None,
            error: None,
        })?;

        let outcome_ref = archive.write(&outcome).await?;
        let portable = portable_root.path().join("video.yosoi");
        archive.export_file(&outcome_ref, &portable).await?;
        drop(archive);
        drop(original_root);

        let imported_root = tempfile::tempdir()?;
        let imported_archive = Archive::open(imported_root.path()).await?;
        let imported_ref = imported_archive.import_file(&portable).await?;
        let imported = imported_archive.read(&imported_ref).await?;
        let restored_profile = imported
            .source_document(&original_profile_ref.to_string(), MAX_OUTCOME_BYTES as u64)?;
        let profile_json: serde_json::Value = serde_json::from_slice(restored_profile.bytes())?;
        let remapped_video_ref = profile_json
            .get("source")
            .and_then(serde_json::Value::as_str)
            .ok_or("restored video profile has no source ref")?;
        assert_ne!(remapped_video_ref, original_video_ref.to_string());
        let restored_video = imported
            .source_file_document(&original_video_ref.to_string(), MAX_OUTCOME_BYTES as u64)?;
        assert_eq!(restored_video, FileDocument::Video(video));

        let source_receipt = imported
            .record
            .operations()
            .iter()
            .find(|receipt| receipt.kind == "surface.video.source")
            .ok_or("restored video source receipt is missing")?;
        let restored_profile_ref = imported
            .sources
            .iter()
            .find(|source| source.key == original_profile_ref.to_string())
            .and_then(|source| source.document_archive.as_ref())
            .map(ToString::to_string)
            .ok_or("restored video profile Archive reference is missing")?;
        assert_eq!(
            source_receipt
                .result
                .as_ref()
                .and_then(|result| result.get("document"))
                .and_then(serde_json::Value::as_str),
            Some(restored_profile_ref.as_str())
        );
        Ok(())
    }
}

#[cfg(all(test, feature = "surface-images"))]
mod pixel_tests {
    use super::*;
    use crate::archive::DocumentArchiveRef;
    use crate::{
        automation_record::{OperationReceipt, OperationStatus},
        documents::ImageDocument,
        surface::{ArchiveLimits, ArchivedSource},
    };
    use serde_json::{Value, json};
    use std::error::Error;

    #[tokio::test]
    async fn portable_video_frame_closes_pixel_artifact_and_image_payload_refs()
    -> Result<(), Box<dyn Error>> {
        use crate::surface::{
            PixelArtifact, PixelCoordinateKind, PixelOrientation, pixels::PixelArtifactArchiveRef,
        };
        use std::io::Cursor;

        let pixels = image::RgbaImage::from_pixel(32, 16, image::Rgba([22, 44, 66, 255]));
        let mut encoded = Cursor::new(Vec::new());
        image::DynamicImage::ImageRgba8(pixels).write_to(&mut encoded, image::ImageFormat::Png)?;
        let image = ImageDocument::from_bytes("frame-pixels", encoded.into_inner())?;
        let artifact =
            PixelArtifact::from_image_document(image, 32, 16, PixelOrientation::ExifUnapplied)?;

        let original_root = tempfile::tempdir()?;
        let portable_root = tempfile::tempdir()?;
        let archive = Archive::open(original_root.path()).await?;
        let pixel_reference = artifact.write_to(&archive).await?;
        let frame_document = Document::json(
            "frame-envelope",
            serde_json::to_vec(&json!({
                "schema": "yosoi.surface.video-frame.v2",
                "info": {
                    "requested_us": 350_000,
                    "source_pts_us": 400_000,
                    "canvas_width": 32,
                    "canvas_height": 16,
                },
                "pixels": pixel_reference,
            }))?,
        )?;
        let frame_reference = archive.write_document(&frame_document).await?;
        let mut outcome = Outcome::new("portable-frame", ArchiveLimits::default())?.with_source(
            ArchivedSource::new(frame_reference.to_string(), &frame_document, None),
        )?;
        outcome.record.push_operation(OperationReceipt {
            browser: None,
            id: "portable-frame:0".into(),
            kind: "surface.video.frame".into(),
            status: OperationStatus::Observed,
            result: Some(json!({"document":frame_reference.to_string()})),
            observation: None,
            error: None,
        })?;
        let outcome_reference = archive.write(&outcome).await?;
        let portable = portable_root.path().join("frame.yosoi");
        archive.export_file(&outcome_reference, &portable).await?;
        drop(archive);
        drop(original_root);

        let imported_root = tempfile::tempdir()?;
        let imported_archive = Archive::open(imported_root.path()).await?;
        let imported_reference = imported_archive.import_file(&portable).await?;
        let imported = imported_archive.read(&imported_reference).await?;
        let frame =
            imported.source_document(&frame_reference.to_string(), MAX_OUTCOME_BYTES as u64)?;
        let frame_json: Value = serde_json::from_slice(frame.bytes())?;
        let metadata_reference: DocumentArchiveRef = frame_json
            .pointer("/pixels/document")
            .and_then(Value::as_str)
            .ok_or("frame PixelArtifact reference is missing")?
            .parse()?;
        let restored = imported_archive
            .read(&PixelArtifactArchiveRef {
                document: metadata_reference,
            })
            .await?;
        assert_eq!(restored.info().width, 32);
        assert_eq!(restored.info().height, 16);
        assert_eq!(
            restored.info().source_space.kind,
            PixelCoordinateKind::OriginalRaster
        );
        assert_eq!(restored.info().source, artifact.info().source);
        assert_eq!(restored.bytes(), artifact.bytes());
        Ok(())
    }

    #[tokio::test]
    async fn portable_screenshot_keeps_root_pixel_provenance_and_archive_ref()
    -> Result<(), Box<dyn Error>> {
        use crate::surface::{
            PixelArtifact, PixelCoordinateKind, PixelCoordinateSpace, PixelOrientation,
            PixelSource, pixels::PixelArtifactArchiveRef,
        };
        use std::io::Cursor;

        let pixels = image::RgbaImage::from_pixel(24, 12, image::Rgba([80, 120, 200, 255]));
        let mut encoded = Cursor::new(Vec::new());
        image::DynamicImage::ImageRgba8(pixels).write_to(&mut encoded, image::ImageFormat::Png)?;
        let image = ImageDocument::from_bytes("screenshot-raster", encoded.into_inner())?;
        let artifact = PixelArtifact::from_raster_document(
            image.clone(),
            PixelSource::BrowserScreenshot {
                identity: "browser:test-observation".into(),
            },
            PixelCoordinateSpace {
                kind: PixelCoordinateKind::DecodedCanvas,
                width: 24,
                height: 12,
                orientation: PixelOrientation::NotApplicable,
            },
        )?;

        let original_root = tempfile::tempdir()?;
        let portable_root = tempfile::tempdir()?;
        let archive = Archive::open(original_root.path()).await?;
        let image_reference = archive.write(&image).await?;
        let pixel_reference = artifact.write_to(&archive).await?;
        let metadata = archive.read_document(&pixel_reference.document).await?;
        let mut pixel_source = ArchivedSource::new_pixel_artifact(
            artifact.info().identity.clone(),
            &artifact,
            1,
            None,
        );
        pixel_source.file_archive = Some(crate::archive::FileDocumentArchiveRef::Image(
            image_reference,
        ));
        let mut metadata_source =
            ArchivedSource::new(pixel_reference.document.to_string(), &metadata, None);
        metadata_source.document_archive = Some(pixel_reference.document.clone());
        let mut outcome = Outcome::new("portable-screenshot", ArchiveLimits::default())?
            .with_source(pixel_source)?
            .with_source(metadata_source)?;
        outcome.record.push_operation(OperationReceipt {
            browser: None,
            id: "portable-screenshot:0".into(),
            kind: "surface.command".into(),
            status: OperationStatus::Observed,
            result: Some(json!({
                "command": {"op":"screenshot"},
                "outcome": {"archive_ref":pixel_reference},
            })),
            observation: None,
            error: None,
        })?;

        let outcome_reference = archive.write(&outcome).await?;
        let portable = portable_root.path().join("screenshot.yosoi");
        archive.export_file(&outcome_reference, &portable).await?;
        drop(archive);
        drop(original_root);

        let imported_root = tempfile::tempdir()?;
        let imported_archive = Archive::open(imported_root.path()).await?;
        let imported_reference = imported_archive.import_file(&portable).await?;
        let imported = imported_archive.read(&imported_reference).await?;
        let restored = imported.source_pixel_artifact(&artifact.info().identity, 1024 * 1024)?;
        assert_eq!(restored.info().source, artifact.info().source);
        assert_eq!(
            restored.info().coordinate_space,
            artifact.info().coordinate_space
        );
        assert_eq!(restored.bytes(), artifact.bytes());

        let receipt = imported
            .record
            .operations()
            .iter()
            .find(|receipt| receipt.kind == "surface.command")
            .ok_or("screenshot receipt is missing")?;
        let metadata_reference: DocumentArchiveRef = receipt
            .result
            .as_ref()
            .and_then(|result| result.pointer("/outcome/archive_ref/document"))
            .and_then(Value::as_str)
            .ok_or("screenshot PixelArtifact reference is missing")?
            .parse()?;
        let restored_from_archive = PixelArtifact::read_from(
            &imported_archive,
            &PixelArtifactArchiveRef {
                document: metadata_reference,
            },
        )
        .await?;
        assert_eq!(restored_from_archive, artifact);
        Ok(())
    }
}
