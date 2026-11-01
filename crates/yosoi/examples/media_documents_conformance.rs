//! Emit native media-document values for installed-Python parity comparison.
//!
//! Build with `cargo build -p yosoi --example media_documents_conformance`.
//! Fixture bytes are authored here; the Python runner recreates each input through
//! the public SDK, compares complete value snapshots, and checks typed failures.

use std::{
    error::Error,
    io::{self, Write},
};

use serde_json::{Value, json};
use yosoi::documents::{
    FileDocument, FileDocumentError, FileLimits, FileMetadata, ImageDocument, MAX_FILE_BYTES,
    MAX_SOURCE_BYTES, file_from_bytes,
};

#[path = "support/media_documents_conformance.rs"]
mod media_documents_support;
use media_documents_support::{
    authored_metadata, factory_default_case, metadata_value, read_file_case, typed_document_case,
};

const PNG: &[u8] = &[0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];
const JPEG: &[u8] = &[
    0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, b'J', b'F', b'I', b'F', 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
    0x00, 0x01, 0x00, 0x00,
];
const MP4: &[u8] = &[
    0x00, 0x00, 0x00, 0x10, b'f', b't', b'y', b'p', b'm', b'p', b'4', b'2',
];
const MP3: &[u8] = b"ID3\x04\x00\x00\x00\x00\x00\x00";
const WAV: &[u8] = &[
    b'R', b'I', b'F', b'F', 0x24, 0x00, 0x00, 0x00, b'W', b'A', b'V', b'E', b'f', b'm', b't', b' ',
    0x10, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x44, 0xac, 0x00, 0x00, 0x88, 0x58, 0x01, 0x00,
    0x02, 0x00, 0x10, 0x00, b'd', b'a', b't', b'a', 0x00, 0x00, 0x00, 0x00,
];
const OPAQUE: &[u8] = b"unknown application payload";
const SOURCE_OVER_4K: usize = 4_097;

const fn kind(document: &FileDocument) -> &'static str {
    match document {
        FileDocument::Image(_) => "image",
        FileDocument::Video(_) => "video",
        FileDocument::Audio(_) => "audio",
        FileDocument::Binary(_) => "binary",
    }
}

fn snapshot(document: &FileDocument) -> Value {
    json!({
        "kind": kind(document),
        "id": document.id().to_string(),
        "metadata": metadata_value(document.metadata()),
        "bytes": document.bytes(),
        "byte_len": document.byte_len(),
        "sha256": document.sha256(),
    })
}

fn document_case(name: &str, bytes: &[u8], source: String) -> Result<Value, Box<dyn Error>> {
    let id = format!("media-{name}");
    let metadata = authored_metadata(name, source)?;
    let input_metadata = metadata_value(&metadata);
    let limits = FileLimits::default();
    let document = file_from_bytes(id.clone(), bytes.to_vec(), metadata, limits)?;
    Ok(json!({
        "name": name,
        "input": {
            "id": id,
            "bytes": bytes,
            "metadata": input_metadata,
            "limits": {"max_bytes": limits.max_bytes()},
            "omit_optional_arguments": false,
            "rust_arguments": {
                "id": id,
                "bytes": bytes,
                "metadata": input_metadata,
                "limits": {"max_bytes": limits.max_bytes()},
            },
        },
        "rust": snapshot(&document),
    }))
}

fn error_value(error: &FileDocumentError) -> Value {
    let (variant, details) = match error {
        FileDocumentError::TooLarge { maximum, observed } => (
            "TooLarge",
            json!({"maximum": maximum, "observed": observed}),
        ),
        FileDocumentError::LimitExceedsHardMaximum {
            configured,
            maximum,
        } => (
            "LimitExceedsHardMaximum",
            json!({"configured": configured, "maximum": maximum}),
        ),
        FileDocumentError::MetadataTooLong {
            field,
            maximum,
            observed,
        } => (
            "MetadataTooLong",
            json!({"field": field, "maximum": maximum, "observed": observed}),
        ),
        FileDocumentError::TypeMismatch { expected, detected } => (
            "TypeMismatch",
            json!({"expected": expected, "detected": detected}),
        ),
        _ => ("unexpected", json!({"message": error.to_string()})),
    };
    json!({
        "rust_type": "yosoi::documents::FileDocumentError",
        "variant": variant,
        "details": details,
        "source_chain": [],
    })
}

fn error_case(
    name: &str,
    operation: &str,
    input: &Value,
    result: Result<(), FileDocumentError>,
) -> Value {
    let rust = match result {
        Err(error) => error_value(&error),
        Ok(()) => json!({
            "rust_type": "yosoi::documents::FileDocumentError",
            "variant": "unexpected_success",
            "details": {},
            "source_chain": [],
        }),
    };
    json!({"name": name, "operation": operation, "input": input, "rust": rust})
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut cases = Vec::new();
    for (name, bytes) in [
        ("png", PNG),
        ("jpeg", JPEG),
        ("mp4", MP4),
        ("mp3", MP3),
        ("wav", WAV),
        ("opaque", OPAQUE),
        ("empty", &[]),
    ] {
        cases.push(document_case(
            name,
            bytes,
            format!("https://conformance.invalid/{name}"),
        )?);
    }
    let long_source = "s".repeat(SOURCE_OVER_4K);
    cases.push(document_case("source-over-4k", OPAQUE, long_source)?);
    cases.push(read_file_case(PNG).await?);
    for (kind, bytes) in [
        ("image", PNG),
        ("video", MP4),
        ("audio", MP3),
        ("binary", OPAQUE),
    ] {
        for constructor in [
            "from_bytes",
            "from_bytes_with_limits",
            "from_bytes_with_metadata",
        ] {
            cases.push(typed_document_case(kind, constructor, bytes)?);
        }
    }
    cases.push(factory_default_case(OPAQUE)?);

    let standalone_metadata = metadata_value(&FileMetadata::new());
    let typed_mismatch = ImageDocument::from_bytes("wrong-image", OPAQUE.to_vec()).map(|_| ());
    let too_large = file_from_bytes(
        "too-large",
        OPAQUE.to_vec(),
        FileMetadata::new(),
        FileLimits { max_bytes: 2 },
    )
    .map(|_| ());
    let hard_maximum = MAX_FILE_BYTES
        .checked_add(1)
        .ok_or_else(|| io::Error::other("file hard maximum overflow"))?;
    let hard_limit = FileLimits::new(hard_maximum).map(|_| ());
    let source_length = MAX_SOURCE_BYTES
        .checked_add(1)
        .ok_or_else(|| io::Error::other("source maximum overflow"))?;
    let long_source = "s".repeat(source_length);
    let source_limit = FileMetadata::new().with_source(long_source).map(|_| ());

    let error_cases = vec![
        error_case(
            "typed-mismatch",
            "ImageDocument.from_bytes",
            &json!({"id": "wrong-image", "bytes": OPAQUE}),
            typed_mismatch,
        ),
        error_case(
            "payload-too-large",
            "file_from_bytes",
            &json!({"id": "too-large", "bytes": OPAQUE, "max_bytes": 2}),
            too_large,
        ),
        error_case(
            "hard-limit",
            "FileLimits.new",
            &json!({"configured": hard_maximum}),
            hard_limit,
        ),
        error_case(
            "source-over-limit",
            "FileMetadata.with_source",
            &json!({"source_length": source_length}),
            source_limit,
        ),
    ];

    let first =
        ImageDocument::from_bytes_with_limits("same-image", PNG.to_vec(), FileLimits::default())?;
    let exact_limit = u64::try_from(PNG.len())?;
    let second = ImageDocument::from_bytes_with_limits(
        "same-image",
        PNG.to_vec(),
        FileLimits {
            max_bytes: exact_limit,
        },
    )?;
    let different_id = ImageDocument::from_bytes("other-image", PNG.to_vec())?;
    let equality = json!({
        "same_value_different_handles_and_limits": (
            FileDocument::Image(first.clone()) == FileDocument::Image(second)
        ),
        "different_identity": (
            FileDocument::Image(first) == FileDocument::Image(different_id)
        ),
    });

    let output = json!({
        "schemaVersion": 1,
        "kind": "yosoi-media-documents-conformance-fixtures",
        "cases": cases,
        "errorCases": error_cases,
        "standaloneMetadata": standalone_metadata,
        "equality": equality,
        "fileLimits": {
            "defaultMaxBytes": FileLimits::default().max_bytes(),
            "hardMaxBytes": MAX_FILE_BYTES,
            "sourceMaxBytes": MAX_SOURCE_BYTES,
        },
    });
    let stdout = io::stdout();
    let mut writer = stdout.lock();
    serde_json::to_writer(&mut writer, &output)?;
    writer.write_all(b"\n")?;
    Ok(())
}
