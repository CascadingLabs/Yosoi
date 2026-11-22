#![allow(
    clippy::expect_used,
    reason = "These fixture helpers intentionally fail tests when setup or record mutation cannot complete."
)]

use std::fs;

use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::{
    archive::{
        Archive, ArchiveError, AudioDocumentArchiveRef, BinaryDocumentArchiveRef,
        FileDocumentArchiveRef, ImageDocumentArchiveRef,
    },
    documents::{
        AudioDocument, BinaryDocument, FileDocument, FileDocumentError, FileLimits, FileMetadata,
        ImageDocument, VideoDocument, file_from_bytes,
    },
};

const PNG_SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];
const MP4_SIGNATURE: [u8; 12] = [0, 0, 0, 16, b'f', b't', b'y', b'p', b'm', b'p', b'4', b'2'];
const ID3_SIGNATURE: &[u8] = b"ID3\x04\x00\x00\x00\x00\x00\x00";

#[tokio::test]
async fn media_records_round_trip_from_a_fresh_archive_handle() {
    let directory = tempfile::tempdir().expect("temporary archive directory");
    let archive = Archive::open(directory.path()).await.expect("open archive");
    let image = image_document("image-1");
    let video =
        VideoDocument::from_bytes("video-1", MP4_SIGNATURE.to_vec()).expect("video signature");
    let audio =
        AudioDocument::from_bytes("audio-1", ID3_SIGNATURE.to_vec()).expect("audio signature");
    let binary = BinaryDocument::from_bytes("binary-1", b"opaque".to_vec()).expect("binary bytes");
    let explicit_binary_image = BinaryDocument::from_bytes("binary-image", PNG_SIGNATURE.to_vec())
        .expect("an explicit BinaryDocument retains recognized image bytes");

    let image_ref = archive.write(&image).await.expect("write image");
    let video_ref = archive.write(&video).await.expect("write video");
    let audio_ref: AudioDocumentArchiveRef = archive.write(&audio).await.expect("write audio");
    let binary_ref: BinaryDocumentArchiveRef = archive.write(&binary).await.expect("write binary");
    let explicit_binary_image_ref: BinaryDocumentArchiveRef = archive
        .write(&explicit_binary_image)
        .await
        .expect("write explicit binary with a recognized signature");
    let runtime = file_from_bytes(
        "runtime-image",
        PNG_SIGNATURE.to_vec(),
        FileMetadata::new(),
        FileLimits::default(),
    )
    .expect("classify image bytes");
    let runtime_ref: FileDocumentArchiveRef = archive.write(&runtime).await.expect("write enum");
    let runtime_text = runtime_ref.to_string();
    drop(archive);

    let reopened = Archive::open(directory.path())
        .await
        .expect("reopen archive with a fresh handle");
    let image_copy: ImageDocument = reopened.read(&image_ref).await.expect("read image");
    let video_copy: VideoDocument = reopened.read(&video_ref).await.expect("read video");
    let audio_copy: AudioDocument = reopened.read(&audio_ref).await.expect("read audio");
    let binary_copy: BinaryDocument = reopened.read(&binary_ref).await.expect("read binary");
    let explicit_binary_image_copy: BinaryDocument = reopened
        .read(&explicit_binary_image_ref)
        .await
        .expect("read explicit binary with a recognized signature");
    let runtime_ref: FileDocumentArchiveRef = runtime_text
        .parse()
        .expect("parse runtime string reference");
    let runtime_copy: FileDocument = reopened.read(&runtime_ref).await.expect("read enum");

    // This is only the eight-byte PNG signature, not a complete image to decode.
    assert_eq!(image_copy.bytes(), PNG_SIGNATURE);
    assert_eq!(image_copy.id().as_str(), "image-1");
    assert_eq!(
        image_copy.metadata().source(),
        Some("https://example.test/image.png")
    );
    assert_eq!(video_copy.bytes(), MP4_SIGNATURE);
    assert_eq!(audio_copy.bytes(), ID3_SIGNATURE);
    assert_eq!(binary_copy.bytes(), b"opaque");
    assert_eq!(explicit_binary_image_copy.bytes(), PNG_SIGNATURE);
    assert_eq!(
        explicit_binary_image_copy.metadata().detected_media_type(),
        Some("image/png")
    );
    assert!(matches!(runtime_copy, FileDocument::Image(_)));
    assert!(matches!(runtime_ref, FileDocumentArchiveRef::Image(_)));
}

#[tokio::test]
async fn changed_detected_mime_is_rejected_without_changing_payload_hashes() {
    let directory = tempfile::tempdir().expect("temporary archive directory");
    let archive = Archive::open(directory.path()).await.expect("open archive");
    let reference = archive
        .write(&image_document("image-mime"))
        .await
        .expect("write image");
    let path = image_record_path(&archive, &reference);
    let mut record = read_record(&path);
    let payload_sha256 = record["value"]["sha256"].clone();
    let metadata_sha256 = record["value"]["metadata"]["sha256"].clone();
    assert_eq!(
        record["value"]["metadata"]["detected_media_type"],
        "image/png"
    );
    record["value"]["metadata"]["detected_media_type"] = Value::String("image/jpeg".to_owned());
    assert_eq!(record["value"]["sha256"], payload_sha256);
    assert_eq!(record["value"]["metadata"]["sha256"], metadata_sha256);
    write_record(&path, &record);

    assert_archived_metadata_mismatch(&archive, &reference).await;
}

#[tokio::test]
async fn changed_source_or_id_is_rejected() {
    let directory = tempfile::tempdir().expect("temporary archive directory");
    let archive = Archive::open(directory.path()).await.expect("open archive");
    let id_reference = archive
        .write(&image_document("image-id"))
        .await
        .expect("write id image");
    let source_reference = archive
        .write(&image_document("image-source"))
        .await
        .expect("write source image");

    let id_path = image_record_path(&archive, &id_reference);
    let mut id_record = read_record(&id_path);
    id_record["value"]["id"] = Value::String("rewritten-image-id".to_owned());
    write_record(&id_path, &id_record);
    assert_archived_metadata_mismatch(&archive, &id_reference).await;

    let source_path = image_record_path(&archive, &source_reference);
    let mut source_record = read_record(&source_path);
    source_record["value"]["metadata"]["source"] =
        Value::String("https://example.test/rewritten.png".to_owned());
    write_record(&source_path, &source_record);
    assert_archived_metadata_mismatch(&archive, &source_reference).await;
}

fn image_document(id: &str) -> ImageDocument {
    let metadata = FileMetadata::new()
        .with_source("https://example.test/image.png")
        .expect("valid image source");
    ImageDocument::from_bytes_with_metadata(
        id,
        PNG_SIGNATURE.to_vec(),
        metadata,
        FileLimits::default(),
    )
    .expect("image signature")
}

async fn assert_archived_metadata_mismatch(archive: &Archive, reference: &ImageDocumentArchiveRef) {
    assert!(matches!(
        archive.read(reference).await,
        Err(ArchiveError::InvalidFileDocument(
            FileDocumentError::ArchivedMetadataMismatch
        ))
    ));
}

fn image_record_path(archive: &Archive, reference: &ImageDocumentArchiveRef) -> PathBuf {
    let key = reference.logical_key();
    let shard: String = key.chars().take(2).collect();
    archive
        .format_root()
        .join("records")
        .join("image-document")
        .join(shard)
        .join(format!("{key}.json"))
}

fn read_record(path: &Path) -> Value {
    serde_json::from_slice(&fs::read(path).expect("read archive record"))
        .expect("decode archive record")
}

fn write_record(path: &Path, record: &Value) {
    fs::write(
        path,
        serde_json::to_vec(record).expect("encode archive record"),
    )
    .expect("write archive record");
}
