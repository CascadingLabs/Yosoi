//! Observed resolution facts composed with a terminal capture receipt.

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;
use yosoi_types::CaptureReceipt;

use crate::{ObservedWebOrigin, ResolvedWebUrl, WebCaptureRequest};

/// Whether a producer observed a particular fact.
///
/// `Unobserved` is distinct from an observed empty collection or a guessed
/// value. Producers must not substitute the requested target for an unobserved
/// final URL.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
pub enum Observation<T> {
    /// The producer directly observed and retained the fact.
    Observed(T),
    /// The producer did not observe or retain the fact.
    Unobserved,
}

impl<T> Observation<T> {
    /// Returns the observed value, if one exists.
    pub const fn as_observed(&self) -> Option<&T> {
        match self {
            Self::Observed(value) => Some(value),
            Self::Unobserved => None,
        }
    }
}

/// Error returned when an HTTP status cannot describe a URL transition.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("HTTP redirect status must be one of 300, 301, 302, 303, 305, 307, or 308")]
pub struct HttpRedirectStatusError;

/// Validated HTTP redirect status.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(try_from = "u16", into = "u16")]
pub struct HttpRedirectStatus(u16);

impl HttpRedirectStatus {
    /// Returns the numeric HTTP status.
    pub const fn get(self) -> u16 {
        self.0
    }
}

impl TryFrom<u16> for HttpRedirectStatus {
    type Error = HttpRedirectStatusError;

    fn try_from(value: u16) -> Result<Self, Self::Error> {
        if matches!(value, 300 | 301 | 302 | 303 | 305 | 307 | 308) {
            Ok(Self(value))
        } else {
            Err(HttpRedirectStatusError)
        }
    }
}

impl From<HttpRedirectStatus> for u16 {
    fn from(value: HttpRedirectStatus) -> Self {
        value.get()
    }
}

/// Observed reason that one URL led to another.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "kind", content = "status", rename_all = "snake_case")]
pub enum RedirectCause {
    /// An HTTP response supplied a redirect status.
    Http(HttpRedirectStatus),
    /// The document initiated a meta-refresh navigation.
    MetaRefresh,
    /// Script initiated another navigation.
    Script,
    /// The producer observed a redirect but could not classify it further.
    Other,
}

/// One observed transition in a redirect or navigation chain.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RedirectHop {
    from: ResolvedWebUrl,
    to: ResolvedWebUrl,
    cause: RedirectCause,
}

impl RedirectHop {
    /// Creates one observed URL transition.
    pub const fn new(from: ResolvedWebUrl, to: ResolvedWebUrl, cause: RedirectCause) -> Self {
        Self { from, to, cause }
    }

    /// Returns the URL before the transition.
    pub const fn from(&self) -> &ResolvedWebUrl {
        &self.from
    }

    /// Returns the URL after the transition.
    pub const fn to(&self) -> &ResolvedWebUrl {
        &self.to
    }

    /// Returns the observed transition cause.
    pub const fn cause(&self) -> &RedirectCause {
        &self.cause
    }
}

/// Error returned when observed resolution facts contradict one another.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum CaptureResolutionError {
    /// Adjacent redirect hops do not form one chain.
    #[error("observed redirect hops must form a continuous chain")]
    DiscontinuousRedirects,
    /// The final redirect target disagrees with the observed final URL.
    #[error("last observed redirect target must equal the observed final URL")]
    RedirectFinalUrlMismatch,
}

/// URL and origin facts observed while resolving a capture target.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CaptureResolution {
    final_url: Observation<ResolvedWebUrl>,
    redirects: Observation<Vec<RedirectHop>>,
    resource_origin: Observation<ObservedWebOrigin>,
    initiator_origin: Observation<ObservedWebOrigin>,
}

impl CaptureResolution {
    /// Creates and validates a set of observed resolution facts.
    pub fn new(
        final_url: Observation<ResolvedWebUrl>,
        redirects: Observation<Vec<RedirectHop>>,
        resource_origin: Observation<ObservedWebOrigin>,
        initiator_origin: Observation<ObservedWebOrigin>,
    ) -> Result<Self, CaptureResolutionError> {
        validate_redirects(&final_url, &redirects)?;
        Ok(Self {
            final_url,
            redirects,
            resource_origin,
            initiator_origin,
        })
    }

    /// Returns the final URL observation without inventing a fallback value.
    pub const fn final_url(&self) -> &Observation<ResolvedWebUrl> {
        &self.final_url
    }

    /// Returns the redirect-history observation.
    ///
    /// `Observed(vec![])` means the producer observed zero redirects;
    /// `Unobserved` means it cannot make that claim.
    pub const fn redirects(&self) -> &Observation<Vec<RedirectHop>> {
        &self.redirects
    }

    /// Returns the origin observation for the resource that produced the capture.
    pub const fn resource_origin(&self) -> &Observation<ObservedWebOrigin> {
        &self.resource_origin
    }

    /// Returns the origin that initiated a page-context request or navigation.
    ///
    /// Direct HTTP attempts normally leave this unobserved. It is separate from
    /// the resource origin because CORS, credentials, and service workers can
    /// depend on the initiator rather than the target resource.
    pub const fn initiator_origin(&self) -> &Observation<ObservedWebOrigin> {
        &self.initiator_origin
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CaptureResolutionWire {
    final_url: Observation<ResolvedWebUrl>,
    redirects: Observation<Vec<RedirectHop>>,
    resource_origin: Observation<ObservedWebOrigin>,
    initiator_origin: Observation<ObservedWebOrigin>,
}

impl TryFrom<CaptureResolutionWire> for CaptureResolution {
    type Error = CaptureResolutionError;

    fn try_from(value: CaptureResolutionWire) -> Result<Self, Self::Error> {
        Self::new(
            value.final_url,
            value.redirects,
            value.resource_origin,
            value.initiator_origin,
        )
    }
}

impl<'de> Deserialize<'de> for CaptureResolution {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        CaptureResolutionWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Error returned when an acquisition record contains contradictory facts.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum WebAcquisitionRecordError {
    /// The request and terminal receipt identify different attempts.
    #[error("request capture identity must match the terminal receipt")]
    ReceiptIdentityMismatch,
    /// The first observed redirect did not start from the requested target.
    #[error("first observed redirect source must equal the requested target")]
    RedirectInitialUrlMismatch,
    /// A tuple resource origin disagreed with the observed final URL.
    #[error("tuple resource origin must match the observed final URL")]
    ResourceOriginMismatch,
    /// An opaque origin was allocated by a different capture occurrence.
    #[error("opaque resource origin must belong to the acquisition capture")]
    ForeignOpaqueOrigin,
}

/// One concrete request, its observed resolution, and its terminal receipt.
///
/// This record does not claim to be the final immutable `WebCapture` aggregate
/// owned by CAS-292. It records only CAS-295 acquisition facts and does not infer
/// the target from artifacts or provenance. A retry or fallback strategy
/// produces another record with a fresh receipt.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct WebAcquisitionRecord {
    request: WebCaptureRequest,
    resolution: CaptureResolution,
    receipt: CaptureReceipt,
}

impl WebAcquisitionRecord {
    /// Creates a record after checking capture-local acquisition invariants.
    pub fn new(
        request: WebCaptureRequest,
        resolution: CaptureResolution,
        receipt: CaptureReceipt,
    ) -> Result<Self, WebAcquisitionRecordError> {
        validate_record(&request, &resolution, &receipt)?;
        Ok(Self {
            request,
            resolution,
            receipt,
        })
    }

    /// Returns the immutable request snapshot.
    pub const fn request(&self) -> &WebCaptureRequest {
        &self.request
    }

    /// Returns observed URL and origin facts.
    pub const fn resolution(&self) -> &CaptureResolution {
        &self.resolution
    }

    /// Returns the generic terminal capture receipt.
    pub const fn receipt(&self) -> &CaptureReceipt {
        &self.receipt
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WebAcquisitionRecordWire {
    request: WebCaptureRequest,
    resolution: CaptureResolution,
    receipt: CaptureReceipt,
}

impl TryFrom<WebAcquisitionRecordWire> for WebAcquisitionRecord {
    type Error = WebAcquisitionRecordError;

    fn try_from(value: WebAcquisitionRecordWire) -> Result<Self, Self::Error> {
        Self::new(value.request, value.resolution, value.receipt)
    }
}

impl<'de> Deserialize<'de> for WebAcquisitionRecord {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        WebAcquisitionRecordWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

fn validate_redirects(
    final_url: &Observation<ResolvedWebUrl>,
    redirects: &Observation<Vec<RedirectHop>>,
) -> Result<(), CaptureResolutionError> {
    let Observation::Observed(hops) = redirects else {
        return Ok(());
    };

    let mut previous_target: Option<&ResolvedWebUrl> = None;
    for hop in hops {
        if previous_target.is_some_and(|target| !target.same_network_resource_as(hop.from())) {
            return Err(CaptureResolutionError::DiscontinuousRedirects);
        }
        previous_target = Some(hop.to());
    }

    match (previous_target, final_url) {
        (Some(last_target), Observation::Observed(observed_final_url))
            if !last_target.same_network_resource_as(observed_final_url) =>
        {
            return Err(CaptureResolutionError::RedirectFinalUrlMismatch);
        }
        _ => {}
    }
    Ok(())
}

fn validate_record(
    request: &WebCaptureRequest,
    resolution: &CaptureResolution,
    receipt: &CaptureReceipt,
) -> Result<(), WebAcquisitionRecordError> {
    if request.capture_id() != receipt.id() {
        return Err(WebAcquisitionRecordError::ReceiptIdentityMismatch);
    }
    let redirect_source_mismatch = match resolution.redirects() {
        Observation::Observed(redirects) => redirects
            .first()
            .is_some_and(|first| !request.target().matches_redirect_source(first.from())),
        Observation::Unobserved => false,
    };
    if redirect_source_mismatch {
        return Err(WebAcquisitionRecordError::RedirectInitialUrlMismatch);
    }
    match (resolution.final_url(), resolution.resource_origin()) {
        (
            Observation::Observed(final_url),
            Observation::Observed(ObservedWebOrigin::Tuple(resource_origin)),
        ) if &final_url.origin() != resource_origin => {
            return Err(WebAcquisitionRecordError::ResourceOriginMismatch);
        }
        _ => {}
    }

    for origin in [resolution.resource_origin(), resolution.initiator_origin()] {
        match origin {
            Observation::Observed(ObservedWebOrigin::Opaque(origin_id))
                if origin_id.capture_id() != receipt.id() =>
            {
                return Err(WebAcquisitionRecordError::ForeignOpaqueOrigin);
            }
            _ => {}
        }
    }
    Ok(())
}
