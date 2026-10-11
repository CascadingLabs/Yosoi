//! Public projection from a capture to locator documents.

mod browser;
mod browser_response;
mod outcome;
mod project;

pub use crate::internal::web_capture::{DecodingErrorCode, UnknownReason, WebArtifactFamily};
pub use outcome::{
    DocumentOutcome, PartialReason, ProjectedAttempt, ProjectedAttemptTransport, ProjectionError,
    UnavailableReason, UnprojectableReason,
};
pub use project::project_attempt;
