//! Direct HTTP capture producer built on the provider-neutral web capture foundation.
//!
//! Dependency direction is one-way: this producer depends on `yosoi-web-capture`;
//! the foundation never depends on this crate or on the HTTP transport.

#![allow(
    clippy::redundant_pub_crate,
    reason = "crate-private HTTP seams are shared across private acquisition modules"
)]

pub use yosoi_web_capture::*;

mod direct_http_orchestration;
mod direct_http_spec;
mod executor;
mod lifecycle;

pub use direct_http_orchestration::{
    DirectHttpCapture, DirectHttpCaptureError, DirectHttpCaptureEvidence,
    DirectHttpCaptureTimestamps, DirectHttpConstructionError, DirectHttpReplayError,
    capture_direct_http, capture_direct_http_at, capture_direct_http_at_with_redirect_policy,
    capture_direct_http_with_clock, capture_direct_http_with_redirect_policy,
};
pub use direct_http_spec::{
    AcceptedSourceFormat, AcceptedSourceFormats, DirectHttpCaptureSpecError,
    DirectHttpContentLimits, DirectHttpOutputSchemas, DirectHttpRedirectPolicy, RedirectHopLimit,
    ResolvedDirectHttpCaptureSpec, SourceRetentionPolicy, UnsupportedSourceFormatBehavior,
    XmlSourceProfile,
};
pub use executor::{
    execute_direct_http, execute_direct_http_at, execute_direct_http_at_with_redirect_policy,
    execute_direct_http_with_client_at,
};
pub use lifecycle::{LifecycleError, finalize_direct_http_attempt};

pub(crate) mod body;
mod error;
mod failure;
mod identity;
mod redirect;
#[cfg(test)]
mod redirect_protocol_tests;
#[cfg(test)]
mod redirect_test_assertions;
#[cfg(test)]
mod redirect_tests;
#[cfg(test)]
mod redirect_traversal_tests;
mod response;
mod termination;
#[cfg(test)]
mod tests;

pub use body::{
    BodyTerminal, ContentEncodingError, HttpContentCoding, ResponseBodyError, ResponseBodyFailure,
    ResponseBodyOutcome, consume_response_body, parse_content_encoding,
};
pub use error::{DirectHttpTransportError, DirectHttpTransportErrorKind};
pub use failure::{DirectHttpFailure, DirectHttpTerminationFailure};
pub use identity::{
    DirectHttpDependencyIdentity, DirectHttpExecutionIdentity, wreq_adapter_producer,
};
pub use redirect::{DirectHttpRedirectErrorKind, DirectHttpRedirectTargetPolicy};
pub use response::{
    BoundedHeaderValue, DirectHttpProtocol, DirectHttpResponseFacts, ObservedContentLength,
    ObservedHeaderValue, PendingDirectHttpResponse,
};
