//! Bounded site discovery composed from existing Requests and Documents.

use crate::internal::engine as yosoi_engine;
use crate::internal::policy as yosoi_policy;
use crate::internal::web_capture as yosoi_web_capture;

mod acquisition;
mod exploration;
mod inspection;
mod inventory;
mod lifecycle;
mod outcome;
mod page_concurrency;
#[cfg(test)]
mod page_concurrency_tests;
mod preflight;
mod public_sources;
mod redirects;
#[cfg(test)]
mod tests;
mod xml_links;

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use crate::internal::map::{admission::Scope, sources::Robots};
use thiserror::Error;
use tokio::time::Instant;
use url::Url;

use crate::internal::engine::{
    CancellationToken, Document, Policy, PolicySnapshot,
    request::{self, Response},
};

pub use crate::internal::map::admission::Rejection;
pub use crate::internal::map::providers::PublicProvider;

pub use crate::internal::map::{
    DiscoverySource, Exploration, FrontierEntry, HostEntry, HostVerification, LimitReached,
    MapTermination, Observation, Omission, OmissionReason, PageEntry, PendingReason, Relationship,
    RelationshipKind, SkipReason, SourceFailure, SourceOutcome, SourceSkipReason, SourceStatus,
    Summary, SupportDocument, SupportDocumentKind, TreeEntry, WildcardEntry,
};

#[derive(Debug, Error)]
pub enum MapError {
    #[error(transparent)]
    Policy(#[from] yosoi_policy::PolicyError),
    #[error(transparent)]
    Setup(#[from] yosoi_engine::StandardExecutionSetupError),
    #[error(transparent)]
    UserAgent(#[from] yosoi_web_capture::UserAgentError),
    #[error("invalid Map seed or scope: {0}")]
    Admission(#[from] Rejection),
    #[error("Map requires exactly one Direct HTTP acquisition producing a response document")]
    UnsupportedAcquisition,
    #[error("Map deadline cannot be represented on this platform")]
    Deadline,
}

#[derive(Clone, Debug)]
pub struct MapRequest {
    seed: String,
    policy: Policy,
}

pub fn new(seed: impl Into<String>) -> MapRequest {
    MapRequest {
        seed: seed.into(),
        policy: Policy::default(),
    }
}

impl MapRequest {
    pub fn bind(mut self, policy: &Policy) -> Self {
        self.policy = policy.clone();
        self
    }

    pub async fn send(self) -> Result<MapOutcome, MapError> {
        self.send_cancellable(&CancellationToken::new()).await
    }

    pub async fn send_cancellable(
        self,
        cancellation: &CancellationToken,
    ) -> Result<MapOutcome, MapError> {
        let preflight::PreparedInputs {
            snapshot,
            seed,
            scope,
        } = self.prepare_inputs()?;
        let deadline = Instant::now()
            .checked_add(self.policy.map.limits.maximum_elapsed)
            .ok_or(MapError::Deadline)?;
        let user_agent =
            yosoi_web_capture::UserAgent::new(concat!("YosoiMap/", env!("CARGO_PKG_VERSION")))?;
        let executor = request::execution::direct_http_executor_with_user_agent(user_agent)?;
        let mut runner = Runner::new(seed, snapshot, scope, deadline, cancellation, executor);
        runner.run().await;
        Ok(runner.finish())
    }
}

#[derive(Debug)]
pub struct RetainedCapture {
    url: Url,
    response: Response,
}
impl RetainedCapture {
    pub const fn url(&self) -> &Url {
        &self.url
    }
    pub const fn response(&self) -> &Response {
        &self.response
    }
}

#[derive(Clone, Debug, serde::Serialize)]
pub struct RequestTrace {
    pub target: Url,
    pub status: Option<u16>,
    pub charged_response_bytes: u64,
}

#[derive(Debug)]
pub struct MapOutcome {
    snapshot: PolicySnapshot,
    hosts: Vec<HostEntry>,
    pages: Vec<PageEntry>,
    relationships: Vec<Relationship>,
    frontier: Vec<FrontierEntry>,
    support_documents: Vec<SupportDocument>,
    sources: Vec<SourceOutcome>,
    tree: Vec<TreeEntry>,
    captures: Vec<RetainedCapture>,
    wildcard_names: Vec<String>,
    wildcard_entries: Vec<WildcardEntry>,
    termination: MapTermination,
    summary: Summary,
    omissions: Vec<Omission>,
    request_trace: Vec<RequestTrace>,
}
impl MapOutcome {
    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        &self.snapshot
    }
    pub fn hosts(&self) -> &[HostEntry] {
        &self.hosts
    }
    pub fn pages(&self) -> &[PageEntry] {
        &self.pages
    }
    pub fn relationships(&self) -> &[Relationship] {
        &self.relationships
    }
    pub fn frontier(&self) -> &[FrontierEntry] {
        &self.frontier
    }
    pub fn support_documents(&self) -> &[SupportDocument] {
        &self.support_documents
    }
    pub fn sources(&self) -> &[SourceOutcome] {
        &self.sources
    }
    pub fn tree(&self) -> &[TreeEntry] {
        &self.tree
    }
    pub fn captures(&self) -> &[RetainedCapture] {
        &self.captures
    }
    pub fn wildcard_names(&self) -> &[String] {
        &self.wildcard_names
    }
    pub fn wildcards(&self) -> &[WildcardEntry] {
        &self.wildcard_entries
    }
    pub const fn termination(&self) -> MapTermination {
        self.termination
    }
    pub fn request_trace(&self) -> &[RequestTrace] {
        &self.request_trace
    }
    pub fn omissions(&self) -> &[Omission] {
        &self.omissions
    }
    pub const fn summary(&self) -> &Summary {
        &self.summary
    }
}

#[derive(Clone, Copy, Debug)]
enum Purpose {
    Page { depth: u16 },
    Support,
}

#[derive(Debug)]
struct Fetch {
    url: Url,
    status: u16,
    document: Option<Document>,
    raw_response: Option<Vec<u8>>,
    location: Option<String>,
    response: Response,
    aliases: Vec<Url>,
}

#[derive(Debug)]
enum FetchResult {
    Acquired(Box<Fetch>),
    Reused {
        url: Url,
        exploration: Exploration,
        aliases: Vec<Url>,
    },
}

#[derive(Clone, Debug)]
struct CachedLinks {
    source: DiscoverySource,
    urls: Vec<Url>,
}

#[derive(Debug)]
struct PageTask {
    url: Url,
    depth: u16,
    probe: bool,
}

#[derive(Debug)]
enum RobotsState {
    Rules(Robots),
    Blocked,
}

#[derive(Debug)]
struct Runner<'a> {
    seed: Url,
    snapshot: PolicySnapshot,
    scope: Scope,
    deadline: Instant,
    cancellation: &'a CancellationToken,
    hosts: BTreeMap<String, HostEntry>,
    pages: BTreeMap<Url, PageEntry>,
    edges: BTreeSet<Relationship>,
    queue: VecDeque<PageTask>,
    cache: BTreeMap<Url, CachedLinks>,
    redirects: BTreeMap<Url, Url>,
    robots: BTreeMap<String, RobotsState>,
    support: Vec<SupportDocument>,
    source_outcomes: Vec<SourceOutcome>,
    captures: Vec<RetainedCapture>,
    wildcard_names: Vec<String>,
    wildcard_entries: BTreeMap<String, Vec<Observation>>,
    summary: Summary,
    termination: Option<MapTermination>,
    sitemap_count: u32,
    probes: BTreeSet<Url>,
    omissions: BTreeMap<OmissionReason, u64>,
    executor: yosoi_engine::RequestExecutor,
    request_trace: Vec<RequestTrace>,
    reserved_response_bytes: u64,
    ready_responses: BTreeMap<
        Url,
        (
            acquisition::PreparedRequest,
            Result<Response, SourceFailure>,
        ),
    >,
}

impl<'a> Runner<'a> {
    fn new(
        seed: Url,
        snapshot: PolicySnapshot,
        scope: Scope,
        deadline: Instant,
        cancellation: &'a CancellationToken,
        executor: yosoi_engine::RequestExecutor,
    ) -> Self {
        Self {
            seed,
            snapshot,
            scope,
            deadline,
            cancellation,
            hosts: BTreeMap::new(),
            pages: BTreeMap::new(),
            edges: BTreeSet::new(),
            queue: VecDeque::new(),
            cache: BTreeMap::new(),
            redirects: BTreeMap::new(),
            robots: BTreeMap::new(),
            support: Vec::new(),
            source_outcomes: Vec::new(),
            captures: Vec::new(),
            wildcard_names: Vec::new(),
            wildcard_entries: BTreeMap::new(),
            summary: Summary::default(),
            termination: None,
            sitemap_count: 0,
            probes: BTreeSet::new(),
            omissions: BTreeMap::new(),
            executor,
            request_trace: Vec::new(),
            reserved_response_bytes: 0,
            ready_responses: BTreeMap::new(),
        }
    }
}
