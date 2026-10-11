use super::super::capture_facts::{
    AttemptCaptureFacts, AttemptCaptureFailureFacts, browser_document_observation,
};
use super::super::failure::{
    AttemptDiagnostic, AttemptFailure, AttemptFailureKind, NotStartedAttempt, NotStartedReason,
};
use super::{AttemptDocumentOutcome, AttemptOutcome, AttemptResult, AttemptTransportOutcome};
use crate::internal::engine::{
    AppliedPolicy, CaptureArchiveRef, DocumentArchiveRef, PolicyResolutionError, PreparedAttempt,
    PreparedPageRequest, ProjectedAttempt, projection::ProjectedAttemptTransport,
};
use crate::internal::policy::policy::{AcquisitionKind, DocumentSelectionKind};
use crate::internal::types::CaptureId;
use crate::internal::web_capture::{Observation, RedirectHop, ResolvedWebUrl};
use std::fmt;

impl AttemptOutcome {
    pub(in crate::internal::engine) fn completed(
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
    pub(in crate::internal::engine) fn failed(
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

    pub(in crate::internal::engine) fn not_started_outcome(
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
    pub(in crate::internal::engine::request::execution) fn observed_cancellation(&self) -> bool {
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
