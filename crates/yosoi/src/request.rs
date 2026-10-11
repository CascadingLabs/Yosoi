//! Author page requests, apply a policy, and inspect their results.

mod authoring;
mod outcomes;
mod response;

pub use crate::internal::engine::projection::{
    DecodingErrorCode, PartialReason, UnavailableReason, UnknownReason, UnprojectableReason,
    WebArtifactFamily,
};
pub use crate::internal::engine::request::BrowserFailureReason;
pub use crate::internal::engine::request::execution::{
    DirectHttpRedirectErrorKind, DirectHttpTransportErrorKind,
};
pub use crate::internal::engine::request::{
    AttemptDiagnostic, AttemptFailureKind, NotStartedReason,
};
pub use crate::internal::engine::{
    ActivityId, CancellationToken, CaptureId, RequestId, ResponseTermination, WebTarget,
};
pub use authoring::{
    BoundPageRequest, PageRequest, RequestPreparationError, RequestSendError, new,
};
pub use outcomes::{Attempt, AttemptDocument, AttemptState, DocumentOutcome};
pub use response::{Response, ResponseRef};
