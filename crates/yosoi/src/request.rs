//! Author page requests, apply a policy, and inspect their results.

mod authoring;
mod outcomes;
mod response;

pub use authoring::{
    BoundPageRequest, PageRequest, RequestPreparationError, RequestSendError, new,
};
pub use outcomes::{Attempt, AttemptDocument, AttemptState, DocumentOutcome};
pub use response::{Response, ResponseRef};
pub use yosoi_engine::projection::{PartialReason, UnavailableReason, UnprojectableReason};
pub use yosoi_engine::request::{AttemptDiagnostic, AttemptFailureKind, NotStartedReason};
pub use yosoi_engine::{
    ActivityId, CancellationToken, CaptureId, RequestId, ResponseTermination, WebTarget,
};
