use std::fmt;

use thiserror::Error;
use yosoi_policy::policy::{DocumentRequest, DocumentSelectionKind};
use yosoi_types::CaptureId;
use yosoi_web_capture::{WebArtifactRef, WebCapture};
use yosoi_web_capture_direct_http::DirectHttpResponseFacts;

use crate::{AppliedPolicy, Document, EffectivePolicyIdentity, PolicySnapshot};

/// A capture associated with the exact prepared attempt that produced it.
pub struct ProjectedAttempt {
    capture_id: CaptureId,
    applied_policy: AppliedPolicy,
    policy_snapshot: PolicySnapshot,
    authored_selection: DocumentSelectionKind,
    capture: WebCapture,
    transport: ProjectedAttemptTransport,
    documents: Vec<DocumentOutcome>,
    raw_response: Option<Vec<u8>>,
}

/// Acquisition-specific facts retained by a projected attempt.
pub enum ProjectedAttemptTransport {
    /// Bounded response facts from a Direct HTTP capture.
    DirectHttp(Box<DirectHttpResponseFacts>),
    /// Browser cleanup state observed before finalization consumed the result.
    Browser {
        cleanup: yosoi_web_capture::CleanupState,
        status: Option<u16>,
    },
}

impl ProjectedAttempt {
    pub(super) const fn new(
        capture_id: CaptureId,
        applied_policy: AppliedPolicy,
        policy_snapshot: PolicySnapshot,
        authored_selection: DocumentSelectionKind,
        capture: WebCapture,
        transport: ProjectedAttemptTransport,
        documents: Vec<DocumentOutcome>,
    ) -> Self {
        Self {
            capture_id,
            applied_policy,
            policy_snapshot,
            authored_selection,
            capture,
            transport,
            documents,
            raw_response: None,
        }
    }

    pub(super) fn with_raw_response(mut self, raw_response: Option<Vec<u8>>) -> Self {
        self.raw_response = raw_response;
        self
    }

    pub(crate) const fn take_raw_response(&mut self) -> Option<Vec<u8>> {
        self.raw_response.take()
    }

    /// Returns the capture identity allocated during request preparation.
    pub const fn capture_id(&self) -> CaptureId {
        self.capture_id
    }

    /// Returns the effective policy identity attached to the capture.
    pub const fn policy_identity(&self) -> EffectivePolicyIdentity {
        self.applied_policy.identity()
    }

    /// Returns the complete content-free policy application record.
    pub const fn applied_policy(&self) -> &AppliedPolicy {
        &self.applied_policy
    }

    /// Returns the full validated policy used to prepare the request.
    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        &self.policy_snapshot
    }

    /// Returns whether the prepared acquisition used Current or Exact documents.
    pub const fn authored_selection(&self) -> DocumentSelectionKind {
        self.authored_selection
    }

    /// Returns finalized capture metadata without retained payloads.
    pub const fn capture(&self) -> &WebCapture {
        &self.capture
    }

    /// Returns the acquisition-specific response or cleanup facts.
    pub const fn transport(&self) -> &ProjectedAttemptTransport {
        &self.transport
    }

    /// Returns bounded Direct HTTP response facts when this was a Direct HTTP attempt.
    pub fn response(&self) -> Option<&DirectHttpResponseFacts> {
        match &self.transport {
            ProjectedAttemptTransport::DirectHttp(response) => Some(response.as_ref()),
            ProjectedAttemptTransport::Browser { .. } => None,
        }
    }

    /// Returns the observed browser cleanup state when this was a browser attempt.
    pub const fn browser_cleanup(&self) -> Option<yosoi_web_capture::CleanupState> {
        match &self.transport {
            ProjectedAttemptTransport::DirectHttp(_) => None,
            ProjectedAttemptTransport::Browser { cleanup, .. } => Some(*cleanup),
        }
    }

    /// Returns the browser-observed main-document status, when available.
    pub const fn browser_status(&self) -> Option<u16> {
        match &self.transport {
            ProjectedAttemptTransport::DirectHttp(_) => None,
            ProjectedAttemptTransport::Browser { status, .. } => *status,
        }
    }

    /// Returns outcomes for explicitly requested and supported documents.
    pub fn documents(&self) -> &[DocumentOutcome] {
        &self.documents
    }

    /// Separates the preserved attempt metadata from its projected documents.
    pub fn into_parts(
        self,
    ) -> (
        CaptureId,
        AppliedPolicy,
        PolicySnapshot,
        DocumentSelectionKind,
        WebCapture,
        ProjectedAttemptTransport,
        Vec<DocumentOutcome>,
    ) {
        (
            self.capture_id,
            self.applied_policy,
            self.policy_snapshot,
            self.authored_selection,
            self.capture,
            self.transport,
            self.documents,
        )
    }
}

impl fmt::Debug for ProjectedAttempt {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProjectedAttempt")
            .field("raw_response", &self.raw_response.as_ref().map(Vec::len))
            .field("capture_id", &self.capture_id)
            .field("policy_identity", &self.applied_policy.identity())
            .field("policy_snapshot", &"<redacted>")
            .field("authored_selection", &self.authored_selection)
            .field("capture", &"<redacted>")
            .field("transport", &"<redacted>")
            .field("documents", &self.documents)
            .finish()
    }
}

impl fmt::Debug for ProjectedAttemptTransport {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DirectHttp(_) => formatter
                .debug_tuple("ProjectedAttemptTransport::DirectHttp")
                .field(&"<redacted>")
                .finish(),
            Self::Browser { cleanup, status } => formatter
                .debug_struct("ProjectedAttemptTransport::Browser")
                .field("cleanup", cleanup)
                .field("status", status)
                .finish(),
        }
    }
}

/// One result for an explicitly requested response document.
pub enum DocumentOutcome {
    /// A complete normalized payload was moved into a locator document.
    Produced {
        /// The owned document available to the locator facade.
        document: Document,
        /// Exact retained capture artifact used as the document payload.
        artifact: WebArtifactRef,
    },
    /// Capture evidence was incomplete; a safe normalized document may still be available.
    Partial {
        /// A validated partial document, when the normalizer can safely represent it.
        document: Option<Document>,
        /// Exact capture artifact used to produce the document or partial evidence.
        artifact: Option<WebArtifactRef>,
        /// Bounded reasons the document could not be treated as complete.
        reasons: Vec<PartialReason>,
    },
    /// Capture did not retain a required artifact or decoded view.
    Unavailable { reason: UnavailableReason },
    /// Capture facts cannot be represented by the supported locator document profiles.
    Unprojectable { reason: UnprojectableReason },
}

impl DocumentOutcome {
    /// Borrows a validated document when projection could safely materialize one.
    pub const fn document(&self) -> Option<&Document> {
        match self {
            Self::Produced { document, .. } => Some(document),
            Self::Partial { document, .. } => document.as_ref(),
            Self::Unavailable { .. } | Self::Unprojectable { .. } => None,
        }
    }

    /// Returns the exact capture artifact used for a produced or partial document.
    pub const fn artifact(&self) -> Option<WebArtifactRef> {
        match self {
            Self::Produced { artifact, .. } => Some(*artifact),
            Self::Partial { artifact, .. } => *artifact,
            Self::Unavailable { .. } | Self::Unprojectable { .. } => None,
        }
    }

    /// Returns bounded completeness reasons, or an empty slice for other outcomes.
    pub fn partial_reasons(&self) -> &[PartialReason] {
        match self {
            Self::Partial { reasons, .. } => reasons,
            Self::Produced { .. } | Self::Unavailable { .. } | Self::Unprojectable { .. } => &[],
        }
    }

    /// Consumes the outcome and returns any safely normalized Document.
    ///
    /// Partial source or truncated DOM evidence has no Document. Accessibility
    /// evidence can carry a validated partial Document whose internal
    /// completeness prevents a false complete no-match claim.
    pub fn into_document(self) -> Option<Document> {
        match self {
            Self::Produced { document, .. } => Some(document),
            Self::Partial { document, .. } => document,
            Self::Unavailable { .. } | Self::Unprojectable { .. } => None,
        }
    }
}

impl fmt::Debug for DocumentOutcome {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Produced { document, artifact } => formatter
                .debug_struct("DocumentOutcome::Produced")
                .field("document_id", document.id())
                .field("class", &document.class())
                .field("byte_len", &document.byte_len())
                .field("artifact", artifact)
                .field("bytes", &"<redacted>")
                .finish(),
            Self::Partial {
                document,
                artifact,
                reasons,
            } => formatter
                .debug_struct("DocumentOutcome::Partial")
                .field("document", document)
                .field("artifact", artifact)
                .field("reasons", reasons)
                .finish(),
            Self::Unavailable { reason } => formatter
                .debug_tuple("DocumentOutcome::Unavailable")
                .field(reason)
                .finish(),
            Self::Unprojectable { reason } => formatter
                .debug_tuple("DocumentOutcome::Unprojectable")
                .field(reason)
                .finish(),
        }
    }
}

/// Bounded reasons a projected document is incomplete.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PartialReason {
    /// The capture reports a partial source artifact family.
    SourceFamilyPartial,
    /// The retained source artifact contains fewer than its complete bytes.
    SourceArtifactTruncated,
    /// Classification used only a retained prefix of the source.
    ClassificationFromRetainedPrefix,
    /// The UTF-8 decoded-source output reached its configured limit.
    DecodedOutputTruncated,
    /// Decoding ended in an incomplete terminal sequence.
    IncompleteTerminalSequence,
    /// The decoded-source artifact family is recorded as partial.
    DecodedSourceFamilyPartial,
    /// The browser capture reports a partial rendered-DOM artifact family.
    RenderedDomFamilyPartial,
    /// The browser capture reports a partial accessibility-tree artifact family.
    AccessibilityTreeFamilyPartial,
    /// The browser accessibility snapshot was intentionally depth-limited.
    AccessibilityDepthLimited,
    /// Some observed accessibility nodes were not retained.
    AccessibilityNodeLoss,
    /// The amount of lost accessibility nodes is unknown.
    AccessibilityNodeLossUnknown,
    /// Some observed accessibility bytes were not retained.
    AccessibilityByteLoss,
    /// The amount of lost accessibility bytes is unknown.
    AccessibilityByteLossUnknown,
    /// The retained browser artifact itself is truncated and was not normalized.
    BrowserArtifactTruncated {
        family: yosoi_web_capture::WebArtifactFamily,
    },
}

/// Bounded reasons required capture payloads are unavailable.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnavailableReason {
    /// No usable source artifact was retained in the capture bundle.
    SourceArtifactUnavailable,
    /// The policy did not retain the decoded UTF-8 artifact.
    DecodedSourceNotRetained,
    /// The finalized capture has no bytes for its decoded-source reference.
    DecodedSourcePayloadUnavailable,
    /// The browser response source has no retained decoded view in this capture.
    BrowserDecodedSourceNotRetained,
    /// The requested browser artifact was intentionally not retained.
    CaptureArtifactNotRetained {
        family: yosoi_web_capture::WebArtifactFamily,
    },
    /// The requested browser artifact payload is absent from the consumed bundle.
    CaptureArtifactPayloadUnavailable {
        family: yosoi_web_capture::WebArtifactFamily,
    },
    /// The requested browser artifact capture failed.
    CaptureArtifactFailed {
        family: yosoi_web_capture::WebArtifactFamily,
    },
    /// The requested browser artifact was unavailable from the provider.
    CaptureArtifactUnavailable {
        family: yosoi_web_capture::WebArtifactFamily,
    },
}

/// Bounded reasons the captured representation cannot be made into a Document.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnprojectableReason {
    /// Direct HTTP did not provide source representation facts.
    SourceFactsUnavailable,
    /// The source classifier returned an unknown format.
    UnknownSourceFormat {
        /// Bounded explanation returned by the classifier.
        reason: yosoi_web_capture::UnknownReason,
    },
    /// The source classifier returned an unsupported format.
    UnsupportedSourceFormat,
    /// The source classifier returned multiple possible formats.
    AmbiguousSourceFormat,
    /// The classifier and decoded view refer to different source artifacts.
    DecodedSourceReferenceMismatch,
    /// The source format was classified, but decoding was not supported.
    UnsupportedEncoding {
        /// Closed decoding failure category.
        code: yosoi_web_capture::DecodingErrorCode,
    },
    /// The source format was classified, but decoding failed.
    Undecodable {
        /// Closed decoding failure category.
        code: yosoi_web_capture::DecodingErrorCode,
    },
    /// No decoded view applies to this classification.
    DecodingNotApplicable {
        /// Closed decoding failure category.
        code: yosoi_web_capture::DecodingErrorCode,
    },
    /// The validated document constructor rejected the derived document input.
    DocumentRejected,
    /// No locator document schema is defined for the requested network tree.
    NetworkTreeSchemaUnavailable,
    /// Capture metadata did not provide a browser document epoch for the requested snapshot.
    BrowserDocumentEpochUnavailable,
    /// The retained browser artifact could not be normalized into its locator document schema.
    BrowserDocumentNormalizationFailed,
    /// The finalized capture omitted an artifact family that the prepared attempt requested.
    CaptureArtifactNotRequested {
        family: yosoi_web_capture::WebArtifactFamily,
    },
    /// The provider marked an artifact family unsupported.
    CaptureArtifactUnsupported {
        family: yosoi_web_capture::WebArtifactFamily,
    },
}

/// Structural misuse while associating a capture with a prepared attempt.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ProjectionError {
    /// The attempt does not belong to the supplied prepared request.
    #[error("prepared attempt does not belong to the supplied request")]
    ForeignAttempt,
    /// The capture was resolved with a different effective policy identity.
    #[error("capture policy identity does not match the prepared request")]
    PolicyIdentityMismatch,
    /// The capture identity differs from the prepared attempt identity.
    #[error("capture identity does not match the prepared attempt")]
    CaptureIdMismatch,
    /// Capture outcome kind does not match the prepared attempt acquisition.
    #[error("capture outcome kind does not match the prepared attempt")]
    CaptureOutcomeMismatch,
    /// This Direct HTTP projection does not support the requested document family.
    #[error("document request {document:?} cannot be projected from Direct HTTP")]
    UnsupportedDocumentRequest {
        /// Public document request outside this projection's scope.
        document: DocumentRequest,
    },
    /// A required browser artifact family did not contain exactly one artifact.
    #[error("requested {family:?} artifact family did not contain exactly one artifact")]
    ArtifactCountMismatch {
        /// Capture family associated with the requested document.
        family: yosoi_web_capture::WebArtifactFamily,
    },
    /// The prepared document policy could not be represented as a normalization budget.
    #[error("prepared document policy could not be represented as a resource budget")]
    InvalidResourceBudget,
}
