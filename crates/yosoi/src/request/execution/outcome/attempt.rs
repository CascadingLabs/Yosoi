use std::fmt;

use yosoi_policy::policy::{AcquisitionKind, DocumentRequest, DocumentSelectionKind};
use yosoi_types::CaptureId;
use yosoi_web_capture::{CleanupState, Observation, RedirectHop, ResolvedWebUrl};

use crate::{
    AppliedPolicy, CaptureArchiveRef, DocumentArchiveRef, DocumentOutcome, PolicyResolutionError,
    PolicySnapshot, PreparedAttempt, PreparedPageRequest, ProjectedAttempt,
    projection::ProjectedAttemptTransport,
};

use super::capture_facts::{
    AttemptCaptureFacts, AttemptCaptureFailureFacts, BrowserDocumentObservation,
    browser_document_observation,
};
use super::failure::{
    AttemptDiagnostic, AttemptFailure, AttemptFailureKind, NotStartedAttempt, NotStartedReason,
};

/// One outcome for an authored acquisition, in policy order.
pub enum AttemptOutcome {
    /// The existing capture adapter completed and document projection ran.
    Completed(AttemptResult),
    /// Resolution, capture, or projection failed for this authored acquisition.
    Failed(AttemptFailure),
    /// Cancellation prevented this authored acquisition from starting.
    NotStarted(NotStartedAttempt),
}

impl AttemptOutcome {
    pub(crate) fn completed(
        prepared: &PreparedPageRequest,
        attempt: &PreparedAttempt,
        mut projected: ProjectedAttempt,
        capture_archive_ref: Option<CaptureArchiveRef>,
        document_archive_refs: Option<&[Option<DocumentArchiveRef>]>,
    ) -> Self {
        let raw_response = projected.take_raw_response();
        let (
            capture_id,
            applied_policy,
            policy_snapshot,
            authored_selection,
            capture,
            transport,
            documents,
        ) = projected.into_parts();
        let (transport, response_status, response_facts) = match transport {
            ProjectedAttemptTransport::DirectHttp(response) => {
                let status = response.status();
                (
                    AttemptTransportOutcome::DirectHttp { status },
                    Some(status),
                    Some(response),
                )
            }
            ProjectedAttemptTransport::Browser { cleanup, status } => (
                AttemptTransportOutcome::Browser { cleanup, status },
                status,
                None,
            ),
        };
        let capture_facts = AttemptCaptureFacts::from_capture(&capture, response_status);
        let mut document_outcomes = Vec::with_capacity(documents.len());
        for (index, (requested, outcome)) in attempt
            .documents()
            .iter()
            .copied()
            .zip(documents)
            .enumerate()
        {
            document_outcomes.push(AttemptDocumentOutcome {
                requested,
                outcome,
                browser_observation: browser_document_observation(&capture, requested),
                document_archive_ref: document_archive_refs
                    .and_then(|references| references.get(index))
                    .and_then(Option::as_ref)
                    .cloned(),
            });
        }

        Self::Completed(AttemptResult {
            capture_id,
            capture_archive_ref,
            acquisition: attempt.kind(),
            authored_selection,
            requested_target: prepared.target().to_owned(),
            policy_snapshot,
            applied_policy,
            capture_facts,
            transport,
            response_facts,
            raw_response,
            documents: document_outcomes,
        })
    }

    #[allow(
        clippy::too_many_arguments,
        reason = "failure construction keeps each bounded evidence class explicit"
    )]
    pub(crate) fn failed(
        prepared: &PreparedPageRequest,
        attempt: &PreparedAttempt,
        kind: AttemptFailureKind,
        diagnostic: AttemptDiagnostic,
        resolution_error: Option<PolicyResolutionError>,
        applied_policy: Option<AppliedPolicy>,
        capture_archive_ref: Option<CaptureArchiveRef>,
        capture_failure_facts: Option<AttemptCaptureFailureFacts>,
        capture_facts: Option<AttemptCaptureFacts>,
    ) -> Self {
        Self::Failed(AttemptFailure {
            capture_id: attempt.capture_id(),
            acquisition: attempt.kind(),
            authored_selection: attempt.authored_selection(),
            requested_target: prepared.target().to_owned(),
            policy_snapshot: prepared.policy_snapshot().clone(),
            applied_policy,
            capture_archive_ref,
            kind,
            diagnostic,
            resolution_error,
            capture_failure_facts,
            capture_facts,
        })
    }

    pub(crate) fn not_started_outcome(
        prepared: &PreparedPageRequest,
        attempt: &PreparedAttempt,
        reason: NotStartedReason,
    ) -> Self {
        Self::NotStarted(NotStartedAttempt {
            planned_capture_id: attempt.capture_id(),
            acquisition: attempt.kind(),
            authored_selection: attempt.authored_selection(),
            requested_target: prepared.target().to_owned(),
            policy_snapshot: prepared.policy_snapshot().clone(),
            reason,
        })
    }

    /// Returns the identity allocated for this authored acquisition.
    pub const fn capture_id(&self) -> CaptureId {
        match self {
            Self::Completed(result) => result.capture_id,
            Self::Failed(failure) => failure.capture_id,
            Self::NotStarted(attempt) => attempt.planned_capture_id,
        }
    }

    pub const fn acquisition(&self) -> AcquisitionKind {
        match self {
            Self::Completed(result) => result.acquisition,
            Self::Failed(failure) => failure.acquisition,
            Self::NotStarted(attempt) => attempt.acquisition,
        }
    }

    pub const fn authored_selection(&self) -> DocumentSelectionKind {
        match self {
            Self::Completed(result) => result.authored_selection,
            Self::Failed(failure) => failure.authored_selection,
            Self::NotStarted(attempt) => attempt.authored_selection,
        }
    }

    pub fn requested_target(&self) -> &str {
        match self {
            Self::Completed(result) => &result.requested_target,
            Self::Failed(failure) => &failure.requested_target,
            Self::NotStarted(attempt) => &attempt.requested_target,
        }
    }

    /// Returns the final target only when the adapter observed one.
    pub fn final_target(&self) -> Option<&ResolvedWebUrl> {
        match self {
            Self::Completed(result) => result.capture_facts.final_target(),
            Self::Failed(failure) => failure
                .capture_facts
                .as_ref()
                .and_then(AttemptCaptureFacts::final_target)
                .or_else(|| {
                    failure
                        .capture_failure_facts
                        .as_ref()
                        .and_then(AttemptCaptureFailureFacts::final_target)
                }),
            Self::NotStarted(_) => None,
        }
    }

    /// Returns redirect observations without treating unobserved as empty.
    pub fn redirects(&self) -> Option<&Observation<Vec<RedirectHop>>> {
        match self {
            Self::Completed(result) => Some(result.capture_facts.redirects()),
            Self::Failed(failure) => failure
                .capture_facts
                .as_ref()
                .map(AttemptCaptureFacts::redirects)
                .or_else(|| {
                    failure
                        .capture_failure_facts
                        .as_ref()
                        .and_then(AttemptCaptureFailureFacts::redirects)
                }),
            Self::NotStarted(_) => None,
        }
    }

    /// Returns the observed response status, when available.
    pub fn status(&self) -> Option<u16> {
        match self {
            Self::Completed(result) => result.transport.status(),
            Self::Failed(failure) => failure
                .capture_failure_facts
                .as_ref()
                .and_then(AttemptCaptureFailureFacts::response_status)
                .or_else(|| {
                    failure
                        .capture_facts
                        .as_ref()
                        .and_then(AttemptCaptureFacts::response_status)
                }),
            Self::NotStarted(_) => None,
        }
    }

    pub const fn result(&self) -> Option<&AttemptResult> {
        match self {
            Self::Completed(result) => Some(result),
            Self::Failed(_) | Self::NotStarted(_) => None,
        }
    }
    pub const fn failure(&self) -> Option<&AttemptFailure> {
        match self {
            Self::Failed(failure) => Some(failure),
            Self::Completed(_) | Self::NotStarted(_) => None,
        }
    }
    pub const fn not_started(&self) -> Option<&NotStartedAttempt> {
        match self {
            Self::NotStarted(attempt) => Some(attempt),
            Self::Completed(_) | Self::Failed(_) => None,
        }
    }
    pub const fn capture_facts(&self) -> Option<&AttemptCaptureFacts> {
        match self {
            Self::Completed(result) => Some(&result.capture_facts),
            Self::Failed(failure) => failure.capture_facts.as_ref(),
            Self::NotStarted(_) => None,
        }
    }
    pub(in crate::request::execution) fn observed_cancellation(&self) -> bool {
        match self {
            Self::Completed(result) => result.capture_facts.observed_cancellation(),
            Self::Failed(failure) => failure.observed_cancellation(),
            Self::NotStarted(_) => true,
        }
    }
}

impl fmt::Debug for AttemptOutcome {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Completed(result) => formatter
                .debug_tuple("AttemptOutcome::Completed")
                .field(result)
                .finish(),
            Self::Failed(failure) => formatter
                .debug_tuple("AttemptOutcome::Failed")
                .field(failure)
                .finish(),
            Self::NotStarted(attempt) => formatter
                .debug_tuple("AttemptOutcome::NotStarted")
                .field(attempt)
                .finish(),
        }
    }
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
