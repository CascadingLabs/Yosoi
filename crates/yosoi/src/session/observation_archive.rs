//! Archive manifests reference native binary media records instead of embedding media in JSON.

use super::{
    capture::ScreenshotCapture,
    evidence::{AutomaticEvidence, SessionEvidence, SessionEvidenceMetadata},
    recording::{RecordingOutcome, RecordingOutcomeMetadata, RecordingSegment},
};
use crate::{
    Archive,
    archive::{ArchiveError, DocumentArchiveRef, ImageDocumentArchiveRef, VideoDocumentArchiveRef},
    documents::{Document, DocumentError, MAX_FILE_BYTES},
};
use crate::{
    automation_record::MAX_AUTOMATION_RECORD_ITEMS, internal::archive::read_document_bounded,
};
use serde::{Deserialize, Serialize, de::DeserializeOwned};

const MAX_ITEMS: usize = MAX_AUTOMATION_RECORD_ITEMS;
const MAX_MANIFEST_BYTES: usize = 8 * 1024 * 1024;

/// Failure to save or restore visual evidence through the existing Archive.
#[derive(Debug, thiserror::Error)]
pub enum EvidenceArchiveError {
    /// Archive I/O, integrity, or reference validation failed.
    #[error(transparent)]
    Archive(#[from] ArchiveError),
    /// The immutable JSON manifest could not be constructed.
    #[error(transparent)]
    Document(#[from] DocumentError),
    /// Manifest encoding or decoding failed.
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    /// Schema, bounds, or the relationship between media and metadata is invalid.
    #[error("invalid visual evidence manifest: {0}")]
    Invalid(&'static str),
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RecordingManifest {
    version: u32,
    metadata: RecordingOutcomeMetadata,
    videos: Vec<VideoDocumentArchiveRef>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ScreenshotManifest {
    version: u32,
    metadata: SessionEvidenceMetadata,
    images: Vec<Option<ImageDocumentArchiveRef>>,
}

fn recording_valid(value: &RecordingOutcomeMetadata) -> Result<(), EvidenceArchiveError> {
    if value.id.is_empty() || value.segments.len() > MAX_ITEMS || value.gaps.len() > MAX_ITEMS {
        return Err(EvidenceArchiveError::Invalid(
            "recording identity or item bound",
        ));
    }
    if value.actions.len() > MAX_ITEMS {
        return Err(EvidenceArchiveError::Invalid("action marker bound"));
    }
    for action in &value.actions {
        if action.operation_id.is_empty()
            || action.operation_id.len() > 128
            || action.kind.is_empty()
            || action.kind.len() > 128
            || action.operation_id.chars().any(char::is_control)
            || action.kind.chars().any(char::is_control)
            || action.tab_id.as_ref().is_some_and(|id| {
                id.is_empty() || id.len() > 1024 || id.chars().any(char::is_control)
            })
        {
            return Err(EvidenceArchiveError::Invalid("action marker identity"));
        }
        if let super::recording::RecordingScope::Tab { tab_id } = &value.source.scope
            && action.tab_id.as_ref() != Some(tab_id)
        {
            return Err(EvidenceArchiveError::Invalid(
                "action marker source mismatch",
            ));
        }
    }
    let mut previous = 0;
    let mut bytes = 0_u64;
    for (index, segment) in value.segments.iter().enumerate() {
        if usize::try_from(segment.sequence).ok() != Some(index)
            || segment.start_offset_ms > segment.end_offset_ms
            || segment.start_offset_ms < previous
            || !segment.media_start_ms.is_finite()
            || !segment.media_end_ms.is_finite()
            || segment.media_start_ms < 0.0
            || segment.media_end_ms < segment.media_start_ms
        {
            return Err(EvidenceArchiveError::Invalid("segment ordering"));
        }
        bytes = bytes
            .checked_add(segment.byte_len)
            .filter(|total| *total <= MAX_FILE_BYTES)
            .ok_or(EvidenceArchiveError::Invalid("recording byte bound"))?;
        previous = segment.end_offset_ms;
    }
    if value
        .gaps
        .iter()
        .any(|gap| gap.start_offset_ms > gap.end_offset_ms)
        || (value.complete
            && (value.segments.is_empty()
                || !value.gaps.is_empty()
                || value.segments.iter().any(|segment| !segment.complete)))
    {
        return Err(EvidenceArchiveError::Invalid("recording coverage"));
    }
    Ok(())
}

async fn write_manifest<T: Serialize + Sync>(
    archive: &Archive,
    kind: &str,
    value: &T,
) -> Result<DocumentArchiveRef, EvidenceArchiveError> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > MAX_MANIFEST_BYTES {
        return Err(EvidenceArchiveError::Invalid("manifest byte bound"));
    }
    Ok(archive
        .write_document(&Document::json(kind, bytes)?)
        .await?)
}

async fn read_manifest<T: DeserializeOwned>(
    archive: &Archive,
    reference: &DocumentArchiveRef,
) -> Result<T, EvidenceArchiveError> {
    let maximum = u64::try_from(MAX_MANIFEST_BYTES)
        .map_err(|_| EvidenceArchiveError::Invalid("manifest byte bound"))?;
    let document = read_document_bounded(archive, reference, maximum).await?;
    Ok(serde_json::from_slice(document.bytes())?)
}

impl RecordingOutcome {
    /// Saves all video segments as raw binary Archive values and a versioned JSON manifest.
    /// The returned reference retains timing, gaps and source facts without live authority.
    pub async fn write_to(
        &self,
        archive: &Archive,
    ) -> Result<DocumentArchiveRef, EvidenceArchiveError> {
        let metadata = self.metadata();
        recording_valid(&metadata)?;
        let mut videos = Vec::with_capacity(self.segments.len());
        for segment in &self.segments {
            if segment.document.byte_len() != segment.metadata.byte_len
                || segment.document.sha256() != segment.metadata.sha256
                || segment.document.id().as_str() != segment.metadata.document_id
            {
                return Err(EvidenceArchiveError::Invalid(
                    "video metadata disagrees with payload",
                ));
            }
            videos.push(archive.write(&segment.document).await?);
        }
        write_manifest(
            archive,
            "session-recording",
            &RecordingManifest {
                version: 1,
                metadata,
                videos,
            },
        )
        .await
    }

    /// Restores video bytes and recording facts without a browser or media decoder.
    /// Unknown schemas, mismatched digests and malformed timeline metadata fail explicitly.
    pub async fn read_from(
        archive: &Archive,
        reference: &DocumentArchiveRef,
    ) -> Result<Self, EvidenceArchiveError> {
        let manifest: RecordingManifest = read_manifest(archive, reference).await?;
        if manifest.version != 1 || manifest.videos.len() != manifest.metadata.segments.len() {
            return Err(EvidenceArchiveError::Invalid(
                "recording schema or segment count",
            ));
        }
        recording_valid(&manifest.metadata)?;
        let mut segments = Vec::with_capacity(manifest.videos.len());
        for (reference, metadata) in manifest.videos.iter().zip(&manifest.metadata.segments) {
            let document = archive.read(reference).await?;
            if document.sha256() != metadata.sha256
                || document.byte_len() != metadata.byte_len
                || document.id().as_str() != metadata.document_id
            {
                return Err(EvidenceArchiveError::Invalid("restored video identity"));
            }
            segments.push(RecordingSegment {
                document,
                metadata: metadata.clone(),
            });
        }
        let value = manifest.metadata;
        Ok(Self {
            id: value.id,
            source: value.source,
            segments,
            gaps: value.gaps,
            actions: value.actions,
            lost_action_events: value.lost_action_events,
            stopped_at_unix_ms: value.stopped_at_unix_ms,
            stop_reason: value.stop_reason,
            complete: value.complete,
        })
    }
}

impl SessionEvidence {
    /// Constructs an immutable evidence snapshot from validated metadata and image values.
    /// This checks entry linkage and aggregate bounds and grants no live browser authority.
    pub fn from_parts(
        metadata: SessionEvidenceMetadata,
        entries: Vec<AutomaticEvidence>,
    ) -> Result<Self, EvidenceArchiveError> {
        Self::from_archived(metadata, entries)
            .map_err(|_| EvidenceArchiveError::Invalid("screenshot evidence parts"))
    }

    /// Saves the screenshot snapshot and receipt links using raw image Archive values.
    /// Recording outputs are saved separately with [`RecordingOutcome::write_to`].
    pub async fn write_to(
        &self,
        archive: &Archive,
    ) -> Result<DocumentArchiveRef, EvidenceArchiveError> {
        Self::from_archived(self.metadata(), self.entries.clone())
            .map_err(|_| EvidenceArchiveError::Invalid("screenshot evidence parts"))?;
        let mut images = Vec::with_capacity(self.entries.len());
        for entry in &self.entries {
            images.push(match &entry.capture {
                Some(capture) => {
                    if capture.document.metadata().capture_id()
                        != Some(capture.metadata.capture_id.as_str())
                        || capture.document.metadata().tab_id()
                            != Some(capture.metadata.tab_id.as_str())
                    {
                        return Err(EvidenceArchiveError::Invalid("screenshot identity"));
                    }
                    Some(archive.write(&capture.document).await?)
                }
                None => None,
            });
        }
        write_manifest(
            archive,
            "session-screenshot-evidence",
            &ScreenshotManifest {
                version: 1,
                metadata: self.metadata(),
                images,
            },
        )
        .await
    }

    /// Restores screenshot evidence and explicit gaps without restoring Session authority.
    /// Aggregate counters include retained recording bytes, whose outputs are archived separately.
    pub async fn read_from(
        archive: &Archive,
        reference: &DocumentArchiveRef,
    ) -> Result<Self, EvidenceArchiveError> {
        let manifest: ScreenshotManifest = read_manifest(archive, reference).await?;
        if manifest.version != 1
            || manifest.images.len() != manifest.metadata.entries.len()
            || manifest.images.len() > MAX_ITEMS
            || manifest.metadata.retained_bytes > manifest.metadata.maximum_bytes
        {
            return Err(EvidenceArchiveError::Invalid("screenshot schema or bounds"));
        }
        let mut entries = Vec::with_capacity(manifest.images.len());
        let mut image_bytes = 0_u64;
        for (reference, entry) in manifest.images.iter().zip(&manifest.metadata.entries) {
            let capture = match (reference, &entry.capture) {
                (Some(reference), Some(metadata)) if entry.gap.is_none() => {
                    let document = archive.read(reference).await?;
                    if document.metadata().capture_id() != Some(metadata.capture_id.as_str())
                        || document.metadata().tab_id() != Some(metadata.tab_id.as_str())
                    {
                        return Err(EvidenceArchiveError::Invalid(
                            "restored screenshot identity",
                        ));
                    }
                    image_bytes = image_bytes
                        .checked_add(document.byte_len())
                        .filter(|bytes| {
                            *bytes <= manifest.metadata.retained_bytes && *bytes <= MAX_FILE_BYTES
                        })
                        .ok_or(EvidenceArchiveError::Invalid("screenshot retention bound"))?;
                    Some(ScreenshotCapture {
                        document,
                        metadata: metadata.clone(),
                    })
                }
                (None, None) if entry.gap.is_some() => None,
                _ => {
                    return Err(EvidenceArchiveError::Invalid(
                        "screenshot payload/gap disagreement",
                    ));
                }
            };
            entries.push(AutomaticEvidence {
                operation_id: entry.operation_id.clone(),
                phase: entry.phase,
                capture,
                gap: entry.gap,
            });
        }
        Self::from_archived(manifest.metadata, entries)
            .map_err(|_| EvidenceArchiveError::Invalid("restored screenshot evidence"))
    }
}

#[cfg(all(test, unix))]
mod tests {
    use std::{error::Error, path::PathBuf};

    use super::*;
    use crate::{
        documents::VideoDocument,
        session::recording::{
            RecordingScope, RecordingSegmentMetadata, RecordingSource, RecordingSourceKind,
            RecordingStopReason,
        },
    };
    use tokio::fs;

    fn recording() -> Result<RecordingOutcome, Box<dyn Error>> {
        // Opaque container signature tests Archive identity, not media decodability.
        let document = VideoDocument::from_bytes(
            "segment-0",
            vec![0, 0, 0, 16, b'f', b't', b'y', b'p', b'm', b'p', b'4', b'2'],
        )?;
        let metadata = RecordingSegmentMetadata {
            document_id: document.id().as_str().to_owned(),
            sha256: document.sha256().into(),
            byte_len: document.byte_len(),
            sequence: 0,
            start_offset_ms: 0,
            end_offset_ms: 100,
            media_start_ms: 0.0,
            media_end_ms: 100.0,
            mime_type: "video/mp4".into(),
            complete: true,
        };
        Ok(RecordingOutcome {
            id: "recording-0".into(),
            source: RecordingSource {
                id: "source-0".into(),
                scope: RecordingScope::Tab {
                    tab_id: "tab-0".into(),
                },
                kind: RecordingSourceKind::TabMediaStream,
                started_at_unix_ms: Some(1000),
            },
            segments: vec![RecordingSegment { document, metadata }],
            gaps: vec![],
            actions: Vec::new(),
            lost_action_events: 0,
            stopped_at_unix_ms: Some(1100),
            stop_reason: RecordingStopReason::Requested,
            complete: true,
        })
    }

    fn document_record_path(archive: &Archive, reference: &DocumentArchiveRef) -> PathBuf {
        let key = reference.logical_key();
        let shard: String = key.chars().take(2).collect();
        archive
            .format_root()
            .join("records/document")
            .join(shard)
            .join(format!("{key}.json"))
    }

    fn document_payload_path(archive: &Archive, reference: &DocumentArchiveRef) -> PathBuf {
        let key = reference.logical_key();
        let shard: String = key.chars().take(2).collect();
        archive
            .format_root()
            .join("documents")
            .join(shard)
            .join(key)
            .join("payload.bin")
    }

    async fn reject_oversize_manifest_before_payload_read(
        archive: &Archive,
        remove_payload: bool,
    ) -> Result<(), Box<dyn Error>> {
        let reference =
            write_manifest(archive, "oversize-test", &serde_json::json!({"ok": true})).await?;
        let record_path = document_record_path(archive, &reference);
        let mut envelope: serde_json::Value =
            serde_json::from_slice(&fs::read(&record_path).await?)?;
        let record = envelope
            .get_mut("value")
            .and_then(serde_json::Value::as_object_mut)
            .ok_or("document record envelope value is missing")?;
        let observed = u64::try_from(MAX_MANIFEST_BYTES)?
            .checked_add(1)
            .ok_or("oversize manifest test length overflow")?;
        record.insert("byte_len".to_owned(), serde_json::Value::from(observed));
        fs::write(&record_path, serde_json::to_vec(&envelope)?).await?;

        let payload_path = document_payload_path(archive, &reference);
        if remove_payload {
            fs::remove_file(payload_path).await?;
        } else {
            fs::write(payload_path, b"short").await?;
        }

        let result: Result<serde_json::Value, EvidenceArchiveError> =
            read_manifest(archive, &reference).await;
        assert!(matches!(
            result,
            Err(EvidenceArchiveError::Archive(ArchiveError::DocumentTooLarge {
                maximum,
                observed: actual,
            })) if maximum == u64::try_from(MAX_MANIFEST_BYTES)? && actual == observed
        ));
        Ok(())
    }

    #[tokio::test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions report manifest-bound failures; Result propagates fallible archive setup"
    )]
    async fn manifest_reader_bounds_record_before_missing_or_short_payload()
    -> Result<(), Box<dyn Error>> {
        let directory = tempfile::tempdir()?;
        let archive = Archive::open(directory.path()).await?;
        let reference =
            write_manifest(&archive, "small-test", &serde_json::json!({"version": 1})).await?;
        let restored: serde_json::Value = read_manifest(&archive, &reference).await?;
        assert_eq!(restored, serde_json::json!({"version": 1}));

        reject_oversize_manifest_before_payload_read(&archive, true).await?;
        reject_oversize_manifest_before_payload_read(&archive, false).await?;
        Ok(())
    }

    #[tokio::test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions report recording-archive regressions; Result propagates fallible setup"
    )]
    async fn recording_archive_preserves_media_and_rejects_manifest_tampering()
    -> Result<(), Box<dyn Error>> {
        let directory = tempfile::tempdir()?;
        let archive = Archive::open(directory.path()).await?;
        let original = recording()?;
        let reference = original.write_to(&archive).await?;
        let restored = RecordingOutcome::read_from(&archive, &reference).await?;
        assert_eq!(restored.metadata(), original.metadata());
        assert_eq!(
            restored
                .segments
                .first()
                .map(|segment| segment.document.bytes()),
            original
                .segments
                .first()
                .map(|segment| segment.document.bytes())
        );
        let mut manifest: RecordingManifest = read_manifest(&archive, &reference).await?;
        if let Some(segment) = manifest.metadata.segments.first_mut() {
            segment.sha256 = "0".repeat(64);
        }
        let altered = write_manifest(&archive, "altered-recording", &manifest).await?;
        assert!(matches!(
            RecordingOutcome::read_from(&archive, &altered).await,
            Err(EvidenceArchiveError::Invalid("restored video identity"))
        ));
        manifest.version = 99;
        let future = write_manifest(&archive, "future-recording", &manifest).await?;
        assert!(
            RecordingOutcome::read_from(&archive, &future)
                .await
                .is_err()
        );
        Ok(())
    }

    #[tokio::test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions report recording-archive validation regressions; Result propagates fallible setup"
    )]
    async fn recording_archive_rejects_false_coverage_and_payload_metadata()
    -> Result<(), Box<dyn Error>> {
        let directory = tempfile::tempdir()?;
        let archive = Archive::open(directory.path()).await?;
        let mut original = recording()?;
        if let Some(segment) = original.segments.first_mut() {
            segment.metadata.byte_len = 1;
        }
        assert!(matches!(
            original.write_to(&archive).await,
            Err(EvidenceArchiveError::Invalid(
                "video metadata disagrees with payload"
            ))
        ));
        let mut original = recording()?;
        original.gaps.push(super::super::recording::RecordingGap {
            start_offset_ms: 20,
            end_offset_ms: 40,
            reason: super::super::recording::RecordingGapReason::Navigation,
        });
        assert!(matches!(
            original.write_to(&archive).await,
            Err(EvidenceArchiveError::Invalid("recording coverage"))
        ));
        Ok(())
    }
}
