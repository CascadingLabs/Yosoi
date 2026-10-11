use std::io;
use std::path::PathBuf;

use crate::internal::documents::DocumentError;
use crate::internal::policy::PolicyError;
use crate::internal::types::{ArtifactId, CaptureId};
use crate::internal::web_capture::{CaptureBundleError, WebArtifactRef, WebCaptureWireError};
use thiserror::Error;
use tokio::task::JoinError;

use crate::internal::archive::{
    ArchiveRefError, ContractRunRecordError, EvaluationRunError, LocatorRunRecordError,
    RequestRunRecordError,
};

/// Typed failures from the local Archive boundary.
#[derive(Debug, Error)]
pub enum ArchiveError {
    #[error("local Archive format 1 is not certified on platform {platform}")]
    UnsupportedPlatform { platform: &'static str },
    #[error("an Archive root path cannot be empty")]
    EmptyRoot,
    #[error(transparent)]
    InvalidReference(#[from] ArchiveRefError),
    #[error("Archive {operation} failed at {path}")]
    Io {
        operation: &'static str,
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("Archive filesystem task failed during {operation}")]
    FilesystemTask {
        operation: &'static str,
        #[source]
        source: JoinError,
    },
    #[error("Archive-owned path {path} is unsafe: {reason}")]
    UnsafeArchivePath { path: PathBuf, reason: &'static str },
    #[error("Archive-owned path {path} has insecure permissions {mode:#o}")]
    InsecurePermissions { path: PathBuf, mode: u32 },
    #[error("Archive {kind} record {key} does not exist")]
    RecordNotFound { kind: &'static str, key: String },
    #[error("Archive record at {path} is not a regular file")]
    NotRegularFile { path: PathBuf },
    #[error("Archive record is too large: maximum {maximum} bytes, observed {observed}")]
    RecordTooLarge { maximum: u64, observed: u64 },
    #[error("invalid Policy value")]
    InvalidPolicy(#[source] PolicyError),
    #[error("invalid request run record")]
    InvalidRequestRun(#[source] RequestRunRecordError),
    #[error("invalid archived Document")]
    InvalidDocument(#[source] DocumentError),
    #[error("invalid EvaluationRunRecord")]
    InvalidEvaluationRun(#[source] EvaluationRunError),
    #[error("invalid LocatorRunRecord")]
    InvalidLocatorRun(#[source] LocatorRunRecordError),
    #[error("invalid ContractRunRecord")]
    InvalidContractRun(#[source] ContractRunRecordError),
    #[error("archived Document exceeds {maximum} bytes: observed {observed}")]
    DocumentTooLarge { maximum: u64, observed: u64 },
    #[error("archived Document {key} payload does not exist")]
    DocumentPayloadMissing { key: String },
    #[error(
        "archived Document {key} payload has the wrong length: expected {expected}, observed {observed}"
    )]
    DocumentPayloadLengthMismatch {
        key: String,
        expected: u64,
        observed: u64,
    },
    #[error("archived Document {key} payload has the wrong SHA-256 digest")]
    DocumentPayloadDigestMismatch { key: String },
    #[error("immutable archived Document {key} already contains other bytes")]
    DocumentPayloadConflict { key: String },
    #[error("archived Document {key} payload may be committed but durability confirmation failed")]
    DocumentPayloadCommitUncertain {
        key: String,
        #[source]
        source: io::Error,
    },
    #[error("EvaluationRun source artifact {artifact:?} has no retained payload in its Capture")]
    EvaluationSourcePayloadUnavailable { artifact: WebArtifactRef },
    #[error("invalid Web Capture wire value")]
    InvalidWebCapture(#[source] WebCaptureWireError),
    #[error("invalid CaptureBundle payload association")]
    InvalidCaptureBundle(#[source] CaptureBundleError),
    #[error("failed to package canonical Web Capture JSON")]
    CaptureRecordJson(#[source] serde_json::Error),
    #[error("Capture record identity {found} does not match reference {expected}")]
    CaptureIdentityMismatch {
        expected: CaptureId,
        found: CaptureId,
    },
    #[error("Capture contains too many retained payloads: maximum {maximum}, observed {observed}")]
    CapturePayloadCountExceeded { maximum: u64, observed: u64 },
    #[error(
        "Capture payload materialization exceeds {maximum} bytes: observed at least {observed}"
    )]
    CaptureMaterializationTooLarge { maximum: u64, observed: u64 },
    #[error("Capture {capture_id} payload {artifact_id} does not exist")]
    CapturePayloadMissing {
        capture_id: CaptureId,
        artifact_id: ArtifactId,
    },
    #[error(
        "Capture payload {artifact:?} has the wrong length: expected {expected}, observed {observed}"
    )]
    CapturePayloadLengthMismatch {
        artifact: WebArtifactRef,
        expected: u64,
        observed: u64,
    },
    #[error("Capture payload {artifact:?} has the wrong SHA-256 digest")]
    CapturePayloadDigestMismatch { artifact: WebArtifactRef },
    #[error("immutable Capture {capture_id} payload {artifact_id} already contains other bytes")]
    CapturePayloadConflict {
        capture_id: CaptureId,
        artifact_id: ArtifactId,
    },
    #[error(
        "Capture {capture_id} payload {artifact_id} may be committed but durability confirmation failed"
    )]
    CapturePayloadCommitUncertain {
        capture_id: CaptureId,
        artifact_id: ArtifactId,
        #[source]
        source: io::Error,
    },
    #[error("failed to encode Archive {kind} record")]
    EncodeRecord {
        kind: &'static str,
        #[source]
        source: serde_json::Error,
    },
    #[error("malformed Archive envelope")]
    MalformedEnvelope(#[source] serde_json::Error),
    #[error("invalid Archive {kind} record value")]
    InvalidRecordValue {
        kind: &'static str,
        #[source]
        source: serde_json::Error,
    },
    #[error("invalid internal Archive layout: {reason}")]
    InvalidLayout { reason: &'static str },
    #[error("Archive format {found} is unsupported; this build supports {supported}")]
    UnsupportedFormat { found: u32, supported: u32 },
    #[error(
        "{kind} schema {found_schema} written by {writer_package} {writer_version} requires migration to schema {supported_schema}"
    )]
    MigrationRequired {
        kind: &'static str,
        found_schema: u32,
        supported_schema: u32,
        writer_package: String,
        writer_version: String,
    },
    #[error("Archive record kind {found} cannot be read as {expected}")]
    WrongRecordKind {
        found: String,
        expected: &'static str,
    },
    #[error("Archive record key {found} cannot be read as {expected}")]
    WrongRecordKey { found: String, expected: String },
    #[error("immutable Archive {kind} identity {key} already contains another value")]
    IdentityConflict { kind: &'static str, key: String },
    #[error("Archive {kind} record {key} may be committed but durability confirmation failed")]
    CommitUncertain {
        kind: &'static str,
        key: String,
        #[source]
        source: io::Error,
    },
}

impl ArchiveError {
    pub(in crate::internal::archive) fn io(
        operation: &'static str,
        path: impl Into<PathBuf>,
        source: io::Error,
    ) -> Self {
        Self::Io {
            operation,
            path: path.into(),
            source,
        }
    }
}
