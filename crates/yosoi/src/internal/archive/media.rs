use std::sync::Arc;

use serde::{Deserialize, Serialize};

use crate::internal::{
    archive::{
        Archive, ArchiveError, AudioDocumentArchiveRef, BinaryDocumentArchiveRef,
        FileDocumentArchiveRef, ImageDocumentArchiveRef, VideoDocumentArchiveRef,
        dispatch::{ArchiveReference, ArchiveValue, sealed},
        refs::RecordKey,
        wire::{ARCHIVE_FORMAT_VERSION, RecordKind},
    },
    documents::DocumentId,
    media_documents::{
        AudioDocument, BinaryDocument, FileDocument, FileDocumentError, FileMetadata,
        ImageDocument, MAX_FILE_BYTES, VideoDocument, from_archived_audio, from_archived_binary,
        from_archived_image, from_archived_video,
    },
    types::Sha256Digest,
};

/// Maximum number of bytes restored by one archived media or binary file read.
pub const MAX_ARCHIVED_FILE_BYTES: u64 = MAX_FILE_BYTES;
const MEDIA_RECORD_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct FileRecord {
    id: DocumentId,
    metadata: FileMetadata,
    byte_len: u64,
    sha256: String,
    interpretation_sha256: Sha256Digest,
}

struct FilePayloadRef<'payload> {
    id: &'payload DocumentId,
    metadata: &'payload FileMetadata,
    byte_len: u64,
    bytes: &'payload [u8],
    sha256: &'payload str,
}

async fn write_file_record(
    archive: &Archive,
    kind: RecordKind,
    key: &RecordKey,
    value: FilePayloadRef<'_>,
) -> Result<(), ArchiveError> {
    enforce_file_bound(value.byte_len)?;
    let id = value.id.clone();
    let metadata = value.metadata.clone();
    let sha256 = value.sha256.to_owned();
    let interpretation_sha256 =
        file_interpretation_digest(kind, &id, &metadata, value.byte_len, &sha256).map_err(
            |source| ArchiveError::EncodeRecord {
                kind: kind.as_str(),
                source,
            },
        )?;
    archive.write_document_payload(key, value.bytes).await?;
    archive
        .write_record(
            kind,
            MEDIA_RECORD_SCHEMA_VERSION,
            key,
            &FileRecord {
                id,
                metadata,
                byte_len: value.byte_len,
                sha256,
                interpretation_sha256,
            },
        )
        .await
}

async fn read_file_record(
    archive: &Archive,
    kind: RecordKind,
    format_version: u32,
    key: &RecordKey,
) -> Result<(DocumentId, Arc<Vec<u8>>, FileMetadata), ArchiveError> {
    if format_version != ARCHIVE_FORMAT_VERSION {
        return Err(ArchiveError::UnsupportedFormat {
            found: format_version,
            supported: ARCHIVE_FORMAT_VERSION,
        });
    }
    let record: FileRecord = archive
        .read_record(kind, MEDIA_RECORD_SCHEMA_VERSION, key)
        .await?;
    let interpretation_sha256 = file_interpretation_digest(
        kind,
        &record.id,
        &record.metadata,
        record.byte_len,
        &record.sha256,
    )
    .map_err(|source| ArchiveError::InvalidRecordValue {
        kind: kind.as_str(),
        source,
    })?;
    if interpretation_sha256 != record.interpretation_sha256 {
        return Err(ArchiveError::InvalidFileDocument(
            FileDocumentError::ArchivedMetadataMismatch,
        ));
    }
    enforce_file_bound(record.byte_len)?;
    let bytes = archive.read_document_payload(key, record.byte_len).await?;
    let digest = Sha256Digest::digest(&bytes).to_string();
    if digest != record.sha256 || record.metadata.sha256() != Some(digest.as_str()) {
        return Err(ArchiveError::DocumentPayloadDigestMismatch {
            key: key.to_string(),
        });
    }
    Ok((record.id, Arc::new(bytes), record.metadata))
}

/// Hashes the canonical JSON tuple whose members define a media record's stored interpretation.
/// Tuple order and serialized metadata fields are part of the record schema; changing them or
/// adding future fields requires a versioned reader.
fn file_interpretation_digest(
    kind: RecordKind,
    id: &DocumentId,
    metadata: &FileMetadata,
    byte_len: u64,
    payload_sha256: &str,
) -> Result<Sha256Digest, serde_json::Error> {
    let canonical = serde_json::to_vec(&(
        kind,
        MEDIA_RECORD_SCHEMA_VERSION,
        id,
        metadata,
        byte_len,
        payload_sha256,
    ))?;
    Ok(Sha256Digest::digest(canonical))
}

const fn enforce_file_bound(observed: u64) -> Result<(), ArchiveError> {
    if observed > MAX_ARCHIVED_FILE_BYTES {
        return Err(ArchiveError::DocumentTooLarge {
            maximum: MAX_ARCHIVED_FILE_BYTES,
            observed,
        });
    }
    Ok(())
}

macro_rules! typed_file_archive {
    ($document:ty, $reference:ty, $kind:expr, $construct:ident) => {
        impl sealed::Value for $document {}

        impl ArchiveValue for $document {
            type Reference = $reference;

            async fn write_to<'a>(
                archive: &'a Archive,
                value: &'a Self,
            ) -> Result<Self::Reference, ArchiveError> {
                let reference = <$reference>::new_current();
                write_file_record(
                    archive,
                    $kind,
                    reference.key(),
                    FilePayloadRef {
                        id: value.id(),
                        metadata: value.metadata(),
                        byte_len: value.byte_len(),
                        bytes: value.bytes(),
                        sha256: value.sha256(),
                    },
                )
                .await?;
                Ok(reference)
            }
        }

        impl sealed::Reference for $reference {}

        impl ArchiveReference for $reference {
            type Value = $document;

            async fn read_from<'a>(
                archive: &'a Archive,
                reference: &'a Self,
            ) -> Result<Self::Value, ArchiveError> {
                let (id, bytes, metadata) =
                    read_file_record(archive, $kind, reference.format_version(), reference.key())
                        .await?;
                $construct(id, bytes, metadata).map_err(ArchiveError::InvalidFileDocument)
            }
        }
    };
}

typed_file_archive!(
    ImageDocument,
    ImageDocumentArchiveRef,
    RecordKind::ImageDocument,
    from_archived_image
);
typed_file_archive!(
    VideoDocument,
    VideoDocumentArchiveRef,
    RecordKind::VideoDocument,
    from_archived_video
);
typed_file_archive!(
    AudioDocument,
    AudioDocumentArchiveRef,
    RecordKind::AudioDocument,
    from_archived_audio
);
typed_file_archive!(
    BinaryDocument,
    BinaryDocumentArchiveRef,
    RecordKind::BinaryDocument,
    from_archived_binary
);

impl sealed::Value for FileDocument {}

impl ArchiveValue for FileDocument {
    type Reference = FileDocumentArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        match value {
            Self::Image(document) => archive
                .write(document)
                .await
                .map(FileDocumentArchiveRef::Image),
            Self::Video(document) => archive
                .write(document)
                .await
                .map(FileDocumentArchiveRef::Video),
            Self::Audio(document) => archive
                .write(document)
                .await
                .map(FileDocumentArchiveRef::Audio),
            Self::Binary(document) => archive
                .write(document)
                .await
                .map(FileDocumentArchiveRef::Binary),
        }
    }
}

impl sealed::Reference for FileDocumentArchiveRef {}

impl ArchiveReference for FileDocumentArchiveRef {
    type Value = FileDocument;

    async fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> Result<Self::Value, ArchiveError> {
        match reference {
            Self::Image(reference) => archive.read(reference).await.map(FileDocument::Image),
            Self::Video(reference) => archive.read(reference).await.map(FileDocument::Video),
            Self::Audio(reference) => archive.read(reference).await.map(FileDocument::Audio),
            Self::Binary(reference) => archive.read(reference).await.map(FileDocument::Binary),
        }
    }
}

#[cfg(all(test, unix))]
#[path = "media_tests.rs"]
mod tests;
