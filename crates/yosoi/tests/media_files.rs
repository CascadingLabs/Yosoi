//! File families and Archive corruption are verified through the public SDK.
#![allow(
    clippy::panic_in_result_fn,
    reason = "Assertions report contract failures"
)]
use std::error::Error;
use tokio::fs;
use yosoi::{
    Archive, Document,
    documents::{
        BinaryDocument, FileDocument, FileLimits, FileMetadata, file_from_bytes, read_file,
    },
};

type TestResult = Result<(), Box<dyn Error + Send + Sync>>;

#[test]
fn named_media_formats_are_recognized_without_decoder_dependencies() -> TestResult {
    let cases: &[(&[u8], &str)] = &[
        (b"\xff\xd8\xff\xe0JPEG", "image"),
        (b"\x89PNG\r\n\x1a\n", "image"),
        (b"\x00\x00\x00\x10ftypmp42", "video"),
        (b"ID3\x04\x00\x00\x00\x00\x00\x00", "audio"),
        (b"RIFF\x24\x00\x00\x00WAVEfmt ", "audio"),
        (b"%PDF-1.7\n", "binary"),
        (b"", "binary"),
    ];
    for (bytes, expected) in cases {
        let file = file_from_bytes(
            "fixture",
            bytes.to_vec(),
            FileMetadata::new(),
            FileLimits::default(),
        )?;
        let actual = match file {
            FileDocument::Image(_) => "image",
            FileDocument::Video(_) => "video",
            FileDocument::Audio(_) => "audio",
            FileDocument::Binary(_) => "binary",
        };
        assert_eq!(actual, *expected);
    }
    Ok(())
}

#[tokio::test]
#[cfg(unix)]
async fn archive_rejects_changed_payload_and_retains_file_after_original_disappears() -> TestResult
{
    let directory = tempfile::tempdir()?;
    let input = directory.path().join("input.bin");
    fs::write(&input, b"original").await?;
    let file = read_file("owned", &input, FileLimits::default()).await?;
    fs::remove_file(&input).await?;
    let archive = Archive::open(directory.path().join("store")).await?;
    let reference = archive.write(&file).await?;
    let reopened = Archive::open(directory.path().join("store")).await?;
    let restored = reopened.read(&reference).await?;
    assert_eq!(restored.bytes(), b"original");
    let binary = BinaryDocument::from_bytes("corrupt", b"original".to_vec())?;
    let binary_ref = archive.write(&binary).await?;
    let key = binary_ref.logical_key();
    let shard = key.get(..2).ok_or("invalid reference key")?;
    let payload = archive
        .format_root()
        .join("documents")
        .join(shard)
        .join(key)
        .join("payload.bin");
    fs::write(payload, b"modified").await?;
    assert!(reopened.read(&binary_ref).await.is_err());
    let legacy = Document::text("old", b"legacy".to_vec())?;
    let legacy_ref = archive.write_document(&legacy).await?;
    assert_eq!(
        reopened.read_document(&legacy_ref).await?.bytes(),
        b"legacy"
    );
    Ok(())
}
