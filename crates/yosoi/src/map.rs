//! Discover pages within an explicitly bounded site scope.

pub use yosoi_engine::map::{
    DiscoverySource, Exploration, FrontierEntry, HostEntry, HostVerification, LimitReached,
    MapTermination, Observation, Omission, OmissionReason, PageEntry, PendingReason,
    PublicProvider, Rejection, Relationship, RelationshipKind, RequestTrace, SkipReason,
    SourceFailure, SourceOutcome, SourceSkipReason, SourceStatus, Summary, SupportDocument,
    SupportDocumentKind, TreeEntry, WildcardEntry,
};

use crate::{
    policy::{Policy, PolicySnapshot},
    request::{CancellationToken, ResponseRef},
};
use std::{error::Error, fmt};
use yosoi_engine::map as implementation;

/// Creates a bounded discovery request without performing I/O.
pub fn new(seed: impl Into<String>) -> MapRequest {
    MapRequest {
        inner: implementation::new(seed),
    }
}

/// A user-authored site discovery request.
#[derive(Clone, Debug)]
pub struct MapRequest {
    inner: yosoi_engine::MapRequest,
}
impl MapRequest {
    /// Validates the seed and policy without contacting a source.
    pub fn validate(&self) -> Result<(), MapError> {
        self.inner.validate().map_err(MapError)
    }

    /// Uses a complete SDK policy for discovery.
    pub fn bind(self, policy: &Policy) -> Self {
        Self {
            inner: self.inner.bind(policy),
        }
    }
    /// Executes discovery using standard SDK adapters.
    pub async fn send(self) -> Result<MapOutcome, MapError> {
        self.inner
            .send()
            .await
            .map(|inner| MapOutcome { inner })
            .map_err(MapError)
    }
    /// Executes discovery with caller-controlled cancellation.
    pub async fn send_cancellable(
        self,
        cancellation: &CancellationToken,
    ) -> Result<MapOutcome, MapError> {
        self.inner
            .send_cancellable(cancellation)
            .await
            .map(|inner| MapOutcome { inner })
            .map_err(MapError)
    }
}

/// A bounded discovery result. Captures are exposed through SDK response views.
#[derive(Debug)]
pub struct MapOutcome {
    inner: yosoi_engine::MapOutcome,
}
impl MapOutcome {
    /// Returns the immutable policy used for discovery.
    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        self.inner.policy_snapshot()
    }
    /// Returns observed hosts.
    pub fn hosts(&self) -> &[HostEntry] {
        self.inner.hosts()
    }
    /// Returns discovered pages.
    pub fn pages(&self) -> &[PageEntry] {
        self.inner.pages()
    }
    /// Returns observed relationships.
    pub fn relationships(&self) -> &[Relationship] {
        self.inner.relationships()
    }
    /// Returns queued or pending discoveries.
    pub fn frontier(&self) -> &[FrontierEntry] {
        self.inner.frontier()
    }
    /// Returns robots and sitemap support-document facts.
    pub fn support_documents(&self) -> &[SupportDocument] {
        self.inner.support_documents()
    }
    /// Returns source outcomes.
    pub fn sources(&self) -> &[SourceOutcome] {
        self.inner.sources()
    }
    /// Returns the discovery tree.
    pub fn tree(&self) -> &[TreeEntry] {
        self.inner.tree()
    }
    /// Borrows retained captures through the SDK, without cloning payloads.
    pub fn captures(&self) -> impl ExactSizeIterator<Item = RetainedCapture<'_>> {
        self.inner
            .captures()
            .iter()
            .map(|inner| RetainedCapture { inner })
    }
    /// Returns observed wildcard names.
    pub fn wildcard_names(&self) -> &[String] {
        self.inner.wildcard_names()
    }
    /// Returns wildcard patterns with their source observations.
    pub fn wildcards(&self) -> &[WildcardEntry] {
        self.inner.wildcards()
    }
    /// Returns every admitted acquisition request and its observed outcome.
    pub fn request_trace(&self) -> &[RequestTrace] {
        self.inner.request_trace()
    }
    /// Returns the reason discovery stopped.
    pub const fn termination(&self) -> MapTermination {
        self.inner.termination()
    }
    /// Returns explicit omissions.
    pub fn omissions(&self) -> &[Omission] {
        self.inner.omissions()
    }
    /// Returns bounded aggregate counts.
    pub const fn summary(&self) -> &Summary {
        self.inner.summary()
    }
}

/// A capture retained by discovery, with a borrowed SDK response.
#[derive(Clone, Copy, Debug)]
pub struct RetainedCapture<'map> {
    inner: &'map yosoi_engine::RetainedCapture,
}
impl<'map> RetainedCapture<'map> {
    /// Returns the canonical URL.
    pub fn url(self) -> &'map str {
        self.inner.url().as_str()
    }
    /// Borrows the SDK-visible response.
    pub const fn response(self) -> ResponseRef<'map> {
        ResponseRef {
            inner: self.inner.response(),
        }
    }
}

/// Discovery could not be initialized or its policy was invalid.
#[derive(Debug)]
pub struct MapError(yosoi_engine::MapError);
impl fmt::Display for MapError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}
impl Error for MapError {}
