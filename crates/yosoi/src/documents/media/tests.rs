use super::{
    AudioDocument, BinaryDocument, FileDocument, FileDocumentError, FileLimits, FileMetadata,
    ImageDocument, VideoDocument, file_from_bytes, read_file,
};
use tokio::fs;

const PNG_SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];
const MP4_SIGNATURE: [u8; 12] = [0, 0, 0, 16, b'f', b't', b'y', b'p', b'm', b'p', b'4', b'2'];
const ID3_SIGNATURE: &[u8] = b"ID3\x04\x00\x00\x00\x00\x00\x00";

#[test]
fn typed_documents_retain_opaque_bytes_and_canonical_digest() {
    let document =
        BinaryDocument::from_bytes("binary-1", b"abc".to_vec()).expect("valid binary document");

    assert_eq!(document.bytes(), b"abc");
    assert_eq!(document.byte_len(), 3);
    assert_eq!(
        document.sha256(),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    assert_eq!(document.metadata().sha256(), document.sha256());
}

#[test]
fn limits_reject_oversize_payloads_and_hard_caps() {
    let too_many = BinaryDocument::from_bytes_with_limits(
        "binary-1",
        vec![1, 2, 3],
        FileLimits { max_bytes: 2 },
    );
    assert!(matches!(too_many, Err(FileDocumentError::TooLarge { .. })));

    let invalid = FileLimits::new(super::MAX_FILE_BYTES + 1);
    assert!(matches!(
        invalid,
        Err(FileDocumentError::LimitExceedsHardMaximum { .. })
    ));
}

#[test]
fn file_factory_classifies_signatures_without_decoding() {
    let image = file_from_bytes(
        "image-1",
        PNG_SIGNATURE.to_vec(),
        FileMetadata::new(),
        FileLimits::default(),
    )
    .expect("PNG signature should classify opaque bytes");
    assert!(matches!(image, FileDocument::Image(_)));

    let video = file_from_bytes(
        "video-1",
        MP4_SIGNATURE.to_vec(),
        FileMetadata::new(),
        FileLimits::default(),
    )
    .expect("MP4 signature should classify opaque bytes");
    assert!(matches!(video, FileDocument::Video(_)));

    let audio = file_from_bytes(
        "audio-1",
        ID3_SIGNATURE.to_vec(),
        FileMetadata::new(),
        FileLimits::default(),
    )
    .expect("audio signature should classify opaque bytes");
    assert!(matches!(audio, FileDocument::Audio(_)));

    let binary = file_from_bytes(
        "binary-2",
        b"unknown bytes".to_vec(),
        FileMetadata::new(),
        FileLimits::default(),
    )
    .expect("unrecognized bytes remain binary");
    assert!(matches!(binary, FileDocument::Binary(_)));
}

#[test]
fn typed_media_constructors_require_matching_signatures() {
    let image = ImageDocument::from_bytes("image-typed", PNG_SIGNATURE.to_vec())
        .expect("image signature matches");
    assert_eq!(image.bytes(), PNG_SIGNATURE);
    assert!(matches!(
        ImageDocument::from_bytes("wrong-image", b"opaque".to_vec()),
        Err(FileDocumentError::TypeMismatch { .. })
    ));
    assert!(matches!(
        VideoDocument::from_bytes("wrong-video", PNG_SIGNATURE.to_vec()),
        Err(FileDocumentError::TypeMismatch { .. })
    ));
    assert!(matches!(
        AudioDocument::from_bytes("wrong-audio", b"opaque".to_vec()),
        Err(FileDocumentError::TypeMismatch { .. })
    ));

    let binary = BinaryDocument::from_bytes("binary-image", PNG_SIGNATURE.to_vec())
        .expect("explicit BinaryDocument keeps any bytes");
    assert_eq!(binary.metadata().detected_media_type(), Some("image/png"));
}

#[test]
fn file_metadata_keeps_declared_and_detected_types_separate() {
    let metadata = FileMetadata::new()
        .with_filename("picture.bin")
        .expect("short filename")
        .with_declared_media_type("application/octet-stream")
        .expect("short declared type")
        .with_source("https://example.test/picture")
        .expect("short source");
    let document = ImageDocument::from_bytes_with_metadata(
        "image-2",
        PNG_SIGNATURE.to_vec(),
        metadata,
        FileLimits::default(),
    )
    .expect("declared type does not override recognized bytes");

    assert_eq!(document.metadata().filename(), Some("picture.bin"));
    assert_eq!(
        document.metadata().declared_media_type(),
        Some("application/octet-stream")
    );
    assert_eq!(document.metadata().detected_media_type(), Some("image/png"));
    assert_eq!(
        document.metadata().source(),
        Some("https://example.test/picture")
    );
}

#[tokio::test]
async fn read_file_bounds_the_read_and_records_only_the_basename() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let path = directory.path().join("blob.bin");
    fs::write(&path, b"12345").await.expect("write test file");

    let too_large = read_file("file-1", &path, FileLimits { max_bytes: 4 }).await;
    assert!(matches!(too_large, Err(FileDocumentError::TooLarge { .. })));

    let document = read_file("file-1", &path, FileLimits { max_bytes: 5 })
        .await
        .expect("bounded read at exact file size");
    assert_eq!(document.bytes(), b"12345");
    assert_eq!(document.metadata().filename(), Some("blob.bin"));
    assert_eq!(document.metadata().source(), None);
}
