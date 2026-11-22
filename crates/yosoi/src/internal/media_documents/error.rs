use std::{io, path::PathBuf};

use thiserror::Error;

use crate::internal::documents::DocumentError;

/// Invalid or unavailable media and binary file input.
#[derive(Debug, Error)]
pub enum FileDocumentError {
    /// The requested file exceeds the selected byte limit.
    #[error("file payload exceeds {maximum} bytes: observed {observed}")]
    TooLarge {
        /// Largest payload size accepted by the operation.
        maximum: u64,
        /// Exact byte count observed, or the bounded lower bound for a stream.
        observed: u64,
    },
    /// Configured limits exceed the process-wide file hard cap.
    #[error("file limit {configured} bytes exceeds hard maximum {maximum}")]
    LimitExceedsHardMaximum {
        /// Rejected configured limit.
        configured: u64,
        /// Hard maximum accepted by this SDK.
        maximum: u64,
    },
    /// A provenance string exceeds its documented bound.
    #[error("file metadata field {field} exceeds {maximum} bytes: observed {observed}")]
    MetadataTooLong {
        /// Metadata field that exceeded its bound.
        field: &'static str,
        /// Largest UTF-8 byte length accepted for the field.
        maximum: usize,
        /// Observed UTF-8 byte length.
        observed: usize,
    },
    /// Bytes do not match the caller-selected image, video or audio type.
    #[error("file signature does not match requested {expected} type (detected {detected:?})")]
    TypeMismatch {
        /// Requested concrete media type.
        expected: &'static str,
        /// Detected MIME type when the signature is recognized.
        detected: Option<String>,
    },
    /// A response or capture had no retained body bytes to build a file document.
    #[error("file body bytes are unavailable")]
    BodyUnavailable,
    /// Archived provenance does not match the digest of its payload.
    #[error("archived file metadata does not match its payload")]
    ArchivedMetadataMismatch,
    /// The requested file path does not name a regular file.
    #[error("file input is not a regular file: {0}")]
    NotRegularFile(PathBuf),
    /// File identity or byte length failed the existing Document contract.
    #[error(transparent)]
    Document(#[from] DocumentError),
    /// Reading the requested file failed.
    #[error("file read failed at {path}")]
    Io {
        /// File path involved in the failed operation.
        path: PathBuf,
        #[source]
        /// Underlying filesystem failure.
        source: io::Error,
    },
}
