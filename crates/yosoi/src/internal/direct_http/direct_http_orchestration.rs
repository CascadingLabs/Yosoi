//! Bundle-last orchestration for one bounded Direct HTTP attempt.
mod artifacts;
mod error;
mod finalize;
mod outcome;

pub use error::DirectHttpCaptureEvidence;
pub use error::{DirectHttpCaptureError, DirectHttpConstructionError, DirectHttpReplayError};
pub use finalize::{
    DirectHttpCaptureTimestamps, capture_direct_http, capture_direct_http_at,
    capture_direct_http_at_with_redirect_policy, capture_direct_http_with_clock,
    capture_direct_http_with_redirect_policy,
};
#[cfg(test)]
pub(in crate::internal::direct_http) use finalize::{
    capture_direct_http_with_client_at, capture_direct_http_with_sink_at,
};
pub use outcome::DirectHttpCapture;
