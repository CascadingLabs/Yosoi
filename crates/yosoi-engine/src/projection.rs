//! Public projection from a capture to locator documents.

mod browser;
mod browser_response;
mod outcome;
mod project;

pub use outcome::{
    DocumentOutcome, PartialReason, ProjectedAttempt, ProjectedAttemptTransport, ProjectionError,
    UnavailableReason, UnprojectableReason,
};
pub use project::project_attempt;
pub use yosoi_web_capture::{DecodingErrorCode, UnknownReason, WebArtifactFamily};
