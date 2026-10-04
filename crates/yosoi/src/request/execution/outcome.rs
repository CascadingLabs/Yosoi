mod archived;
mod attempt;
mod capture_facts;
mod failure;
mod response;

pub use attempt::{AttemptDocumentOutcome, AttemptOutcome, AttemptResult, AttemptTransportOutcome};
pub use capture_facts::{
    ArtifactDisposition, ArtifactFamilyDisposition, AttemptCaptureFacts,
    AttemptCaptureFailureFacts, BrowserDocumentObservation, BrowserTerminalClassification,
    BrowserTerminalFacts,
};
pub use failure::{
    AttemptDiagnostic, AttemptFailure, AttemptFailureKind, NotStartedAttempt, NotStartedReason,
};
pub use response::{Response, ResponseTermination};

use thiserror::Error;

use crate::{RequestPreparationError, request::execution::StandardExecutionSetupError};

/// Request preparation or standard adapter setup failed before execution.
#[derive(Debug, Error)]
pub enum RequestSendError {
    #[error(transparent)]
    Preparation(#[from] RequestPreparationError),
    /// The package-owned adapter context could not be assembled before execution.
    #[error(transparent)]
    StandardSetup(#[from] StandardExecutionSetupError),
}
pub use archived::{
    ArchivedCaptureProgress, ArchivedRequestError, ArchivedRequestProgress, ArchivedResponse,
};
