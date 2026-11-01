use crate::internal::documents::DocumentId;
use std::sync::Arc;

use serde::{Deserialize, Serialize};

use crate::{
    documents::{
        AudioDocument, BinaryDocument, FileDocument, FileMetadata, ImageDocument, MAX_FILE_BYTES,
        VideoDocument, from_archived_audio, from_archived_binary, from_archived_image,
        from_archived_video,
    },
    internal::{
        archive::{
            Archive, ArchiveError, AudioDocumentArchiveRef, BinaryDocumentArchiveRef,
            FileDocumentArchiveRef, ImageDocumentArchiveRef, VideoDocumentArchiveRef,
            dispatch::{ArchiveReference, ArchiveValue, sealed},
            refs::RecordKey,
            wire::{ARCHIVE_FORMAT_VERSION, RecordKind},
        },
        types::Sha256Digest,
    },
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
    archive.write_document_payload(key, value.bytes).await?;
    archive
        .write_record(
            kind,
            MEDIA_RECORD_SCHEMA_VERSION,
            key,
            &FileRecord {
                id: value.id.clone(),
                metadata: value.metadata.clone(),
                byte_len: value.byte_len,
                sha256: value.sha256.to_owned(),
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
    enforce_file_bound(record.byte_len)?;
    let bytes = archive.read_document_payload(key, record.byte_len).await?;
    let digest = Sha256Digest::digest(&bytes).to_string();
    if digest != record.sha256 || record.metadata.sha256() != digest.as_str() {
        return Err(ArchiveError::DocumentPayloadDigestMismatch {
            key: key.to_string(),
        });
    }
    Ok((record.id, Arc::new(bytes), record.metadata))
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
mod tests {
    use crate::{
        archive::{
            Archive, AudioDocumentArchiveRef, BinaryDocumentArchiveRef, FileDocumentArchiveRef,
        },
        documents::{
            AudioDocument, BinaryDocument, FileDocument, FileLimits, FileMetadata, ImageDocument,
            VideoDocument, file_from_bytes,
        },
    };

    const PNG_SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];
    const MP4_SIGNATURE: [u8; 12] = [0, 0, 0, 16, b'f', b't', b'y', b'p', b'm', b'p', b'4', b'2'];
    const ID3_SIGNATURE: &[u8] = b"ID3\x04\x00\x00\x00\x00\x00\x00";

    #[tokio::test]
    async fn media_records_round_trip_from_a_fresh_archive_handle() {
        let directory = tempfile::tempdir().expect("temporary archive directory");
        let archive = Archive::open(directory.path()).await.expect("open archive");
        let image =
            ImageDocument::from_bytes("image-1", PNG_SIGNATURE.to_vec()).expect("image signature");
        let video =
            VideoDocument::from_bytes("video-1", MP4_SIGNATURE.to_vec()).expect("video signature");
        let audio =
            AudioDocument::from_bytes("audio-1", ID3_SIGNATURE.to_vec()).expect("audio signature");
        let binary =
            BinaryDocument::from_bytes("binary-1", b"opaque".to_vec()).expect("binary bytes");

        let image_ref = archive.write(&image).await.expect("write image");
        let video_ref = archive.write(&video).await.expect("write video");
        let audio_ref: AudioDocumentArchiveRef = archive.write(&audio).await.expect("write audio");
        let binary_ref: BinaryDocumentArchiveRef =
            archive.write(&binary).await.expect("write binary");
        let runtime = file_from_bytes(
            "runtime-image",
            PNG_SIGNATURE.to_vec(),
            FileMetadata::new(),
            FileLimits::default(),
        )
        .expect("classify image bytes");
        let runtime_ref: FileDocumentArchiveRef =
            archive.write(&runtime).await.expect("write enum");
        let runtime_text = runtime_ref.to_string();
        drop(archive);

        let reopened = Archive::open(directory.path())
            .await
            .expect("reopen archive with a fresh handle");
        let image_copy: ImageDocument = reopened.read(&image_ref).await.expect("read image");
        let video_copy: VideoDocument = reopened.read(&video_ref).await.expect("read video");
        let audio_copy: AudioDocument = reopened.read(&audio_ref).await.expect("read audio");
        let binary_copy: BinaryDocument = reopened.read(&binary_ref).await.expect("read binary");
        let runtime_ref: FileDocumentArchiveRef = runtime_text
            .parse()
            .expect("parse runtime string reference");
        let runtime_copy: FileDocument = reopened.read(&runtime_ref).await.expect("read enum");

        assert_eq!(image_copy.bytes(), PNG_SIGNATURE);
        assert_eq!(video_copy.bytes(), MP4_SIGNATURE);
        assert_eq!(audio_copy.bytes(), ID3_SIGNATURE);
        assert_eq!(binary_copy.bytes(), b"opaque");
        assert!(matches!(runtime_copy, FileDocument::Image(_)));
        assert!(matches!(runtime_ref, FileDocumentArchiveRef::Image(_)));
    }
}
