use std::{error::Error as StdError, fmt};

use thiserror::Error;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HttpContentCoding {
    Identity,
    Gzip,
    Brotli,
    Deflate,
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ContentEncodingError {
    #[error("malformed Content-Encoding")]
    Malformed,
    #[error("unsupported Content-Encoding")]
    Unsupported,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BodyTerminal {
    Complete,
    ContentCodedLimit,
    RepresentationLimit,
    LifecycleLimit,
    Disconnect,
    MalformedCoding,
    UnsupportedCoding,
    MalformedHeader,
    Deadline,
    Cancelled,
    SinkFailure,
}

pub(crate) const fn terminal_reason(value: BodyTerminal) -> &'static str {
    match value {
        BodyTerminal::Complete => "web_capture.body.complete",
        BodyTerminal::ContentCodedLimit => "web_capture.body.content_coded_limit",
        BodyTerminal::RepresentationLimit => "web_capture.body.representation_limit",
        BodyTerminal::LifecycleLimit => "web_capture.body.lifecycle_limit",
        BodyTerminal::Disconnect => "web_capture.body.disconnect",
        BodyTerminal::MalformedCoding => "web_capture.body.malformed_coding",
        BodyTerminal::UnsupportedCoding => "web_capture.body.unsupported_coding",
        BodyTerminal::MalformedHeader => "web_capture.body.malformed_header",
        BodyTerminal::Deadline => "web_capture.body.deadline",
        BodyTerminal::Cancelled => "web_capture.body.cancelled",
        BodyTerminal::SinkFailure => "web_capture.body.sink_failure",
    }
}

#[derive(Debug, Eq, PartialEq)]
pub struct ResponseBodyOutcome {
    payload: crate::AcquiredPayloadOutcome,
    content_coded_bytes: u64,
    terminal: BodyTerminal,
}
impl ResponseBodyOutcome {
    pub(super) const fn new(
        payload: crate::AcquiredPayloadOutcome,
        content_coded_bytes: u64,
        terminal: BodyTerminal,
    ) -> Self {
        Self {
            payload,
            content_coded_bytes,
            terminal,
        }
    }
    pub const fn payload(&self) -> &crate::AcquiredPayloadOutcome {
        &self.payload
    }
    pub const fn content_coded_bytes(&self) -> u64 {
        self.content_coded_bytes
    }
    pub const fn terminal(&self) -> BodyTerminal {
        self.terminal
    }
    pub fn into_parts(self) -> (crate::AcquiredPayloadOutcome, u64, BodyTerminal) {
        (self.payload, self.content_coded_bytes, self.terminal)
    }
}

#[derive(Debug, Error)]
pub enum ResponseBodyError {
    #[error("response body lifecycle transition failed")]
    Lifecycle(#[source] crate::LifecycleError),
    #[error("response body lifecycle event was invalid")]
    LifecycleEvent(#[source] crate::LifecycleEventError),
    #[error("response body payload outcome was invalid")]
    Payload(#[source] crate::AcquiredPayloadError),
    #[error("response body terminal reason was invalid")]
    Reason(#[source] yosoi_types::NamespacedIdError),
    #[error("response body clock observation was invalid")]
    AttemptBoundary(#[source] crate::AttemptBoundaryError),
}

/// Non-lossy context for an invariant failure (ordinary body terminals remain values).
pub struct ResponseBodyFailure {
    pub(super) primary: ResponseBodyError,
    pub(super) spec: crate::ResolvedDirectHttpCaptureSpec,
    pub(super) facts: crate::DirectHttpResponseFacts,
    pub(super) resolution: crate::CaptureResolution,
    pub(super) lifecycle: crate::BoundedAcquisitionLifecycle,
    pub(super) identity: crate::DirectHttpExecutionIdentity,
    pub(super) content_coded_bytes: u64,
}
impl ResponseBodyFailure {
    pub const fn primary(&self) -> &ResponseBodyError {
        &self.primary
    }
    pub const fn spec(&self) -> &crate::ResolvedDirectHttpCaptureSpec {
        &self.spec
    }
    pub const fn facts(&self) -> &crate::DirectHttpResponseFacts {
        &self.facts
    }
    pub const fn resolution(&self) -> &crate::CaptureResolution {
        &self.resolution
    }
    pub const fn lifecycle(&self) -> &crate::BoundedAcquisitionLifecycle {
        &self.lifecycle
    }
    pub const fn identity(&self) -> &crate::DirectHttpExecutionIdentity {
        &self.identity
    }
    pub const fn content_coded_bytes(&self) -> u64 {
        self.content_coded_bytes
    }
    pub const fn response_is_consumed(&self) -> bool {
        true
    }
    pub const fn staged_body_is_publishable(&self) -> bool {
        false
    }
    pub fn into_parts(
        self,
    ) -> (
        ResponseBodyError,
        crate::ResolvedDirectHttpCaptureSpec,
        crate::DirectHttpResponseFacts,
        crate::CaptureResolution,
        crate::BoundedAcquisitionLifecycle,
        crate::DirectHttpExecutionIdentity,
        u64,
    ) {
        (
            self.primary,
            self.spec,
            self.facts,
            self.resolution,
            self.lifecycle,
            self.identity,
            self.content_coded_bytes,
        )
    }
}
impl fmt::Debug for ResponseBodyFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ResponseBodyFailure")
            .field("primary", &self.primary)
            .field("content_coded_bytes", &self.content_coded_bytes)
            .field("response", &"consumed")
            .field("staged_body", &"unpublishable")
            .finish_non_exhaustive()
    }
}
impl fmt::Display for ResponseBodyFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "response body invariant failure: {} (response consumed; staged body unpublishable)",
            self.primary
        )
    }
}
impl StdError for ResponseBodyFailure {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        Some(&self.primary)
    }
}
