//! Python-owned immutable views over native media and opaque file documents.

use std::{error::Error, path::PathBuf, sync::Arc};

use pyo3::{exceptions::PyValueError, prelude::*, types::PyBytes};
use serde_json::json;
use yosoi::documents::{
    AudioDocument, BinaryDocument, FileDocument, FileDocumentError as SdkFileDocumentError,
    FileLimits, FileMetadata, ImageDocument, MAX_FILE_BYTES, VideoDocument, file_from_bytes,
    read_file as sdk_read_file,
};

use crate::{async_runtime, errors};

pub fn file_document_error(error: &SdkFileDocumentError) -> PyErr {
    let (variant, details) = match error {
        SdkFileDocumentError::TooLarge { maximum, observed } => (
            "TooLarge",
            json!({"maximum": maximum, "observed": observed}),
        ),
        SdkFileDocumentError::LimitExceedsHardMaximum {
            configured,
            maximum,
        } => (
            "LimitExceedsHardMaximum",
            json!({"configured": configured, "maximum": maximum}),
        ),
        SdkFileDocumentError::MetadataTooLong {
            field,
            maximum,
            observed,
        } => (
            "MetadataTooLong",
            json!({"field": field, "maximum": maximum, "observed": observed}),
        ),
        SdkFileDocumentError::TypeMismatch { expected, detected } => (
            "TypeMismatch",
            json!({"expected": expected, "detected": detected}),
        ),
        SdkFileDocumentError::BodyUnavailable => ("BodyUnavailable", json!({})),
        SdkFileDocumentError::ArchivedMetadataMismatch => ("ArchivedMetadataMismatch", json!({})),
        SdkFileDocumentError::NotRegularFile(path) => {
            ("NotRegularFile", json!({"path": path.to_string_lossy()}))
        }
        SdkFileDocumentError::Document(source) => {
            ("Document", json!({"message": source.to_string()}))
        }
        SdkFileDocumentError::Io { path, .. } => ("Io", json!({"path": path.to_string_lossy()})),
    };
    let sources = error
        .source()
        .map(|source| vec![source.to_string()])
        .unwrap_or_default();
    Python::attach(|py| {
        errors::with_metadata(
            py,
            errors::FileDocumentError::new_err(error.to_string()),
            "yosoi::documents::FileDocumentError",
            Some(variant),
            details,
            &sources,
        )
    })
}

fn decode_metadata(py: Python<'_>, value: &str) -> PyResult<FileMetadata> {
    serde_json::from_str(value).map_err(|error| {
        errors::serde_decode_error(
            py,
            errors::FileDocumentError::new_err(error.to_string()),
            &error,
        )
    })
}

/// Applies one Rust-validated FileMetadata builder and returns the retained JSON value.
#[pyfunction]
pub fn file_metadata_with(
    py: Python<'_>,
    metadata_json: &str,
    field: &str,
    value: &str,
) -> PyResult<String> {
    let metadata = decode_metadata(py, metadata_json)?;
    let metadata = match field {
        "filename" => metadata.with_filename(value),
        "declared_media_type" => metadata.with_declared_media_type(value),
        "source" => metadata.with_source(value),
        "capture_id" => metadata.with_capture_id(value),
        "session_id" => metadata.with_session_id(value),
        "tab_id" => metadata.with_tab_id(value),
        "download_id" => metadata.with_download_id(value),
        _ => {
            return Err(PyValueError::new_err("unknown FileMetadata field"));
        }
    }
    .map_err(|error| file_document_error(&error))?;
    serde_json::to_string(&metadata).map_err(|error| {
        errors::serde_encode_error(
            py,
            errors::FileDocumentError::new_err(error.to_string()),
            &error,
        )
    })
}

pub fn decode_limits(py: Python<'_>, value: &str) -> PyResult<FileLimits> {
    let limits: FileLimits = serde_json::from_str(value).map_err(|error| {
        errors::serde_decode_error(
            py,
            errors::FileDocumentError::new_err(error.to_string()),
            &error,
        )
    })?;
    if limits.max_bytes > MAX_FILE_BYTES {
        return Err(file_document_error(
            &SdkFileDocumentError::LimitExceedsHardMaximum {
                configured: limits.max_bytes,
                maximum: MAX_FILE_BYTES,
            },
        ));
    }
    Ok(limits)
}

/// The concrete document variant is selected in Rust and owns the exact payload.
#[pyclass(
    frozen,
    skip_from_py_object,
    module = "yosoi._native",
    name = "FileDocument"
)]
#[derive(Clone, Debug)]
pub struct NativeFileDocument {
    pub(crate) inner: Arc<FileDocument>,
}

impl NativeFileDocument {
    pub(crate) fn new(inner: FileDocument) -> Self {
        Self {
            inner: Arc::new(inner),
        }
    }
}

#[pymethods]
impl NativeFileDocument {
    /// Build an explicitly typed or inferred file document without decoding payload bytes.
    #[new]
    fn construct(
        py: Python<'_>,
        id: &str,
        content: &Bound<'_, PyBytes>,
        kind: &str,
        metadata_json: &str,
        limits_json: &str,
    ) -> PyResult<Self> {
        let metadata = decode_metadata(py, metadata_json)?;
        let limits = decode_limits(py, limits_json)?;
        let content = content.as_bytes();
        let Ok(observed) = u64::try_from(content.len()) else {
            return Err(file_document_error(&SdkFileDocumentError::TooLarge {
                maximum: limits.max_bytes,
                observed: u64::MAX,
            }));
        };
        if observed > limits.max_bytes {
            return Err(file_document_error(&SdkFileDocumentError::TooLarge {
                maximum: limits.max_bytes,
                observed,
            }));
        }
        let content = content.to_vec();
        let inner = match kind {
            "infer" => file_from_bytes(id, content, metadata, limits),
            "image" => ImageDocument::from_bytes_with_metadata(id, content, metadata, limits)
                .map(FileDocument::Image),
            "video" => VideoDocument::from_bytes_with_metadata(id, content, metadata, limits)
                .map(FileDocument::Video),
            "audio" => AudioDocument::from_bytes_with_metadata(id, content, metadata, limits)
                .map(FileDocument::Audio),
            "binary" => BinaryDocument::from_bytes_with_metadata(id, content, metadata, limits)
                .map(FileDocument::Binary),
            _ => {
                return Err(errors::FileDocumentError::new_err(
                    "kind must be infer, image, video, audio, or binary",
                ));
            }
        }
        .map_err(|error| file_document_error(&error))?;
        Ok(Self::new(inner))
    }

    #[getter]
    fn id(&self) -> &str {
        self.inner.id().as_str()
    }

    fn kind(&self) -> &'static str {
        match self.inner.as_ref() {
            FileDocument::Image(_) => "image",
            FileDocument::Video(_) => "video",
            FileDocument::Audio(_) => "audio",
            FileDocument::Binary(_) => "binary",
        }
    }

    fn metadata(&self, py: Python<'_>) -> PyResult<String> {
        serde_json::to_string(self.inner.metadata()).map_err(|error| {
            errors::serde_encode_error(
                py,
                errors::FileDocumentError::new_err(error.to_string()),
                &error,
            )
        })
    }

    fn bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.inner.bytes())
    }

    #[getter]
    fn byte_len(&self) -> u64 {
        self.inner.byte_len()
    }

    #[getter]
    fn sha256(&self) -> &str {
        self.inner.sha256()
    }

    fn validate_input(
        &self,
        py: Python<'_>,
        id: &str,
        kind: &str,
        metadata_json: &str,
    ) -> PyResult<()> {
        let metadata = decode_metadata(py, metadata_json)?;
        if self.id() != id || self.kind() != kind || self.inner.metadata() != &metadata {
            return Err(errors::FileDocumentError::new_err(
                "file document values do not match the native source",
            ));
        }
        Ok(())
    }
}

/// Read a bounded local file and return its Rust-classified file document.
#[pyfunction]
#[pyo3(signature = (id, path, limits_json))]
pub fn read_file<'py>(
    py: Python<'py>,
    id: &str,
    path: PathBuf,
    limits_json: &str,
) -> PyResult<Bound<'py, PyAny>> {
    let limits = decode_limits(py, limits_json)?;
    let id = id.to_owned();
    async_runtime::bridge(py, None, move |_| async move {
        sdk_read_file(id, path, limits)
            .await
            .map(NativeFileDocument::new)
            .map_err(|error| file_document_error(&error))
    })
}
