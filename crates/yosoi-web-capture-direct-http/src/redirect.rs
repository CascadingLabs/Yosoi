use std::fmt;

use wreq::header::LOCATION;

use crate::{
    CaptureResolution, HttpRedirectStatus, Observation, ObservedWebOrigin, RedirectCause,
    RedirectHop, ResolvedWebUrl, WebUrlParseError,
};

/// Runtime policy applied to each resolved redirect target before another request is sent.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DirectHttpRedirectTargetPolicy {
    /// Permit HTTP(S) targets after ordinary URL validation.
    AllowHttpAndHttps,
    /// Refuse targets whose tuple origin differs from the initial target.
    SameOrigin,
}

/// Secret-safe reason redirect traversal terminated.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DirectHttpRedirectErrorKind {
    MissingLocation,
    MalformedLocation,
    CredentialsNotAllowed,
    UnsupportedScheme,
    TargetRefused,
    Loop,
    HopLimit,
}

impl DirectHttpRedirectErrorKind {
    pub(super) const fn message(self) -> &'static str {
        match self {
            Self::MissingLocation => "redirect response did not contain a Location header",
            Self::MalformedLocation => "redirect Location was malformed",
            Self::CredentialsNotAllowed => "redirect target contained credentials",
            Self::UnsupportedScheme => "redirect target used an unsupported scheme",
            Self::TargetRefused => "redirect target was refused by policy",
            Self::Loop => "redirect traversal detected a repeated resource",
            Self::HopLimit => "redirect traversal exhausted its hop limit",
        }
    }
}

pub(super) fn status(response: &wreq::Response) -> Option<HttpRedirectStatus> {
    let status = response.status().as_u16();
    if !matches!(status, 301 | 302 | 303 | 307 | 308) {
        return None;
    }
    HttpRedirectStatus::try_from(status).ok()
}

pub(super) fn target(
    response: &wreq::Response,
    current: &ResolvedWebUrl,
) -> Result<ResolvedWebUrl, DirectHttpRedirectErrorKind> {
    let value = response
        .headers()
        .get(LOCATION)
        .ok_or(DirectHttpRedirectErrorKind::MissingLocation)?;
    let text = value
        .to_str()
        .map_err(|_| DirectHttpRedirectErrorKind::MalformedLocation)?;
    current.resolve(text).map_err(|error| map_url_error(&error))
}

const fn map_url_error(error: &WebUrlParseError) -> DirectHttpRedirectErrorKind {
    match error {
        WebUrlParseError::CredentialsNotAllowed => {
            DirectHttpRedirectErrorKind::CredentialsNotAllowed
        }
        WebUrlParseError::UnsupportedScheme => DirectHttpRedirectErrorKind::UnsupportedScheme,
        WebUrlParseError::InvalidUrl(_) | WebUrlParseError::MissingHost => {
            DirectHttpRedirectErrorKind::MalformedLocation
        }
    }
}

pub(super) fn allowed(
    policy: DirectHttpRedirectTargetPolicy,
    initial: &ResolvedWebUrl,
    target: &ResolvedWebUrl,
) -> bool {
    matches!(policy, DirectHttpRedirectTargetPolicy::AllowHttpAndHttps)
        || initial.origin() == target.origin()
}

pub(super) fn resolution(
    current: &ResolvedWebUrl,
    redirects: Vec<RedirectHop>,
) -> Result<CaptureResolution, crate::CaptureResolutionError> {
    CaptureResolution::new(
        Observation::Observed(current.clone()),
        Observation::Observed(redirects),
        Observation::Observed(ObservedWebOrigin::Tuple(current.origin())),
        Observation::Unobserved,
    )
}

pub(super) const fn hop(
    from: ResolvedWebUrl,
    to: ResolvedWebUrl,
    status: HttpRedirectStatus,
) -> RedirectHop {
    RedirectHop::new(from, to, RedirectCause::Http(status))
}

pub(super) fn repeated(visited: &[ResolvedWebUrl], target: &ResolvedWebUrl) -> bool {
    visited
        .iter()
        .any(|url| url.same_network_resource_as(target))
}

impl fmt::Display for DirectHttpRedirectErrorKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message())
    }
}
