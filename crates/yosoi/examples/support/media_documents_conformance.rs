//! Shared construction helpers for the media-document conformance example.

use std::{error::Error, io};

use super::snapshot;
use serde_json::{Value, json};
use tokio::fs;
use yosoi::documents::{
    AudioDocument, BinaryDocument, FileDocument, FileDocumentError, FileLimits, FileMetadata,
    ImageDocument, VideoDocument, file_from_bytes, read_file,
};

pub fn metadata_value(metadata: &FileMetadata) -> Value {
    json!({
        "filename": metadata.filename(),
        "declared_media_type": metadata.declared_media_type(),
        "detected_media_type": metadata.detected_media_type(),
        "source": metadata.source(),
        "capture_id": metadata.capture_id(),
        "session_id": metadata.session_id(),
        "tab_id": metadata.tab_id(),
        "download_id": metadata.download_id(),
        "probe_validated_video_container": metadata.probe_validated_video_container(),
        "sha256": metadata.sha256(),
    })
}

pub fn authored_metadata(name: &str, source: String) -> Result<FileMetadata, FileDocumentError> {
    FileMetadata::new()
        .with_filename(format!("{name}.bin"))?
        .with_declared_media_type("application/octet-stream")?
        .with_source(source)?
        .with_capture_id("capture-media-conformance")?
        .with_session_id("session-media-conformance")?
        .with_tab_id("tab-media-conformance")?
        .with_download_id(format!("download-{name}"))
}

pub fn typed_document_case(
    kind: &str,
    constructor: &str,
    bytes: &[u8],
) -> Result<Value, Box<dyn Error>> {
    let name = format!("typed-{kind}-{constructor}");
    let id = format!("{name}-id");
    let source = format!("https://conformance.invalid/{name}");
    let metadata = if constructor == "from_bytes_with_metadata" {
        authored_metadata(&name, source)?
    } else {
        FileMetadata::new()
    };
    let metadata_input = metadata_value(&metadata);
    let byte_limit = u64::try_from(bytes.len())?;
    let limits = if constructor == "from_bytes_with_limits" {
        FileLimits {
            max_bytes: byte_limit,
        }
    } else {
        FileLimits::default()
    };
    let limits_input = if constructor == "from_bytes" {
        Value::Null
    } else {
        json!({"max_bytes": limits.max_bytes()})
    };
    let document = match (kind, constructor) {
        ("image", "from_bytes") => {
            FileDocument::Image(ImageDocument::from_bytes(id.clone(), bytes.to_vec())?)
        }
        ("video", "from_bytes") => {
            FileDocument::Video(VideoDocument::from_bytes(id.clone(), bytes.to_vec())?)
        }
        ("audio", "from_bytes") => {
            FileDocument::Audio(AudioDocument::from_bytes(id.clone(), bytes.to_vec())?)
        }
        ("binary", "from_bytes") => {
            FileDocument::Binary(BinaryDocument::from_bytes(id.clone(), bytes.to_vec())?)
        }
        ("image", "from_bytes_with_limits") => FileDocument::Image(
            ImageDocument::from_bytes_with_limits(id.clone(), bytes.to_vec(), limits)?,
        ),
        ("video", "from_bytes_with_limits") => FileDocument::Video(
            VideoDocument::from_bytes_with_limits(id.clone(), bytes.to_vec(), limits)?,
        ),
        ("audio", "from_bytes_with_limits") => FileDocument::Audio(
            AudioDocument::from_bytes_with_limits(id.clone(), bytes.to_vec(), limits)?,
        ),
        ("binary", "from_bytes_with_limits") => FileDocument::Binary(
            BinaryDocument::from_bytes_with_limits(id.clone(), bytes.to_vec(), limits)?,
        ),
        ("image", "from_bytes_with_metadata") => FileDocument::Image(
            ImageDocument::from_bytes_with_metadata(id.clone(), bytes.to_vec(), metadata, limits)?,
        ),
        ("video", "from_bytes_with_metadata") => FileDocument::Video(
            VideoDocument::from_bytes_with_metadata(id.clone(), bytes.to_vec(), metadata, limits)?,
        ),
        ("audio", "from_bytes_with_metadata") => FileDocument::Audio(
            AudioDocument::from_bytes_with_metadata(id.clone(), bytes.to_vec(), metadata, limits)?,
        ),
        ("binary", "from_bytes_with_metadata") => FileDocument::Binary(
            BinaryDocument::from_bytes_with_metadata(id.clone(), bytes.to_vec(), metadata, limits)?,
        ),
        _ => return Err(io::Error::other("unknown typed media fixture").into()),
    };
    let rust_arguments = match constructor {
        "from_bytes" => json!({"id": id, "bytes": bytes}),
        "from_bytes_with_limits" => json!({
            "id": id,
            "bytes": bytes,
            "limits": {"max_bytes": limits.max_bytes()},
        }),
        "from_bytes_with_metadata" => json!({
            "id": id,
            "bytes": bytes,
            "metadata": metadata_input,
            "limits": {"max_bytes": limits.max_bytes()},
        }),
        _ => return Err(io::Error::other("unknown typed media fixture").into()),
    };
    Ok(json!({
        "name": name,
        "input": {
            "id": id,
            "bytes": bytes,
            "metadata": metadata_input,
            "limits": limits_input,
            "constructor": constructor,
            "omit_optional_arguments": constructor == "from_bytes",
            "rust_arguments": rust_arguments,
        },
        "rust": snapshot(&document),
    }))
}

pub fn factory_default_case(bytes: &[u8]) -> Result<Value, Box<dyn Error>> {
    let id = "media-factory-defaults".to_owned();
    let metadata = FileMetadata::new();
    let limits = FileLimits::default();
    let metadata_input = metadata_value(&metadata);
    let limits_input = json!({"max_bytes": limits.max_bytes()});
    let document = file_from_bytes(id.clone(), bytes.to_vec(), metadata, limits)?;
    Ok(json!({
        "name": "factory-defaults",
        "input": {
            "id": id,
            "bytes": bytes,
            "metadata": metadata_input,
            "limits": limits_input,
            "omit_optional_arguments": true,
            "rust_arguments": {
                "id": id,
                "bytes": bytes,
                "metadata": metadata_input,
                "limits": limits_input,
            },
        },
        "rust": snapshot(&document),
    }))
}

pub async fn read_file_case(bytes: &[u8]) -> Result<Value, Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let filename = "media-read-fixture.png";
    let path = directory.path().join(filename);
    fs::write(&path, bytes).await?;
    let id = "media-local-read".to_owned();
    let max_bytes = u64::try_from(bytes.len())?;
    let limits = FileLimits { max_bytes };
    let document = read_file(id.clone(), &path, limits).await?;
    Ok(json!({
        "name": "local-read",
        "input": {
            "id": id,
            "bytes": bytes,
            "filename": filename,
            "metadata": {"filename": filename},
            "limits": {"max_bytes": limits.max_bytes()},
            "rust_arguments": {
                "id": id,
                "path": filename,
                "limits": {"max_bytes": limits.max_bytes()},
            },
        },
        "rust": snapshot(&document),
    }))
}
