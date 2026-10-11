//! Validated web targets, resolved URLs, and security origins.

use std::{fmt, num::NonZeroU32, str::FromStr};

use crate::internal::types::CaptureId;
use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use thiserror::Error;
use url::Url;

/// Error returned when a URL cannot be used as a web capture target or result.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum WebUrlParseError {
    /// The input is not an absolute URL.
    #[error("web URL must be an absolute URL: {0}")]
    InvalidUrl(#[source] url::ParseError),

    /// Only HTTP and HTTPS are valid initial web capture schemes.
    #[error("web URL scheme must be http or https")]
    UnsupportedScheme,

    /// A web target must name a network host.
    #[error("web URL must contain a host")]
    MissingHost,

    /// User information can contain secrets and is never admitted to metadata.
    #[error("web URL must not contain a username or password")]
    CredentialsNotAllowed,
}

/// The validated URL supplied by a caller before a capture attempt.
///
/// Parsing applies WHATWG URL serialization, accepts only absolute HTTP(S)
/// URLs, rejects credentials, and preserves query ordering and fragments.
#[derive(Clone, Eq, Hash, PartialEq)]
pub struct RequestedWebTarget(Url);

impl fmt::Debug for RequestedWebTarget {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_tuple("RequestedWebTarget")
            .field(&"<redacted>")
            .finish()
    }
}

impl RequestedWebTarget {
    /// Parses and validates a requested target.
    pub fn parse(value: &str) -> Result<Self, WebUrlParseError> {
        parse_web_url(value).map(Self)
    }

    /// Returns the canonical URL serialization.
    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }

    /// Returns the target's tuple security origin.
    pub fn origin(&self) -> TupleWebOrigin {
        TupleWebOrigin::from_url(&self.0)
    }

    pub(in crate::internal::web_capture) fn matches_redirect_source(
        &self,
        observed: &ResolvedWebUrl,
    ) -> bool {
        same_network_resource(&self.0, &observed.0)
    }

    pub fn as_resolved(&self) -> ResolvedWebUrl {
        ResolvedWebUrl(self.0.clone())
    }
}

impl fmt::Display for RequestedWebTarget {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for RequestedWebTarget {
    type Err = WebUrlParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::parse(value)
    }
}

impl Serialize for RequestedWebTarget {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for RequestedWebTarget {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_validated_url(deserializer)
    }
}

/// A final or intermediate URL observed during an acquisition attempt.
///
/// This is intentionally not convertible from [`RequestedWebTarget`]. A
/// producer must construct it from an observed value rather than claiming that
/// the requested target was also the final URL.
///
/// ```text
/// use crate::internal::web_capture::{RequestedWebTarget, ResolvedWebUrl};
///
/// fn requires_observed_url(_: ResolvedWebUrl) {}
/// let requested = RequestedWebTarget::parse("https://example.com").unwrap();
/// requires_observed_url(requested);
/// ```
#[derive(Clone, Eq, Hash, PartialEq)]
pub struct ResolvedWebUrl(Url);

impl fmt::Debug for ResolvedWebUrl {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_tuple("ResolvedWebUrl")
            .field(&"<redacted>")
            .finish()
    }
}

impl ResolvedWebUrl {
    /// Parses and validates an observed web URL.
    pub fn parse(value: &str) -> Result<Self, WebUrlParseError> {
        parse_web_url(value).map(Self)
    }

    /// Returns the canonical URL serialization.
    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }

    /// Returns the URL's tuple security origin.
    pub fn origin(&self) -> TupleWebOrigin {
        TupleWebOrigin::from_url(&self.0)
    }

    pub fn same_network_resource_as(&self, other: &Self) -> bool {
        same_network_resource(&self.0, &other.0)
    }

    pub fn resolve(&self, reference: &str) -> Result<Self, WebUrlParseError> {
        let url = self
            .0
            .join(reference)
            .map_err(WebUrlParseError::InvalidUrl)?;
        validate_web_url(url).map(Self)
    }
}

impl fmt::Display for ResolvedWebUrl {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for ResolvedWebUrl {
    type Err = WebUrlParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::parse(value)
    }
}

impl Serialize for ResolvedWebUrl {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for ResolvedWebUrl {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_validated_url(deserializer)
    }
}

/// Error returned when a serialized tuple origin is not canonical.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum TupleWebOriginParseError {
    /// The value was not a valid HTTP(S) URL.
    #[error(transparent)]
    InvalidUrl(#[from] WebUrlParseError),

    /// The value included URL data outside the canonical origin serialization.
    #[error("web origin must be a canonical scheme-host-port origin")]
    NonCanonical,
}

/// Canonical HTTP(S) tuple origin.
///
/// Path, query, fragment, and credentials are never part of this value. Default
/// ports are omitted according to WHATWG origin serialization.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct TupleWebOrigin(String);

impl TupleWebOrigin {
    fn from_url(url: &Url) -> Self {
        Self(url.origin().ascii_serialization())
    }

    /// Returns the canonical ASCII origin serialization.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for TupleWebOrigin {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for TupleWebOrigin {
    type Err = TupleWebOriginParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let url = parse_web_url(value)?;
        let origin = Self::from_url(&url);
        if origin.as_str() != value {
            return Err(TupleWebOriginParseError::NonCanonical);
        }
        Ok(origin)
    }
}

impl Serialize for TupleWebOrigin {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for TupleWebOrigin {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        String::deserialize(deserializer)?
            .parse()
            .map_err(D::Error::custom)
    }
}

/// Capture-local identity for an opaque browser security origin.
///
/// Opaque origins are intentionally scoped to one capture. Equal local
/// ordinals in different captures do not identify the same security origin.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OpaqueOriginId {
    capture_id: CaptureId,
    local_id: NonZeroU32,
}

impl OpaqueOriginId {
    /// Creates a capture-local opaque-origin identity.
    pub const fn new(capture_id: CaptureId, local_id: NonZeroU32) -> Self {
        Self {
            capture_id,
            local_id,
        }
    }

    /// Returns the capture in which the opaque origin was observed.
    pub const fn capture_id(self) -> CaptureId {
        self.capture_id
    }

    /// Returns the non-zero capture-local ordinal.
    pub const fn local_id(self) -> NonZeroU32 {
        self.local_id
    }
}

/// A security origin observed while capturing a document or resource.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum ObservedWebOrigin {
    /// A normal HTTP(S) tuple origin.
    Tuple(TupleWebOrigin),
    /// A browser-created opaque origin meaningful only within one capture.
    Opaque(OpaqueOriginId),
}

fn same_network_resource(first: &Url, second: &Url) -> bool {
    let mut first = first.clone();
    first.set_fragment(None);
    let mut second = second.clone();
    second.set_fragment(None);
    first == second
}

fn parse_web_url(value: &str) -> Result<Url, WebUrlParseError> {
    let url = Url::parse(value).map_err(WebUrlParseError::InvalidUrl)?;
    validate_web_url(url)
}

fn validate_web_url(url: Url) -> Result<Url, WebUrlParseError> {
    if !matches!(url.scheme(), "http" | "https") {
        return Err(WebUrlParseError::UnsupportedScheme);
    }
    if url.host().is_none() {
        return Err(WebUrlParseError::MissingHost);
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err(WebUrlParseError::CredentialsNotAllowed);
    }
    Ok(url)
}

fn deserialize_validated_url<'de, D, T>(deserializer: D) -> Result<T, D::Error>
where
    D: Deserializer<'de>,
    T: FromStr<Err = WebUrlParseError>,
{
    String::deserialize(deserializer)?
        .parse()
        .map_err(D::Error::custom)
}
