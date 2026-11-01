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
        automation_record::{OperationReceipt, OperationStatus},
        documents::{FileDocument, VideoDocument},
        surface::{ArchiveLimits, ArchivedSource},
    };
    use serde_json::json;
    use std::error::Error;

    const MP4_SIGNATURE: [u8; 12] = [
        0, 0, 0, 16, b'f', b't', b'y', b'p', b'm', b'p', b'4', b'2',
    ];

    #[tokio::test]
    async fn portable_outcome_rewrites_registered_typed_video_dependency() -> Result<(), Box<dyn Error>> {
        let original_root = tempfile::tempdir()?;
        let portable_root = tempfile::tempdir()?;
        let archive = Archive::open(original_root.path()).await?;
        let video = VideoDocument::from_bytes("typed-video-source", MP4_SIGNATURE.to_vec())?;
        let original_video_ref = archive.write(&video).await?;
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
        let mut outcome = Outcome::new("portable-video", ArchiveLimits::default())?
            .with_source(ArchivedSource::new_file_document(
                original_video_ref.to_string(),
                &FileDocument::Video(video.clone()),
                None,
            ))?
            .with_source(ArchivedSource::new(
                original_profile_ref.to_string(),
                &profile,
                None,
            ))?;
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
        let restored_profile = imported.source_document(
            &original_profile_ref.to_string(),
            MAX_OUTCOME_BYTES as u64,
        )?;
        let profile_json: serde_json::Value = serde_json::from_slice(restored_profile.bytes())?;
        let remapped_video_ref = profile_json
            .get("source")
            .and_then(serde_json::Value::as_str)
            .ok_or("restored video profile has no source ref")?;
        assert_ne!(remapped_video_ref, original_video_ref.to_string());
        let restored_video = imported.source_file_document(
            &original_video_ref.to_string(),
            MAX_OUTCOME_BYTES as u64,
        )?;
        assert_eq!(restored_video, FileDocument::Video(video));
        Ok(())
    }
}
