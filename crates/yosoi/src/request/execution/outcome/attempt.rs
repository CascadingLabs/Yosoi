mod classification;

use std::fmt;

use yosoi_policy::policy::{AcquisitionKind, DocumentRequest, DocumentSelectionKind};
use yosoi_types::CaptureId;
use yosoi_web_capture::CleanupState;

use crate::{
    AppliedPolicy, CaptureArchiveRef, DocumentArchiveRef, DocumentOutcome, PolicySnapshot,
};

use super::capture_facts::{AttemptCaptureFacts, BrowserDocumentObservation};
use super::failure::{AttemptFailure, NotStartedAttempt};

/// One outcome for an authored acquisition, in policy order.
pub enum AttemptOutcome {
    /// The existing capture adapter completed and document projection ran.
    Completed(AttemptResult),
    /// Resolution, capture, or projection failed for this authored acquisition.
    Failed(AttemptFailure),
    /// Cancellation prevented this authored acquisition from starting.
    NotStarted(NotStartedAttempt),
}

/// Completed capture metadata, transport status, policy, and ordered documents.
pub struct AttemptResult {
    capture_id: CaptureId,
    capture_archive_ref: Option<CaptureArchiveRef>,
    acquisition: AcquisitionKind,
    authored_selection: DocumentSelectionKind,
    requested_target: String,
    policy_snapshot: PolicySnapshot,
    applied_policy: AppliedPolicy,
    capture_facts: AttemptCaptureFacts,
    transport: AttemptTransportOutcome,
    response_facts: Option<Box<yosoi_web_capture_direct_http::DirectHttpResponseFacts>>,
    raw_response: Option<Vec<u8>>,
    documents: Vec<AttemptDocumentOutcome>,
}

impl AttemptResult {
    pub const fn capture_id(&self) -> CaptureId {
        self.capture_id
    }
    /// Returns the committed Capture reference only for explicit archived sends.
    pub const fn capture_archive_ref(&self) -> Option<&CaptureArchiveRef> {
        self.capture_archive_ref.as_ref()
    }
    pub const fn acquisition(&self) -> AcquisitionKind {
        self.acquisition
    }
    pub const fn authored_selection(&self) -> DocumentSelectionKind {
        self.authored_selection
    }
    pub fn requested_target(&self) -> &str {
        &self.requested_target
    }
    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        &self.policy_snapshot
    }
    pub const fn applied_policy(&self) -> &AppliedPolicy {
        &self.applied_policy
    }
    pub const fn capture_facts(&self) -> &AttemptCaptureFacts {
        &self.capture_facts
    }
    pub const fn transport(&self) -> &AttemptTransportOutcome {
        &self.transport
    }
    /// Bounded HTTP response facts retained for explicit redirect orchestration.
    pub fn response_facts(
        &self,
    ) -> Option<&yosoi_web_capture_direct_http::DirectHttpResponseFacts> {
        self.response_facts.as_deref()
    }
    pub(crate) fn raw_response(&self) -> Option<&[u8]> {
        self.raw_response.as_deref()
    }

    pub fn documents(&self) -> &[AttemptDocumentOutcome] {
        &self.documents
    }
}

impl fmt::Debug for AttemptResult {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AttemptResult")
            .field("capture_id", &self.capture_id)
            .field(
                "has_capture_archive_ref",
                &self.capture_archive_ref.is_some(),
            )
            .field("acquisition", &self.acquisition)
            .field("authored_selection", &self.authored_selection)
            .field("requested_target", &"[redacted]")
            .field("transport", &self.transport)
            .field("documents", &self.documents)
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AttemptTransportOutcome {
    /// A response head was received; non-success HTTP statuses remain responses.
    DirectHttp { status: u16 },
    Browser {
        cleanup: CleanupState,
        status: Option<u16>,
    },
}

impl AttemptTransportOutcome {
    pub const fn status(self) -> Option<u16> {
        match self {
            Self::DirectHttp { status } => Some(status),
            Self::Browser { status, .. } => status,
        }
    }
}

/// One requested document and its capture-time browser provenance.
pub struct AttemptDocumentOutcome {
    requested: DocumentRequest,
    outcome: DocumentOutcome,
    browser_observation: Option<BrowserDocumentObservation>,
    document_archive_ref: Option<DocumentArchiveRef>,
}

impl AttemptDocumentOutcome {
    pub const fn requested(&self) -> DocumentRequest {
        self.requested
    }
    pub const fn outcome(&self) -> &DocumentOutcome {
        &self.outcome
    }
    pub const fn browser_observation(&self) -> Option<BrowserDocumentObservation> {
        self.browser_observation
    }
    /// Returns the exact normalized Document persisted by an archived send.
    pub const fn document_archive_ref(&self) -> Option<&DocumentArchiveRef> {
        self.document_archive_ref.as_ref()
    }
}

impl fmt::Debug for AttemptDocumentOutcome {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AttemptDocumentOutcome")
            .field("requested", &self.requested)
            .field("outcome", &self.outcome)
            .field("browser_observation", &self.browser_observation)
            .field(
                "has_document_archive_ref",
                &self.document_archive_ref.is_some(),
            )
            .finish()
    }
}
