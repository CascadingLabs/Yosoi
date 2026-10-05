use thiserror::Error;
use yosoi_policy::policy::DocumentRequest;
/// Bounded reasons a projected document is incomplete.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
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
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
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
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
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
