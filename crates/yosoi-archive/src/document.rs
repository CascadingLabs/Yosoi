use serde::{Deserialize, Serialize};
use yosoi_documents::{Document, DocumentId, DocumentProfile};
use yosoi_types::Sha256Digest;

use crate::dispatch::{ArchiveReference, ArchiveValue, sealed};
use crate::wire::{ARCHIVE_FORMAT_VERSION, RecordKind};
use crate::{Archive, ArchiveError, DocumentArchiveRef};

const DOCUMENT_RECORD_VERSION: u32 = 1;

/// Maximum exact Document bytes materialized by one Archive operation.
pub const MAX_ARCHIVED_DOCUMENT_BYTES: u64 = 268_435_456;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct DocumentRecord {
    id: DocumentId,
    profile: DocumentProfile,
    byte_len: u64,
    sha256: Sha256Digest,
}

impl sealed::Value for Document {}

impl ArchiveValue for Document {
    type Reference = DocumentArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        enforce_document_bound(value.byte_len())?;
        let reference = DocumentArchiveRef::new_current();
        let record = DocumentRecord {
            id: value.id().clone(),
            profile: value.profile(),
            byte_len: value.byte_len(),
            sha256: Sha256Digest::digest(value.bytes()),
        };
        archive
            .write_document_payload(reference.key(), value.bytes())
            .await?;
        archive
            .write_record(
                RecordKind::Document,
                DOCUMENT_RECORD_VERSION,
                reference.key(),
                &record,
            )
            .await?;
        Ok(reference)
    }
}

impl sealed::Reference for DocumentArchiveRef {}

impl ArchiveReference for DocumentArchiveRef {
    type Value = Document;

    async fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> Result<Self::Value, ArchiveError> {
        if reference.format_version() != ARCHIVE_FORMAT_VERSION {
            return Err(ArchiveError::UnsupportedFormat {
                found: reference.format_version(),
                supported: ARCHIVE_FORMAT_VERSION,
            });
        }
        let record: DocumentRecord = archive
            .read_record(
                RecordKind::Document,
                DOCUMENT_RECORD_VERSION,
                reference.key(),
            )
            .await?;
        enforce_document_bound(record.byte_len)?;
        let bytes = archive
            .read_document_payload(reference.key(), record.byte_len)
            .await?;
        if Sha256Digest::digest(&bytes) != record.sha256 {
            return Err(ArchiveError::DocumentPayloadDigestMismatch {
                key: reference.logical_key().to_owned(),
            });
        }
        Document::from_profile(record.id, record.profile, bytes)
            .map_err(ArchiveError::InvalidDocument)
    }
}

const fn enforce_document_bound(observed: u64) -> Result<(), ArchiveError> {
    if observed > MAX_ARCHIVED_DOCUMENT_BYTES {
        return Err(ArchiveError::DocumentTooLarge {
            maximum: MAX_ARCHIVED_DOCUMENT_BYTES,
            observed,
        });
    }
    Ok(())
}
