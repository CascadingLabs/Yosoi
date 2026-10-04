use serde::{Deserialize, Serialize};
use yosoi_policy::policy::DocumentRequest;
use yosoi_types::CaptureOffset;
use yosoi_web_capture::{
    BrowserDocumentScope, DecodingErrorCode, UnknownReason, WebArtifactFamily, WebArtifactRef,
};

use crate::ArchivedDocumentInput;

/// Browser frame and capture offset retained beside one requested document.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RequestBrowserDocumentObservation {
    scope: BrowserDocumentScope,
    captured_at: CaptureOffset,
}

impl RequestBrowserDocumentObservation {
    pub const fn new(scope: BrowserDocumentScope, captured_at: CaptureOffset) -> Self {
        Self { scope, captured_at }
    }

    pub const fn scope(self) -> BrowserDocumentScope {
        self.scope
    }

    pub const fn captured_at(self) -> CaptureOffset {
        self.captured_at
    }
}

/// Bounded reason a requested document is incomplete.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestDocumentPartialReason {
    SourceFamilyPartial,
    SourceArtifactTruncated,
    ClassificationFromRetainedPrefix,
    DecodedOutputTruncated,
    IncompleteTerminalSequence,
    DecodedSourceFamilyPartial,
    RenderedDomFamilyPartial,
    AccessibilityTreeFamilyPartial,
    AccessibilityDepthLimited,
    AccessibilityNodeLoss,
    AccessibilityNodeLossUnknown,
    AccessibilityByteLoss,
    AccessibilityByteLossUnknown,
    BrowserArtifactTruncated { family: WebArtifactFamily },
}

/// Bounded reason required capture evidence is unavailable.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestDocumentUnavailableReason {
    SourceArtifactUnavailable,
    DecodedSourceNotRetained,
    DecodedSourcePayloadUnavailable,
    BrowserDecodedSourceNotRetained,
    CaptureArtifactNotRetained { family: WebArtifactFamily },
    CaptureArtifactPayloadUnavailable { family: WebArtifactFamily },
    CaptureArtifactFailed { family: WebArtifactFamily },
    CaptureArtifactUnavailable { family: WebArtifactFamily },
}

/// Bounded reason captured evidence cannot become a supported Document.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestDocumentUnprojectableReason {
    SourceFactsUnavailable,
    UnknownSourceFormat { reason: UnknownReason },
    UnsupportedSourceFormat,
    AmbiguousSourceFormat,
    DecodedSourceReferenceMismatch,
    UnsupportedEncoding { code: DecodingErrorCode },
    Undecodable { code: DecodingErrorCode },
    DecodingNotApplicable { code: DecodingErrorCode },
    DocumentRejected,
    NetworkTreeSchemaUnavailable,
    BrowserDocumentEpochUnavailable,
    BrowserDocumentNormalizationFailed,
    CaptureArtifactNotRequested { family: WebArtifactFamily },
    CaptureArtifactUnsupported { family: WebArtifactFamily },
}

/// Durable projection result for one requested document.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum RequestDocumentOutcome {
    Produced {
        document: ArchivedDocumentInput,
    },
    Partial {
        document: Option<ArchivedDocumentInput>,
        artifact: Option<WebArtifactRef>,
        reasons: Vec<RequestDocumentPartialReason>,
    },
    Unavailable {
        reason: RequestDocumentUnavailableReason,
    },
    Unprojectable {
        reason: RequestDocumentUnprojectableReason,
    },
}

impl RequestDocumentOutcome {
    pub(crate) fn artifact_references(&self) -> [Option<WebArtifactRef>; 2] {
        match self {
            Self::Produced { document } => [document.source_artifact(), None],
            Self::Partial {
                document, artifact, ..
            } => [
                document
                    .as_ref()
                    .and_then(ArchivedDocumentInput::source_artifact),
                *artifact,
            ],
            Self::Unavailable { .. } | Self::Unprojectable { .. } => [None, None],
        }
    }
}

/// One requested document and its exact durable projection outcome.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RequestDocumentRecord {
    requested: DocumentRequest,
    outcome: RequestDocumentOutcome,
    browser_observation: Option<RequestBrowserDocumentObservation>,
}

impl RequestDocumentRecord {
    pub const fn new(
        requested: DocumentRequest,
        outcome: RequestDocumentOutcome,
        browser_observation: Option<RequestBrowserDocumentObservation>,
    ) -> Self {
        Self {
            requested,
            outcome,
            browser_observation,
        }
    }

    pub const fn requested(&self) -> DocumentRequest {
        self.requested
    }

    pub const fn outcome(&self) -> &RequestDocumentOutcome {
        &self.outcome
    }

    pub const fn browser_observation(&self) -> Option<RequestBrowserDocumentObservation> {
        self.browser_observation
    }
}
