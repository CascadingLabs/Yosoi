use std::fmt;

use tokio::time::Instant;
use wreq::header::{
    CONTENT_ENCODING, CONTENT_LENGTH, CONTENT_TYPE, HeaderMap, HeaderName, LOCATION,
};

use crate::internal::direct_http::{
    AttemptBoundary, BoundedAcquisitionLifecycle, CaptureResolution, RequestedWebTarget,
    ResolvedDirectHttpCaptureSpec, ResolvedWebUrl, SourceMediaType,
};

use super::{DirectHttpExecutionIdentity, DirectHttpTransportError};

const MAX_CAPTURED_HEADER_BYTES: usize = 1_024;

/// Protocol version observed at the response-head boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DirectHttpProtocol {
    Http09,
    Http10,
    Http11,
    Http2,
    Http3,
    Other,
}

/// Bounded observation of one allowlisted response header.
#[derive(Clone, Eq, PartialEq)]
pub struct BoundedHeaderValue(String);
impl fmt::Debug for BoundedHeaderValue {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("[redacted]")
    }
}
impl BoundedHeaderValue {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Eq, PartialEq)]
pub enum ObservedHeaderValue {
    Absent,
    Value(BoundedHeaderValue),
    InvalidEncoding,
    TooLong,
    /// More than one field line was observed for a singleton header.
    Duplicate,
}

/// Parsed and bounded Content-Length observation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObservedContentLength {
    Absent,
    Value(u64),
    Invalid,
    TooLong,
}

/// Allowlisted, bounded response-head facts. URLs are intentionally not serialized and its
/// custom Debug implementation never reveals query-bearing values.
#[derive(Clone, Eq, PartialEq)]
pub struct DirectHttpResponseFacts {
    status: u16,
    requested_url: RequestedWebTarget,
    final_url: ResolvedWebUrl,
    protocol: DirectHttpProtocol,
    content_type: ObservedHeaderValue,
    content_encoding: ObservedHeaderValue,
    content_length: ObservedContentLength,
    location: ObservedHeaderValue,
}

impl ObservedHeaderValue {
    /// Observes one already-decoded field value while enforcing the durable bound.
    pub fn from_text(value: impl Into<String>) -> Self {
        let value = value.into();
        if value.len() > MAX_CAPTURED_HEADER_BYTES {
            Self::TooLong
        } else {
            Self::Value(BoundedHeaderValue(value))
        }
    }
}

impl From<&ObservedHeaderValue> for SourceMediaType {
    fn from(value: &ObservedHeaderValue) -> Self {
        match value {
            ObservedHeaderValue::Absent => Self::Absent,
            ObservedHeaderValue::Value(value) => Self::from_text(value.as_str()),
            ObservedHeaderValue::InvalidEncoding => Self::InvalidEncoding,
            ObservedHeaderValue::TooLong => Self::TooLong,
            ObservedHeaderValue::Duplicate => Self::Duplicate,
        }
    }
}

impl DirectHttpResponseFacts {
    /// Reconstructs bounded response facts for deterministic offline replay.
    pub const fn from_observations(
        status: u16,
        requested_url: RequestedWebTarget,
        final_url: ResolvedWebUrl,
        protocol: DirectHttpProtocol,
        content_type: ObservedHeaderValue,
        content_encoding: ObservedHeaderValue,
        content_length: ObservedContentLength,
    ) -> Self {
        Self {
            status,
            requested_url,
            final_url,
            protocol,
            content_type,
            content_encoding,
            content_length,
            location: ObservedHeaderValue::Absent,
        }
    }

    pub(in crate::internal::direct_http) fn observe(
        requested_url: &RequestedWebTarget,
        response: &wreq::Response,
    ) -> Result<Self, DirectHttpTransportError> {
        let final_url_text = response.uri().to_string();
        let final_url = ResolvedWebUrl::parse(&final_url_text)
            .map_err(DirectHttpTransportError::response_url)?;
        Ok(Self {
            status: response.status().as_u16(),
            requested_url: requested_url.clone(),
            final_url,
            protocol: protocol(response.version()),
            content_type: singleton_header(response.headers(), CONTENT_TYPE),
            content_encoding: list_header(response.headers(), CONTENT_ENCODING),
            content_length: content_length(response.headers()),
            location: singleton_header(response.headers(), LOCATION),
        })
    }

    pub const fn status(&self) -> u16 {
        self.status
    }
    pub const fn requested_url(&self) -> &RequestedWebTarget {
        &self.requested_url
    }
    pub const fn final_url(&self) -> &ResolvedWebUrl {
        &self.final_url
    }
    pub const fn protocol(&self) -> DirectHttpProtocol {
        self.protocol
    }
    pub const fn content_type(&self) -> &ObservedHeaderValue {
        &self.content_type
    }
    pub fn source_media_type(&self) -> SourceMediaType {
        SourceMediaType::from(&self.content_type)
    }
    pub const fn content_encoding(&self) -> &ObservedHeaderValue {
        &self.content_encoding
    }
    pub const fn content_length(&self) -> &ObservedContentLength {
        &self.content_length
    }

    /// Bounded Location observation for callers that explicitly manage redirects.
    pub const fn location(&self) -> &ObservedHeaderValue {
        &self.location
    }
}

impl fmt::Debug for ObservedHeaderValue {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Absent => formatter.write_str("Absent"),
            Self::Value(_) => formatter.write_str("Value([redacted])"),
            Self::InvalidEncoding => formatter.write_str("InvalidEncoding"),
            Self::TooLong => formatter.write_str("TooLong"),
            Self::Duplicate => formatter.write_str("Duplicate"),
        }
    }
}

impl fmt::Debug for DirectHttpResponseFacts {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DirectHttpResponseFacts")
            .field("status", &self.status)
            .field("requested_url", &"[redacted]")
            .field("final_url", &"[redacted]")
            .field("protocol", &self.protocol)
            .field("content_type", &self.content_type)
            .field("content_encoding", &self.content_encoding)
            .field("content_length", &self.content_length)
            .field("location", &self.location)
            .finish()
    }
}

/// Provider-specific handoff containing an unconsumed body and a still-running lifecycle.
pub struct PendingDirectHttpResponse {
    response: wreq::Response,
    spec: ResolvedDirectHttpCaptureSpec,
    facts: DirectHttpResponseFacts,
    resolution: CaptureResolution,
    lifecycle: BoundedAcquisitionLifecycle,
    identity: DirectHttpExecutionIdentity,
    boundary: AttemptBoundary,
}

impl PendingDirectHttpResponse {
    pub(in crate::internal::direct_http) const fn new(
        response: wreq::Response,
        spec: ResolvedDirectHttpCaptureSpec,
        facts: DirectHttpResponseFacts,
        resolution: CaptureResolution,
        lifecycle: BoundedAcquisitionLifecycle,
        identity: DirectHttpExecutionIdentity,
        boundary: AttemptBoundary,
    ) -> Self {
        Self {
            response,
            spec,
            facts,
            resolution,
            lifecycle,
            identity,
            boundary,
        }
    }

    pub const fn spec(&self) -> &ResolvedDirectHttpCaptureSpec {
        &self.spec
    }
    pub const fn facts(&self) -> &DirectHttpResponseFacts {
        &self.facts
    }
    pub const fn resolution(&self) -> &CaptureResolution {
        &self.resolution
    }
    pub const fn lifecycle(&self) -> &BoundedAcquisitionLifecycle {
        &self.lifecycle
    }
    pub const fn lifecycle_mut(&mut self) -> &mut BoundedAcquisitionLifecycle {
        &mut self.lifecycle
    }
    pub const fn identity(&self) -> &DirectHttpExecutionIdentity {
        &self.identity
    }
    /// The absolute traversal deadline established before the first request.
    pub fn deadline(&self) -> Instant {
        Instant::from_std(self.boundary.deadline())
    }
    pub const fn boundary(&self) -> AttemptBoundary {
        self.boundary
    }

    /// Transfers the response and every item of downstream acquisition context.
    pub fn into_parts(
        self,
    ) -> (
        wreq::Response,
        ResolvedDirectHttpCaptureSpec,
        DirectHttpResponseFacts,
        CaptureResolution,
        BoundedAcquisitionLifecycle,
        DirectHttpExecutionIdentity,
        AttemptBoundary,
    ) {
        (
            self.response,
            self.spec,
            self.facts,
            self.resolution,
            self.lifecycle,
            self.identity,
            self.boundary,
        )
    }
}

impl fmt::Debug for PendingDirectHttpResponse {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PendingDirectHttpResponse")
            .field("facts", &self.facts)
            .field("capture_id", &self.lifecycle.capture_id())
            .field("identity", &self.identity)
            .field("body", &"[opaque]")
            .finish_non_exhaustive()
    }
}

fn list_header(headers: &HeaderMap, name: HeaderName) -> ObservedHeaderValue {
    let mut combined = String::new();
    for value in &headers.get_all(name) {
        let Ok(text) = value.to_str() else {
            return ObservedHeaderValue::InvalidEncoding;
        };
        let separator = usize::from(!combined.is_empty());
        let Some(length) = combined
            .len()
            .checked_add(separator)
            .and_then(|n| n.checked_add(text.len()))
        else {
            return ObservedHeaderValue::TooLong;
        };
        if length > MAX_CAPTURED_HEADER_BYTES {
            return ObservedHeaderValue::TooLong;
        }
        if separator != 0 {
            combined.push(',');
        }
        combined.push_str(text);
    }
    if combined.is_empty() {
        ObservedHeaderValue::Absent
    } else {
        ObservedHeaderValue::Value(BoundedHeaderValue(combined))
    }
}

pub(super) fn content_length(headers: &HeaderMap) -> ObservedContentLength {
    let Some(value) = headers.get(CONTENT_LENGTH) else {
        return ObservedContentLength::Absent;
    };
    if value.as_bytes().len() > 20 {
        return ObservedContentLength::TooLong;
    }
    value
        .to_str()
        .ok()
        .and_then(|text| text.parse::<u64>().ok())
        .map_or(ObservedContentLength::Invalid, ObservedContentLength::Value)
}

fn singleton_header(headers: &HeaderMap, name: HeaderName) -> ObservedHeaderValue {
    if headers.get_all(&name).iter().count() > 1 {
        return ObservedHeaderValue::Duplicate;
    }
    header(headers, name)
}

pub(super) fn header(headers: &HeaderMap, name: HeaderName) -> ObservedHeaderValue {
    let Some(value) = headers.get(name) else {
        return ObservedHeaderValue::Absent;
    };
    let bytes = value.as_bytes();
    if bytes.len() > MAX_CAPTURED_HEADER_BYTES {
        return ObservedHeaderValue::TooLong;
    }
    value
        .to_str()
        .map_or(ObservedHeaderValue::InvalidEncoding, |value| {
            ObservedHeaderValue::Value(BoundedHeaderValue(value.to_owned()))
        })
}

const fn protocol(version: wreq::Version) -> DirectHttpProtocol {
    match version {
        wreq::Version::HTTP_09 => DirectHttpProtocol::Http09,
        wreq::Version::HTTP_10 => DirectHttpProtocol::Http10,
        wreq::Version::HTTP_11 => DirectHttpProtocol::Http11,
        wreq::Version::HTTP_2 => DirectHttpProtocol::Http2,
        wreq::Version::HTTP_3 => DirectHttpProtocol::Http3,
        _ => DirectHttpProtocol::Other,
    }
}
