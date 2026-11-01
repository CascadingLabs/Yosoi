use serde::{Deserialize, Serialize};

use crate::internal::types::Sha256Digest;

use super::FileDocumentError;

const MAX_FILENAME_BYTES: usize = 1_024;
const MAX_METADATA_VALUE_BYTES: usize = 4_096;

/// Caller and detector metadata retained beside an immutable file payload.
///
/// The caller-supplied filename, media type, source, and capture identifiers
/// remain separate from the detected media type. The SHA-256 digest is filled
/// from exact payload bytes by a document constructor or file factory.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FileMetadata {
    filename: Option<String>,
    declared_media_type: Option<String>,
    detected_media_type: Option<String>,
    source: Option<String>,
    capture_id: Option<String>,
    session_id: Option<String>,
    tab_id: Option<String>,
    download_id: Option<String>,
    sha256: Option<String>,
}

impl FileMetadata {
    /// Creates empty metadata. Payload construction computes detected type and SHA-256.
    pub const fn new() -> Self {
        Self {
            filename: None,
            declared_media_type: None,
            detected_media_type: None,
            source: None,
            capture_id: None,
            session_id: None,
            tab_id: None,
            download_id: None,
            sha256: None,
        }
    }

    /// Sets the caller-provided filename, bounded to 1 KiB of UTF-8 bytes.
    pub fn with_filename(mut self, value: impl Into<String>) -> Result<Self, FileDocumentError> {
        self.filename = Some(checked_metadata_value(
            "filename",
            value.into(),
            MAX_FILENAME_BYTES,
        )?);
        Ok(self)
    }

    /// Sets the caller-declared media type, bounded to 4 KiB of UTF-8 bytes.
    pub fn with_declared_media_type(
        mut self,
        value: impl Into<String>,
    ) -> Result<Self, FileDocumentError> {
        self.declared_media_type = Some(checked_metadata_value(
            "declared_media_type",
            value.into(),
            MAX_METADATA_VALUE_BYTES,
        )?);
        Ok(self)
    }

    /// Sets source provenance such as a request URL or product source label.
    pub fn with_source(mut self, value: impl Into<String>) -> Result<Self, FileDocumentError> {
        self.source = Some(checked_metadata_value(
            "source",
            value.into(),
            MAX_METADATA_VALUE_BYTES,
        )?);
        Ok(self)
    }

    /// Sets the capture identity associated with the file, if available.
    pub fn with_capture_id(mut self, value: impl Into<String>) -> Result<Self, FileDocumentError> {
        self.capture_id = Some(checked_metadata_value(
            "capture_id",
            value.into(),
            MAX_METADATA_VALUE_BYTES,
        )?);
        Ok(self)
    }

    /// Sets the session identity associated with the file, if available.
    pub fn with_session_id(mut self, value: impl Into<String>) -> Result<Self, FileDocumentError> {
        self.session_id = Some(checked_metadata_value(
            "session_id",
            value.into(),
            MAX_METADATA_VALUE_BYTES,
        )?);
        Ok(self)
    }

    /// Sets the tab identity associated with the file, if available.
    pub fn with_tab_id(mut self, value: impl Into<String>) -> Result<Self, FileDocumentError> {
        self.tab_id = Some(checked_metadata_value(
            "tab_id",
            value.into(),
            MAX_METADATA_VALUE_BYTES,
        )?);
        Ok(self)
    }

    /// Sets the download identity associated with the file, if available.
    pub fn with_download_id(mut self, value: impl Into<String>) -> Result<Self, FileDocumentError> {
        self.download_id = Some(checked_metadata_value(
            "download_id",
            value.into(),
            MAX_METADATA_VALUE_BYTES,
        )?);
        Ok(self)
    }

    /// Returns the caller-provided filename, if one was supplied.
    pub fn filename(&self) -> Option<&str> {
        self.filename.as_deref()
    }

    /// Returns the caller-declared media type, if one was supplied.
    pub fn declared_media_type(&self) -> Option<&str> {
        self.declared_media_type.as_deref()
    }

    /// Returns the detected media type when the byte signature is recognized.
    pub fn detected_media_type(&self) -> Option<&str> {
        self.detected_media_type.as_deref()
    }

    /// Returns caller-provided source provenance, if available.
    pub fn source(&self) -> Option<&str> {
        self.source.as_deref()
    }

    /// Returns the associated capture identity, if available.
    pub fn capture_id(&self) -> Option<&str> {
        self.capture_id.as_deref()
    }

    /// Returns the associated session identity, if available.
    pub fn session_id(&self) -> Option<&str> {
        self.session_id.as_deref()
    }

    /// Returns the associated tab identity, if available.
    pub fn tab_id(&self) -> Option<&str> {
        self.tab_id.as_deref()
    }

    /// Returns the associated download identity, if available.
    pub fn download_id(&self) -> Option<&str> {
        self.download_id.as_deref()
    }

    /// Returns the lowercase payload SHA-256, or empty before payload construction.
    pub fn sha256(&self) -> &str {
        self.sha256.as_deref().unwrap_or("")
    }

    pub(super) fn complete_for_payload(&mut self, bytes: &[u8]) {
        self.detected_media_type = infer::get(bytes).map(|kind| kind.mime_type().to_owned());
        self.sha256 = Some(Sha256Digest::digest(bytes).to_string());
    }

    pub(super) fn validate(&self) -> Result<(), FileDocumentError> {
        validate_optional("filename", self.filename.as_deref(), MAX_FILENAME_BYTES)?;
        validate_optional(
            "declared_media_type",
            self.declared_media_type.as_deref(),
            MAX_METADATA_VALUE_BYTES,
        )?;
        validate_optional(
            "detected_media_type",
            self.detected_media_type.as_deref(),
            MAX_METADATA_VALUE_BYTES,
        )?;
        validate_optional("source", self.source.as_deref(), MAX_METADATA_VALUE_BYTES)?;
        validate_optional(
            "capture_id",
            self.capture_id.as_deref(),
            MAX_METADATA_VALUE_BYTES,
        )?;
        validate_optional(
            "session_id",
            self.session_id.as_deref(),
            MAX_METADATA_VALUE_BYTES,
        )?;
        validate_optional("tab_id", self.tab_id.as_deref(), MAX_METADATA_VALUE_BYTES)?;
        validate_optional(
            "download_id",
            self.download_id.as_deref(),
            MAX_METADATA_VALUE_BYTES,
        )?;
        validate_optional("sha256", self.sha256.as_deref(), 64)?;
        Ok(())
    }

    pub(super) fn has_digest(&self, digest: &str) -> bool {
        self.sha256.as_deref() == Some(digest)
    }
}

fn checked_metadata_value(
    field: &'static str,
    value: String,
    maximum: usize,
) -> Result<String, FileDocumentError> {
    if value.len() > maximum {
        return Err(FileDocumentError::MetadataTooLong {
            field,
            maximum,
            observed: value.len(),
        });
    }
    Ok(value)
}

const fn validate_optional(
    field: &'static str,
    value: Option<&str>,
    maximum: usize,
) -> Result<(), FileDocumentError> {
    if let Some(value) = value
        && value.len() > maximum
    {
        return Err(FileDocumentError::MetadataTooLong {
            field,
            maximum,
            observed: value.len(),
        });
    }
    Ok(())
}
