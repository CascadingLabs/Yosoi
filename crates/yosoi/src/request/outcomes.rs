use crate::internal::engine as yosoi_engine;

use super::{
    AttemptDiagnostic, AttemptFailureKind, CaptureId, NotStartedReason, PartialReason,
    UnavailableReason, UnprojectableReason,
};
use crate::{
    documents::DocumentRef,
    policy::{AcquisitionKind, DocumentRequest, DocumentSelectionKind},
};

/// The user-visible state of one acquisition.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AttemptState {
    /// Acquisition finished; inspect document outcomes and status before claiming successful or complete evidence.
    Completed,
    /// Acquisition returned the supplied bounded failure classification.
    Failed(AttemptFailureKind),
    /// Authored acquisition was retained as an unstarted slot with its explicit reason.
    NotStarted(NotStartedReason),
}

/// A borrowed acquisition outcome with SDK data and diagnostics only.
#[derive(Clone, Copy, Debug)]
pub struct Attempt<'response> {
    pub(crate) inner: &'response yosoi_engine::AttemptOutcome,
}
impl<'response> Attempt<'response> {
    /// Returns the acquisition's correlation identity.
    pub const fn capture_id(self) -> CaptureId {
        self.inner.capture_id()
    }
    /// Returns the acquisition strategy selected by policy.
    pub const fn acquisition(self) -> AcquisitionKind {
        self.inner.acquisition()
    }
    /// Returns the policy's document-selection strategy.
    pub const fn authored_selection(self) -> DocumentSelectionKind {
        self.inner.authored_selection()
    }
    /// Returns the canonical requested target.
    pub fn requested_target(self) -> &'response str {
        self.inner.requested_target()
    }
    /// Returns the HTTP status when an HTTP response was observed.
    pub fn status(self) -> Option<u16> {
        self.inner.status()
    }
    /// Returns the outcome without exposing an execution or archive object.
    pub const fn state(self) -> AttemptState {
        match self.inner {
            yosoi_engine::AttemptOutcome::Completed(_) => AttemptState::Completed,
            yosoi_engine::AttemptOutcome::Failed(failure) => AttemptState::Failed(failure.kind()),
            yosoi_engine::AttemptOutcome::NotStarted(attempt) => {
                AttemptState::NotStarted(attempt.reason())
            }
        }
    }
    /// Returns a bounded, secret-safe failure diagnostic when available.
    pub fn diagnostic(self) -> Option<AttemptDiagnostic> {
        self.inner
            .failure()
            .map(yosoi_engine::AttemptFailure::diagnostic)
    }
    /// Iterates the requested document outcomes without copying their bytes.
    pub fn documents(self) -> impl ExactSizeIterator<Item = AttemptDocument<'response>> {
        self.inner
            .result()
            .map_or(&[][..], yosoi_engine::AttemptResult::documents)
            .iter()
            .map(|inner| AttemptDocument { inner })
    }
}

/// One document requested by policy, paired with its projection outcome.
#[derive(Clone, Copy, Debug)]
pub struct AttemptDocument<'response> {
    inner: &'response yosoi_engine::AttemptDocumentOutcome,
}
impl<'response> AttemptDocument<'response> {
    /// Returns the representation requested by policy.
    pub const fn requested(self) -> DocumentRequest {
        self.inner.requested()
    }
    /// Returns only SDK documents and completeness diagnostics.
    pub fn outcome(self) -> DocumentOutcome<'response> {
        match self.inner.outcome() {
            yosoi_engine::DocumentOutcome::Produced { document, .. } => {
                DocumentOutcome::Produced(DocumentRef::from_internal(document))
            }
            yosoi_engine::DocumentOutcome::Partial {
                document, reasons, ..
            } => DocumentOutcome::Partial {
                document: document.as_ref().map(DocumentRef::from_internal),
                reasons,
            },
            yosoi_engine::DocumentOutcome::Unavailable { reason } => {
                DocumentOutcome::Unavailable(*reason)
            }
            yosoi_engine::DocumentOutcome::Unprojectable { reason } => {
                DocumentOutcome::Unprojectable(*reason)
            }
        }
    }
}

/// Materialization state. Partial and unavailable results remain explicit.
#[derive(Clone, Copy, Debug)]
pub enum DocumentOutcome<'response> {
    /// Requested representation materialized and is borrowed from the owning response.
    Produced(DocumentRef<'response>),
    /// Requested evidence is incomplete, retaining a usable document only when available.
    Partial {
        /// Borrowed usable partial document, absent when no document could be retained.
        document: Option<DocumentRef<'response>>,
        /// Borrowed bounded explanations limiting this representation completeness.
        reasons: &'response [PartialReason],
    },
    /// Required acquisition evidence was unavailable for the requested representation.
    Unavailable(UnavailableReason),
    /// Available evidence cannot support the requested document projection.
    Unprojectable(UnprojectableReason),
}
impl<'response> DocumentOutcome<'response> {
    /// Returns a safely materialized document, including a valid partial document.
    pub const fn document(self) -> Option<DocumentRef<'response>> {
        match self {
            Self::Produced(document) => Some(document),
            Self::Partial { document, .. } => document,
            Self::Unavailable(_) | Self::Unprojectable(_) => None,
        }
    }
}
