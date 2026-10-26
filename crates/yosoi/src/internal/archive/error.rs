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
    /// A portable Surface outcome failed its schema, integrity or resource checks.
    #[error("invalid Surface outcome: {0}")]
    InvalidSurfaceOutcome(String),
    #[error("local Archive format 1 is not certified on platform {platform}")]
    /// Local Archive format 1 is not certified on platform `platform`.
    UnsupportedPlatform {
        /// Operating system on which certification is unavailable.
        platform: &'static str,
    },
    #[error("an Archive root path cannot be empty")]
    /// An Archive root path cannot be empty.
    EmptyRoot,
    #[error(transparent)]
    /// The reference fails its typed parsing contract.
    InvalidReference(#[from] ArchiveRefError),
    #[error("Archive {operation} failed at {path}")]
    /// Archive `operation` failed at `path`.
    Io {
        /// Filesystem operation that failed.
        operation: &'static str,
        /// Owned path involved in the failure.
        path: PathBuf,
        #[source]
        /// Underlying failure retained for diagnosis.
        source: io::Error,
    },
    #[error("Archive filesystem task failed during {operation}")]
    /// Archive filesystem task failed during `operation`.
    FilesystemTask {
        /// Filesystem operation that failed.
        operation: &'static str,
        #[source]
        /// Underlying failure retained for diagnosis.
        source: JoinError,
    },
    #[error("Archive-owned path {path} is unsafe: {reason}")]
    /// Archive-owned path `path` is unsafe: `reason`.
    UnsafeArchivePath {
        /// Owned path involved in the failure.
        path: PathBuf,
        /// Specific violated safety or layout condition.
        reason: &'static str,
    },
    #[error("Archive-owned path {path} has insecure permissions {mode:#o}")]
    /// Archive-owned path `path` has insecure permissions `mode:#o`.
    InsecurePermissions {
        /// Owned path involved in the failure.
        path: PathBuf,
        /// Observed filesystem permission bits.
        mode: u32,
    },
    #[error("Archive {kind} record {key} does not exist")]
    /// Archive `kind` record `key` does not exist.
    RecordNotFound {
        /// Record category involved in this operation.
        kind: &'static str,
        /// Exact immutable record key.
        key: String,
    },
    #[error("Archive record at {path} is not a regular file")]
    /// Archive record at `path` is not a regular file.
    NotRegularFile {
        /// Owned path involved in the failure.
        path: PathBuf,
    },
    #[error("Archive record is too large: maximum {maximum} bytes, observed {observed}")]
    /// Archive record is too large: maximum `maximum` bytes, observed `observed`.
    RecordTooLarge {
        /// Largest supported count or byte length.
        maximum: u64,
        /// Actual count or byte length encountered.
        observed: u64,
    },
    #[error("invalid Policy value")]
    /// Invalid Policy value.
    InvalidPolicy(#[source] PolicyError),
    #[error("invalid request run record")]
    /// Invalid request run record.
    InvalidRequestRun(#[source] RequestRunRecordError),
    #[error("invalid archived Document")]
    /// Invalid archived Document.
    InvalidDocument(#[source] DocumentError),
    #[error("invalid EvaluationRunRecord")]
    /// Invalid EvaluationRunRecord.
    InvalidEvaluationRun(#[source] EvaluationRunError),
    #[error("invalid LocatorRunRecord")]
    /// Invalid LocatorRunRecord.
    InvalidLocatorRun(#[source] LocatorRunRecordError),
    #[error("invalid ContractRunRecord")]
    /// Invalid ContractRunRecord.
    InvalidContractRun(#[source] ContractRunRecordError),
    #[error("archived Document exceeds {maximum} bytes: observed {observed}")]
    /// Archived Document exceeds `maximum` bytes: observed `observed`.
    DocumentTooLarge {
        /// Largest supported count or byte length.
        maximum: u64,
        /// Actual count or byte length encountered.
        observed: u64,
    },
    #[error("archived Document {key} payload does not exist")]
    /// Archived Document `key` payload does not exist.
    DocumentPayloadMissing {
        /// Exact immutable record key.
        key: String,
    },
    #[error(
        "archived Document {key} payload has the wrong length: expected {expected}, observed {observed}"
    )]
    /// Archived Document `key` payload has the wrong length: expected `expected`, observed `observed`.
    DocumentPayloadLengthMismatch {
        /// Exact immutable record key.
        key: String,
        /// Identity, category or length required by the reference.
        expected: u64,
        /// Actual count or byte length encountered.
        observed: u64,
    },
    #[error("archived Document {key} payload has the wrong SHA-256 digest")]
    /// Archived Document `key` payload has the wrong SHA-256 digest.
    DocumentPayloadDigestMismatch {
        /// Exact immutable record key.
        key: String,
    },
    #[error("immutable archived Document {key} already contains other bytes")]
    /// Immutable archived Document `key` already contains other bytes.
    DocumentPayloadConflict {
        /// Exact immutable record key.
        key: String,
    },
    #[error("archived Document {key} payload may be committed but durability confirmation failed")]
    /// Archived Document `key` payload may be committed but durability confirmation failed.
    DocumentPayloadCommitUncertain {
        /// Exact immutable record key.
        key: String,
        #[source]
        /// Underlying failure retained for diagnosis.
        source: io::Error,
    },
    #[error("EvaluationRun source artifact {artifact:?} has no retained payload in its Capture")]
    /// EvaluationRun source artifact `artifact:?` has no retained payload in its Capture.
    EvaluationSourcePayloadUnavailable {
        /// Exact captured artifact reference.
        artifact: WebArtifactRef,
    },
    #[error("invalid Web Capture wire value")]
    /// Invalid Web Capture wire value.
    InvalidWebCapture(#[source] WebCaptureWireError),
    #[error("invalid CaptureBundle payload association")]
    /// Invalid CaptureBundle payload association.
    InvalidCaptureBundle(#[source] CaptureBundleError),
    #[error("failed to package canonical Web Capture JSON")]
    /// Failed to package canonical Web Capture JSON.
    CaptureRecordJson(#[source] serde_json::Error),
    #[error("Capture record identity {found} does not match reference {expected}")]
    /// Capture record identity `found` does not match reference `expected`.
    CaptureIdentityMismatch {
        /// Identity, category or length required by the reference.
        expected: CaptureId,
        /// Identity, category or version stored in the rejected value.
        found: CaptureId,
    },
    #[error("Capture contains too many retained payloads: maximum {maximum}, observed {observed}")]
    /// Capture contains too many retained payloads: maximum `maximum`, observed `observed`.
    CapturePayloadCountExceeded {
        /// Largest supported count or byte length.
        maximum: u64,
        /// Actual count or byte length encountered.
        observed: u64,
    },
    #[error(
        "Capture payload materialization exceeds {maximum} bytes: observed at least {observed}"
    )]
    /// Capture payload materialization exceeds `maximum` bytes: observed at least `observed`.
    CaptureMaterializationTooLarge {
        /// Largest supported count or byte length.
        maximum: u64,
        /// Actual count or byte length encountered.
        observed: u64,
    },
    #[error("Capture {capture_id} payload {artifact_id} does not exist")]
    /// Capture `capture_id` payload `artifact_id` does not exist.
    CapturePayloadMissing {
        /// Capture occurrence whose payload was requested.
        capture_id: CaptureId,
        /// Artifact identity within the capture.
        artifact_id: ArtifactId,
    },
    #[error(
        "Capture payload {artifact:?} has the wrong length: expected {expected}, observed {observed}"
    )]
    /// Capture payload `artifact:?` has the wrong length: expected `expected`, observed `observed`.
    CapturePayloadLengthMismatch {
        /// Exact captured artifact reference.
        artifact: WebArtifactRef,
        /// Identity, category or length required by the reference.
        expected: u64,
        /// Actual count or byte length encountered.
        observed: u64,
    },
    #[error("Capture payload {artifact:?} has the wrong SHA-256 digest")]
    /// Capture payload `artifact:?` has the wrong SHA-256 digest.
    CapturePayloadDigestMismatch {
        /// Exact captured artifact reference.
        artifact: WebArtifactRef,
    },
    #[error("immutable Capture {capture_id} payload {artifact_id} already contains other bytes")]
    /// Immutable Capture `capture_id` payload `artifact_id` already contains other bytes.
    CapturePayloadConflict {
        /// Capture occurrence whose payload was requested.
        capture_id: CaptureId,
        /// Artifact identity within the capture.
        artifact_id: ArtifactId,
    },
    #[error(
        "Capture {capture_id} payload {artifact_id} may be committed but durability confirmation failed"
    )]
    /// Capture `capture_id` payload `artifact_id` may be committed but durability confirmation failed.
    CapturePayloadCommitUncertain {
        /// Capture occurrence whose payload was requested.
        capture_id: CaptureId,
        /// Artifact identity within the capture.
        artifact_id: ArtifactId,
        #[source]
        /// Underlying failure retained for diagnosis.
        source: io::Error,
    },
    #[error("failed to encode Archive {kind} record")]
    /// Failed to encode Archive `kind` record.
    EncodeRecord {
        /// Record category involved in this operation.
        kind: &'static str,
        #[source]
        /// Underlying failure retained for diagnosis.
        source: serde_json::Error,
    },
    #[error("malformed Archive envelope")]
    /// Malformed Archive envelope.
    MalformedEnvelope(#[source] serde_json::Error),
    #[error("invalid Archive {kind} record value")]
    /// Invalid Archive `kind` record value.
    InvalidRecordValue {
        /// Record category involved in this operation.
        kind: &'static str,
        #[source]
        /// Underlying failure retained for diagnosis.
        source: serde_json::Error,
    },
    #[error("invalid internal Archive layout: {reason}")]
    /// Invalid internal Archive layout: `reason`.
    InvalidLayout {
        /// Specific violated safety or layout condition.
        reason: &'static str,
    },
    #[error("Archive format {found} is unsupported; this build supports {supported}")]
    /// Archive format `found` is unsupported; this build supports `supported`.
    UnsupportedFormat {
        /// Identity, category or version stored in the rejected value.
        found: u32,
        /// Newest format version accepted by this build.
        supported: u32,
    },
    #[error(
        "{kind} schema {found_schema} written by {writer_package} {writer_version} requires migration to schema {supported_schema}"
    )]
    /// `kind` schema `found_schema` written by `writer_package` `writer_version` requires migration to schema `supported_schema`.
    MigrationRequired {
        /// Record category involved in this operation.
        kind: &'static str,
        /// Schema version stored in the record.
        found_schema: u32,
        /// Schema version accepted by this build.
        supported_schema: u32,
        /// Package that originally encoded the record.
        writer_package: String,
        /// Original writer package version.
        writer_version: String,
    },
    #[error("Archive record kind {found} cannot be read as {expected}")]
    /// Archive record kind `found` cannot be read as `expected`.
    WrongRecordKind {
        /// Identity, category or version stored in the rejected value.
        found: String,
        /// Identity, category or length required by the reference.
        expected: &'static str,
    },
    #[error("Archive record key {found} cannot be read as {expected}")]
    /// Archive record key `found` cannot be read as `expected`.
    WrongRecordKey {
        /// Identity, category or version stored in the rejected value.
        found: String,
        /// Identity, category or length required by the reference.
        expected: String,
    },
    #[error("immutable Archive {kind} identity {key} already contains another value")]
    /// Immutable Archive `kind` identity `key` already contains another value.
    IdentityConflict {
        /// Record category involved in this operation.
        kind: &'static str,
        /// Exact immutable record key.
        key: String,
    },
    #[error("Archive {kind} record {key} may be committed but durability confirmation failed")]
    /// Archive `kind` record `key` may be committed but durability confirmation failed.
    CommitUncertain {
        /// Record category involved in this operation.
        kind: &'static str,
        /// Exact immutable record key.
        key: String,
        #[source]
        /// Underlying failure retained for diagnosis.
        source: io::Error,
    },
}

impl ArchiveError {
    pub(crate) fn io(operation: &'static str, path: impl Into<PathBuf>, source: io::Error) -> Self {
        Self::Io {
            operation,
            path: path.into(),
            source,
        }
    }
}
