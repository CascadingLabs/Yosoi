use thiserror::Error;
use yosoi_documents::DocumentClass;
use yosoi_policy::policy::{AcquisitionKind, DocumentRequest, DocumentSelectionKind};
use yosoi_types::{ActivityId, CaptureId, Sha256Digest};
use yosoi_web_capture::{WebArtifactFamily, WebArtifactRef};

/// Failures while constructing or decoding one durable request run.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum RequestRunRecordError {
    #[error("effective Policy identity version must be greater than zero")]
    ZeroEffectivePolicyIdentityVersion,
    #[error(
        "archived Policy effective identity v{expected_version}:{expected_digest} does not match request-run identity v{found_version}:{found_digest}"
    )]
    EffectivePolicyIdentityMismatch {
        expected_version: u16,
        expected_digest: Sha256Digest,
        found_version: u16,
        found_digest: Sha256Digest,
    },
    #[error("request run contains {observed} attempts; maximum is {maximum}")]
    TooManyAttempts { maximum: usize, observed: usize },
    #[error("request run has {observed} attempts; archived Policy requires {expected}")]
    PolicyAttemptCountMismatch { expected: usize, observed: usize },
    #[error("request attempt {position} uses {found:?}; archived Policy requires {expected:?}")]
    PolicyAcquisitionMismatch {
        position: usize,
        expected: AcquisitionKind,
        found: AcquisitionKind,
    },
    #[error(
        "request attempt {position} records {found:?} document authorship; archived Policy requires {expected:?}"
    )]
    PolicyAuthorshipMismatch {
        position: usize,
        expected: DocumentSelectionKind,
        found: DocumentSelectionKind,
    },
    #[error("request attempt {position} documents differ from the archived effective Policy")]
    PolicyDocumentsMismatch { position: usize },
    #[error("completed request run contains cancelled NotStarted attempt {position}")]
    CompletedRunContainsNotStarted { position: usize },
    #[error("completed request run contains cancellation failure at attempt {position}")]
    CompletedRunContainsCancellationFailure { position: usize },
    #[error("request run repeats capture identity {capture_id}")]
    DuplicateCaptureId { capture_id: CaptureId },
    #[error("completed request attempt is missing its committed Capture reference")]
    CompletedCaptureMissing,
    #[error("completed {requested:?} outcome is missing its archived Document reference")]
    CompletedDocumentReferenceMissing { requested: DocumentRequest },
    #[error("archived {requested:?} Document is missing its source artifact provenance")]
    DocumentSourceArtifactMissing { requested: DocumentRequest },
    #[error(
        "{reference_kind} reference uses Archive format {found}; request run requires format {expected}"
    )]
    ReferenceFormatMismatch {
        reference_kind: &'static str,
        found: u32,
        expected: u32,
    },
    #[error("attempt capture {attempt} references archived capture {archived}")]
    CaptureReferenceMismatch {
        attempt: CaptureId,
        archived: CaptureId,
    },
    #[error("completed attempt has {observed} document outcomes; expected {expected}")]
    DocumentOutcomeCountMismatch { expected: usize, observed: usize },
    #[error(
        "document outcome {position} records {recorded:?}; expected requested document {expected:?}"
    )]
    DocumentOutcomeOrderMismatch {
        position: usize,
        expected: DocumentRequest,
        recorded: DocumentRequest,
    },
    #[error("partial {requested:?} outcome retained a Document without its artifact reference")]
    PartialDocumentArtifactMissing { requested: DocumentRequest },
    #[error("partial {requested:?} outcome has a non-canonical Document/artifact shape")]
    NonCanonicalPartialDocument { requested: DocumentRequest },
    #[error("partial {requested:?} outcome must retain at least one incompleteness reason")]
    PartialDocumentReasonsEmpty { requested: DocumentRequest },
    #[error(
        "{requested:?} artifact belongs to activity {artifact_activity}, not capture {capture_id}"
    )]
    DocumentArtifactOwnershipMismatch {
        requested: DocumentRequest,
        artifact_activity: ActivityId,
        capture_id: CaptureId,
    },
    #[error("{requested:?} source artifact {artifact:?} has no retained Capture payload")]
    DocumentSourcePayloadUnavailable {
        requested: DocumentRequest,
        artifact: WebArtifactRef,
    },
    #[error("{requested:?} requires {expected:?} provenance, found {found:?} artifact family")]
    DocumentArtifactFamilyMismatch {
        requested: DocumentRequest,
        expected: WebArtifactFamily,
        found: WebArtifactFamily,
    },
    #[error("{requested:?} archived Document epoch differs from its source artifact scope")]
    DocumentEpochMismatch { requested: DocumentRequest },
    #[error("{requested:?} cannot reference archived Document class {actual:?}")]
    DocumentClassMismatch {
        requested: DocumentRequest,
        actual: DocumentClass,
    },
}
