//! Bounded site discovery composed from existing Requests and Documents.

mod acquisition;
mod inspection;
mod page_concurrency;
#[cfg(test)]
mod page_concurrency_tests;
mod preflight;
mod public_sources;
mod redirects;
#[cfg(test)]
mod tests;
mod xml_links;

use std::{
    collections::{BTreeMap, BTreeSet, HashSet, VecDeque},
    mem, str,
};

use thiserror::Error;
use tokio::time::Instant;
use url::Url;
use yosoi_documents::{DocumentClass, Finding, LocateOutcome, Plan, ProjectedValue, css, output};
use yosoi_map::{
    admission::{Scope, normalize},
    sources::{self, Robots, SitemapKind},
};
use yosoi_policy::policy::{DiscoveryDocuments, PageDiscovery, Robots as RobotsPolicy};

use crate::{
    CancellationToken, Document, Policy, PolicySnapshot,
    request::{self, Response},
};

pub use yosoi_map::admission::Rejection;
pub use yosoi_map::providers::PublicProvider;

pub use yosoi_map::{
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
    Setup(#[from] crate::StandardExecutionSetupError),
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

#[derive(Clone, Debug)]
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
    executor: crate::RequestExecutor,
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
        executor: crate::RequestExecutor,
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

    fn policy(&self) -> &Policy {
        self.snapshot.policy()
    }
    const fn failure_status(&self, error: SourceFailure) -> SourceStatus {
        if self.termination.is_some() {
            SourceStatus::Truncated
        } else {
            SourceStatus::Failed(error)
        }
    }
    fn stop(&mut self, limit: LimitReached) {
        self.termination.get_or_insert(MapTermination::Limit(limit));
    }
    fn active(&mut self) -> bool {
        if self.termination.is_some() {
            return false;
        }
        if self.cancellation.is_cancelled() {
            self.termination = Some(MapTermination::Cancelled);
        } else if Instant::now() >= self.deadline {
            self.termination = Some(MapTermination::Deadline);
        }
        self.termination.is_none()
    }
    fn omit_reason(&mut self, reason: OmissionReason) {
        self.summary.omitted = self.summary.omitted.saturating_add(1);
        let count = self.omissions.entry(reason).or_default();
        *count = count.saturating_add(1);
    }
    fn omit(&mut self) {
        self.omit_reason(OmissionReason::Other);
    }
    fn reject(&mut self, reason: Rejection) {
        self.omit_reason(OmissionReason::Admission(reason));
    }
    fn charge(&mut self, bytes: usize) -> bool {
        let count = u64::try_from(bytes).unwrap_or(u64::MAX);
        let next = self.summary.inventory_bytes.saturating_add(count);
        if next > u64::from(self.policy().map.limits.max_inventory_bytes.get()) {
            self.stop(LimitReached::InventoryBytes);
            return false;
        }
        self.summary.inventory_bytes = next;
        true
    }
    fn observation(
        &mut self,
        source: DiscoverySource,
        source_url: Option<&Url>,
    ) -> Option<Observation> {
        if self.summary.observations >= self.policy().map.limits.max_observations.get() {
            self.stop(LimitReached::Observations);
            return None;
        }
        if !self.charge(64_usize.saturating_add(source_url.map_or(0, |url| url.as_str().len()))) {
            return None;
        }
        self.summary.observations = self.summary.observations.saturating_add(1);
        Some(Observation {
            source,
            source_url: source_url.cloned(),
        })
    }
    fn host(&mut self, url: &Url, source: DiscoverySource, source_url: Option<&Url>) -> bool {
        let Some(host) = url.host_str() else {
            self.omit();
            return false;
        };
        self.host_name(host, source, source_url)
    }
    fn host_name(&mut self, host: &str, source: DiscoverySource, source_url: Option<&Url>) -> bool {
        let host = match self.scope.admit_host(host) {
            Ok(host) => host,
            Err(reason) => {
                self.reject(reason);
                return false;
            }
        };
        if let Some(entry) = self.hosts.get(&host) {
            let observation = Observation {
                source,
                source_url: source_url.cloned(),
            };
            if entry.observations.contains(&observation) {
                return true;
            }
            let Some(observation) = self.observation(source, source_url) else {
                return false;
            };
            if let Some(entry) = self.hosts.get_mut(&host) {
                entry.observations.push(observation);
            }
            return true;
        }
        if self.hosts.len()
            >= usize::try_from(self.policy().map.limits.max_hosts.get()).unwrap_or(usize::MAX)
        {
            self.stop(LimitReached::Hosts);
            return false;
        }
        if !self.charge(host.len().saturating_add(128)) {
            return false;
        }
        let Some(observation) = self.observation(source, source_url) else {
            return false;
        };
        self.hosts.insert(
            host.clone(),
            HostEntry {
                host,
                observations: vec![observation],
                verification: HostVerification::Unverified,
            },
        );
        true
    }
    fn wildcard(&mut self, value: &str, source_url: &Url, source: DiscoverySource) {
        let Some(suffix) = value.strip_prefix("*.") else {
            self.omit_reason(OmissionReason::Wildcard);
            return;
        };
        if suffix.contains('*') {
            self.omit_reason(OmissionReason::Wildcard);
            return;
        }
        let suffix = match self.scope.admit_host(suffix) {
            Ok(suffix) => suffix,
            Err(reason) => {
                self.reject(reason);
                return;
            }
        };
        let pattern = format!("*.{suffix}");
        let duplicate = self
            .wildcard_entries
            .get(&pattern)
            .is_some_and(|observations| {
                observations.iter().any(|observation| {
                    observation.source == source
                        && observation.source_url.as_ref() == Some(source_url)
                })
            });
        if duplicate {
            return;
        }
        if !self.wildcard_entries.contains_key(&pattern)
            && !self.charge(pattern.len().saturating_add(64))
        {
            return;
        }
        if let Some(observation) = self.observation(source, Some(source_url)) {
            if !self.wildcard_names.contains(&pattern) {
                self.wildcard_names.push(pattern.clone());
            }
            self.wildcard_entries
                .entry(pattern)
                .or_default()
                .push(observation);
        }
    }
    fn page(
        &mut self,
        url: Url,
        depth: Option<u16>,
        source: DiscoverySource,
        source_url: Option<&Url>,
    ) -> bool {
        if let Err(reason) = self.scope.admit(&url) {
            self.reject(reason);
            return false;
        }
        if !self.host(&url, source, source_url) {
            return false;
        }
        let observation = Observation {
            source,
            source_url: source_url.cloned(),
        };
        let duplicate = self
            .pages
            .get(&url)
            .is_some_and(|page| page.observations.contains(&observation));
        if !self.pages.contains_key(&url) {
            if self.pages.len()
                >= usize::try_from(self.policy().map.limits.max_urls.get()).unwrap_or(usize::MAX)
            {
                self.stop(LimitReached::Urls);
                return false;
            }
            if !self.charge(url.as_str().len().saturating_add(192)) {
                return false;
            }
            self.pages.insert(
                url.clone(),
                PageEntry {
                    url: url.clone(),
                    minimum_link_depth: None,
                    observations: Vec::new(),
                    exploration: Exploration::Inventoried,
                },
            );
        }
        let observation = if duplicate {
            None
        } else {
            self.observation(source, source_url)
        };
        if !duplicate && observation.is_none() {
            if self
                .pages
                .get(&url)
                .is_some_and(|page| page.observations.is_empty())
            {
                self.pages.remove(&url);
            }
            return false;
        }
        let max_depth = self.policy().map.limits.max_link_depth;
        let terminal = self.pages.get(&url).is_some_and(|page| {
            matches!(
                page.exploration,
                Exploration::Failed(_)
                    | Exploration::Skipped(SkipReason::NonHtml | SkipReason::Robots)
            )
        });
        let cached = self.cache.contains_key(&url);
        let mut enqueue = false;
        if let Some(page) = self.pages.get_mut(&url) {
            if let Some(observation) = observation {
                page.observations.push(observation);
            }
            if let Some(depth) = depth
                && page
                    .minimum_link_depth
                    .is_none_or(|previous| depth < previous)
            {
                page.minimum_link_depth = Some(depth);
                if depth <= max_depth {
                    enqueue = !terminal;
                    if enqueue && !cached {
                        page.exploration = Exploration::Pending;
                    }
                } else {
                    page.exploration = Exploration::Skipped(SkipReason::Depth);
                }
            }
        }
        if enqueue {
            if self.queue.len().saturating_add(self.ready_responses.len())
                >= usize::try_from(self.policy().map.limits.max_pending.get()).unwrap_or(usize::MAX)
            {
                self.stop(LimitReached::Pending);
                return false;
            }
            self.queue.push_back(PageTask {
                url,
                depth: depth.unwrap_or(0),
                probe: false,
            });
        }
        self.termination.is_none()
    }
    fn edge(&mut self, from: &Url, to: &Url, kind: RelationshipKind) {
        let edge = Relationship {
            from: from.clone(),
            to: to.clone(),
            kind,
        };
        if self.edges.contains(&edge) {
            return;
        }
        if self.edges.len()
            >= usize::try_from(self.policy().map.limits.max_relationships.get())
                .unwrap_or(usize::MAX)
        {
            self.stop(LimitReached::Relationships);
            return;
        }
        if self.charge(
            from.as_str()
                .len()
                .saturating_add(to.as_str().len())
                .saturating_add(64),
        ) {
            self.edges.insert(edge);
        }
    }

    async fn run(&mut self) {
        self.host(&self.seed.clone(), DiscoverySource::Seed, None);
        if self.policy().map.pages == PageDiscovery::Explore {
            self.page(self.seed.clone(), Some(0), DiscoverySource::Seed, None);
        }
        self.passive().await;
        self.explore_pages().await;
        self.source_outcomes.push(SourceOutcome {
            source: DiscoverySource::HtmlLink,
            source_url: None,
            status: if self.policy().map.pages == PageDiscovery::Disabled {
                SourceStatus::Disabled
            } else if self.termination.is_some() {
                SourceStatus::Truncated
            } else {
                SourceStatus::Completed
            },
        });
    }

    async fn fetch_support(&mut self, start: &Url) -> Result<Fetch, SourceFailure> {
        match self.fetch(start, Purpose::Support).await? {
            FetchResult::Acquired(fetched) => Ok(*fetched),
            FetchResult::Reused { .. } => Err(SourceFailure::Transport),
        }
    }

    fn allowed(&self, url: &Url) -> bool {
        if self.policy().map.robots == RobotsPolicy::Ignore {
            return true;
        }
        let origin = url.origin().ascii_serialization();
        match self.robots.get(&origin) {
            Some(RobotsState::Rules(rules)) => {
                let mut path = url.path().to_owned();
                if let Some(query) = url.query() {
                    path.push('?');
                    path.push_str(query);
                }
                rules.allowed(&path)
            }
            _ => false,
        }
    }
    fn support_record(&mut self, url: Url, kind: SupportDocumentKind, status: SourceStatus) {
        if !self.charge(url.as_str().len().saturating_add(192)) {
            return;
        }
        self.support.push(SupportDocument {
            url: url.clone(),
            kind,
            status: status.clone(),
        });
        self.source_outcomes.push(SourceOutcome {
            source: if kind == SupportDocumentKind::Robots {
                DiscoverySource::Robots
            } else {
                DiscoverySource::Sitemap
            },
            source_url: Some(url),
            status,
        });
    }

    async fn ensure_origin(&mut self, page: &Url) {
        let origin = page.origin().ascii_serialization();
        if self.robots.contains_key(&origin) || !self.active() {
            return;
        }
        self.robots.insert(origin.clone(), RobotsState::Blocked);
        let Ok(root) = Url::parse(&origin) else {
            return;
        };
        let Ok(robot_url) = root.join("/robots.txt") else {
            return;
        };
        let fetched = self.fetch_support(&robot_url).await;
        let mut sitemap_urls = Vec::new();
        let max_entries = usize::try_from(self.policy().map.limits.max_parser_entries.get())
            .unwrap_or(usize::MAX);
        match fetched {
            Ok(fetched) if fetched.status == 404 || fetched.status == 410 => {
                if let Ok(rules) = Robots::parse_bounded("", "YosoiMap", max_entries) {
                    self.robots
                        .insert(origin.clone(), RobotsState::Rules(rules));
                }
                self.support_record(
                    robot_url,
                    SupportDocumentKind::Robots,
                    SourceStatus::Completed,
                );
            }
            Ok(fetched) if (200..300).contains(&fetched.status) => {
                let rules = fetched
                    .document
                    .as_ref()
                    .map(Document::bytes)
                    .or(fetched.raw_response.as_deref())
                    .or({
                        if fetched.status == 204 {
                            Some(&[])
                        } else {
                            None
                        }
                    })
                    .and_then(|bytes| str::from_utf8(bytes).ok())
                    .and_then(|text| Robots::parse_bounded(text, "YosoiMap", max_entries).ok());
                if let Some(rules) = rules {
                    sitemap_urls.extend(rules.sitemaps().iter().cloned());
                    self.robots
                        .insert(origin.clone(), RobotsState::Rules(rules));
                    self.support_record(
                        robot_url,
                        SupportDocumentKind::Robots,
                        SourceStatus::Completed,
                    );
                } else {
                    self.support_record(
                        robot_url,
                        SupportDocumentKind::Robots,
                        SourceStatus::Failed(SourceFailure::Parse),
                    );
                }
            }
            Ok(fetched) => self.support_record(
                robot_url,
                SupportDocumentKind::Robots,
                SourceStatus::Failed(SourceFailure::HttpStatus(fetched.status)),
            ),
            Err(error) => self.support_record(
                robot_url,
                SupportDocumentKind::Robots,
                self.failure_status(error),
            ),
        }
        let mut candidates: Vec<_> = sitemap_urls.into_iter().map(|url| (url, false)).collect();
        candidates.extend([
            ("/sitemap.xml".to_owned(), true),
            ("/sitemap_index.xml".to_owned(), true),
        ]);
        self.sitemaps(&root, candidates).await;
    }

    async fn sitemaps(&mut self, origin: &Url, urls: Vec<(String, bool)>) {
        let mut pending = VecDeque::new();
        // Source declarations are admitted one at a time, rather than copied
        // into a potentially oversized work queue. Nested index tasks are bounded.
        let mut declarations = urls.into_iter();
        let mut seen = BTreeSet::new();
        while self.active() {
            let Some((raw, depth, optional)) = pending.pop_front().or_else(|| {
                declarations
                    .next()
                    .map(|(url, optional)| (url, 0_u16, optional))
            }) else {
                break;
            };
            let Ok(url) = normalize(
                &raw,
                Some(origin),
                self.policy().map.limits.max_url_bytes.get(),
            ) else {
                self.omit();
                continue;
            };
            if url.origin() != origin.origin() {
                self.reject(Rejection::OriginScope);
                continue;
            }
            if !seen.insert(url.clone()) {
                continue;
            }
            if self.sitemap_count >= self.policy().map.limits.max_sitemaps.get() {
                self.stop(LimitReached::Sitemaps);
                break;
            }
            self.sitemap_count = self.sitemap_count.saturating_add(1);
            let fetched = match self.fetch_support(&url).await {
                Ok(fetched) => fetched,
                Err(error) => {
                    self.support_record(
                        url,
                        SupportDocumentKind::Sitemap,
                        self.failure_status(error),
                    );
                    continue;
                }
            };
            if fetched.status != 200 {
                self.support_record(
                    url,
                    SupportDocumentKind::Sitemap,
                    SourceStatus::Failed(SourceFailure::HttpStatus(fetched.status)),
                );
                continue;
            }
            let remaining = u64::from(self.policy().map.limits.max_total_response_bytes.get())
                .saturating_sub(self.summary.response_bytes);
            let already_charged = fetched
                .raw_response
                .as_ref()
                .map_or(0, |bytes| u64::try_from(bytes.len()).unwrap_or(u64::MAX));
            let parse_cap = remaining
                .saturating_add(already_charged)
                .min(u64::from(self.policy().map.limits.max_response_bytes.get()));
            let parsed = fetched
                .document
                .as_ref()
                .map(Document::bytes)
                .or(fetched.raw_response.as_deref())
                .ok_or(SourceFailure::IncompleteDocument)
                .and_then(|bytes| {
                    sources::parse_sitemap(
                        bytes,
                        usize::try_from(self.policy().map.limits.max_parser_entries.get())
                            .unwrap_or(usize::MAX),
                        usize::try_from(if fetched.raw_response.is_some() {
                            parse_cap
                        } else {
                            u64::from(self.policy().map.limits.max_response_bytes.get())
                        })
                        .unwrap_or(usize::MAX),
                    )
                    .map_err(|error| {
                        if matches!(error, sources::ParseError::ByteLimitExceeded { .. }) {
                            let additional = parse_cap.saturating_sub(already_charged);
                            self.summary.response_bytes =
                                self.summary.response_bytes.saturating_add(additional);
                            if let Some(trace) = self.request_trace.last_mut() {
                                trace.charged_response_bytes =
                                    trace.charged_response_bytes.saturating_add(additional);
                            }
                            self.stop(
                                if parse_cap
                                    < u64::from(self.policy().map.limits.max_response_bytes.get())
                                {
                                    LimitReached::TotalResponseBytes
                                } else {
                                    LimitReached::ResponseBytes
                                },
                            );
                        }
                        SourceFailure::Parse
                    })
                });
            let sitemap = match parsed {
                Ok(sitemap) => sitemap,
                Err(error) => {
                    let html = fetched
                        .document
                        .as_ref()
                        .is_some_and(|document| document.class() == DocumentClass::SourceHtml);
                    let status = if html && self.termination.is_none() {
                        if optional {
                            SourceStatus::Skipped(SourceSkipReason::NotSitemap)
                        } else {
                            SourceStatus::Failed(SourceFailure::UnexpectedSitemapContent)
                        }
                    } else {
                        self.failure_status(error)
                    };
                    self.support_record(url, SupportDocumentKind::Sitemap, status);
                    continue;
                }
            };
            if fetched.raw_response.is_some() {
                let additional = u64::try_from(sitemap.decoded_bytes)
                    .unwrap_or(u64::MAX)
                    .saturating_sub(already_charged);
                self.summary.response_bytes =
                    self.summary.response_bytes.saturating_add(additional);
                if let Some(trace) = self.request_trace.last_mut() {
                    trace.charged_response_bytes =
                        trace.charged_response_bytes.saturating_add(additional);
                }
            }
            let kind = if sitemap.kind == SitemapKind::Index {
                SupportDocumentKind::SitemapIndex
            } else {
                SupportDocumentKind::Sitemap
            };
            self.support_record(
                url.clone(),
                kind,
                if sitemap.truncated {
                    SourceStatus::Truncated
                } else {
                    SourceStatus::Completed
                },
            );
            if sitemap.truncated {
                self.stop(LimitReached::ParserEntries);
            }
            for location in sitemap.locations {
                if kind == SupportDocumentKind::SitemapIndex {
                    if depth >= self.policy().map.limits.max_sitemap_depth {
                        self.omit_reason(OmissionReason::SitemapDepth);
                        continue;
                    }
                    if pending.len().saturating_add(self.queue.len())
                        >= usize::try_from(self.policy().map.limits.max_pending.get())
                            .unwrap_or(usize::MAX)
                    {
                        self.stop(LimitReached::Pending);
                        break;
                    }
                    let location = match normalize(
                        &location,
                        Some(&fetched.url),
                        self.policy().map.limits.max_url_bytes.get(),
                    ) {
                        Ok(value) => value.to_string(),
                        Err(reason) => {
                            self.reject(reason);
                            continue;
                        }
                    };
                    if !self.charge(location.len().saturating_add(64)) {
                        break;
                    }
                    pending.push_back((location, depth.saturating_add(1), false));
                } else {
                    match normalize(
                        &location,
                        Some(&fetched.url),
                        self.policy().map.limits.max_url_bytes.get(),
                    ) {
                        Ok(page) => {
                            self.page(page, None, DiscoverySource::Sitemap, Some(&url));
                        }
                        Err(reason) => self.reject(reason),
                    }
                }
                if self.termination.is_some() {
                    break;
                }
            }
        }
        let unfinished = pending.len().saturating_add(declarations.count());
        if unfinished > 0 {
            self.summary.omitted = self
                .summary
                .omitted
                .saturating_add(u64::try_from(unfinished).unwrap_or(u64::MAX));
            self.source_outcomes.push(SourceOutcome {
                source: DiscoverySource::Sitemap,
                source_url: None,
                status: SourceStatus::NotStarted,
            });
        }
    }

    async fn explore(&mut self, task: PageTask) {
        if task.probe && self.reuse_completed_probe(&task.url, task.depth) {
            return;
        }
        let url = task.url;
        if !self.redirects.contains_key(&url)
            && let Some(links) = self.cache.get(&url).cloned()
        {
            self.expand(&url, task.depth, links.urls, links.source);
            return;
        }
        if !task.probe
            && !self.redirects.contains_key(&url)
            && self
                .pages
                .get(&url)
                .is_some_and(|page| page.exploration != Exploration::Pending)
        {
            return;
        }
        self.ensure_origin(&url).await;
        if !self.active() {
            return;
        }
        if !self.allowed(&url) {
            self.probes.remove(&url);
            self.omit_reason(OmissionReason::Robots);
            if let Some(page) = self.pages.get_mut(&url) {
                page.exploration = Exploration::Skipped(SkipReason::Robots);
            }
            return;
        }
        let fetched = match self.fetch(&url, Purpose::Page { depth: task.depth }).await {
            Ok(FetchResult::Acquired(fetched)) => *fetched,
            Ok(FetchResult::Reused {
                url: final_url,
                exploration,
                aliases,
            }) => {
                self.probes.remove(&url);
                if task.probe {
                    self.page(
                        url.clone(),
                        Some(task.depth),
                        DiscoverySource::PassiveCertificate,
                        None,
                    );
                }
                self.page(
                    final_url.clone(),
                    Some(task.depth),
                    DiscoverySource::Redirect,
                    Some(&url),
                );
                self.mark_aliases(&aliases, &exploration);
                for page_url in [&url, &final_url] {
                    if let Some(page) = self.pages.get_mut(page_url) {
                        page.exploration = exploration.clone();
                    }
                }
                if let Some(links) = self.cache.get(&final_url).cloned() {
                    self.expand(&final_url, task.depth, links.urls, links.source);
                }
                return;
            }
            Err(error) => {
                if self.termination.is_none() {
                    self.probes.remove(&url);
                    if let Some(page) = self.pages.get_mut(&url) {
                        page.exploration = Exploration::Failed(error.clone());
                    }
                    self.source_outcomes.push(SourceOutcome {
                        source: DiscoverySource::HtmlLink,
                        source_url: Some(url),
                        status: SourceStatus::Failed(error),
                    });
                }
                return;
            }
        };
        self.probes.remove(&url);
        if task.probe {
            self.page(
                url.clone(),
                Some(task.depth),
                DiscoverySource::PassiveCertificate,
                None,
            );
        }
        if fetched.url != url {
            self.page(
                fetched.url.clone(),
                Some(task.depth),
                DiscoverySource::Redirect,
                Some(&url),
            );
        }
        if let Some(host) = fetched
            .url
            .host_str()
            .and_then(|host| self.hosts.get_mut(host))
        {
            host.verification = HostVerification::HttpObserved;
        }
        let state = if !(200..300).contains(&fetched.status) {
            Exploration::Failed(SourceFailure::HttpStatus(fetched.status))
        } else if fetched.document.as_ref().is_none_or(|doc| {
            !matches!(
                doc.class(),
                DocumentClass::SourceHtml | DocumentClass::SourceXml
            )
        }) {
            Exploration::Skipped(SkipReason::NonHtml)
        } else {
            Exploration::Inspected
        };
        if let Some(page) = self.pages.get_mut(&url) {
            page.exploration = state.clone();
        }
        if let Some(page) = self.pages.get_mut(&fetched.url) {
            page.exploration = state.clone();
        }
        if state == Exploration::Inspected
            && let Some(document) = &fetched.document
        {
            self.discover_document(document, &fetched.url, &url, task.depth);
        }
        let final_state = self
            .pages
            .get(&fetched.url)
            .map_or(state, |page| page.exploration.clone());
        self.mark_aliases(&fetched.aliases, &final_state);
        if self.policy().map.documents == DiscoveryDocuments::RetainWithinBudget {
            let bytes = fetched
                .document
                .as_ref()
                .map_or(0, Document::byte_len)
                .saturating_add(
                    fetched
                        .raw_response
                        .as_ref()
                        .map_or(0, |bytes| u64::try_from(bytes.len()).unwrap_or(u64::MAX)),
                );
            let next = self.summary.retained_document_bytes.saturating_add(bytes);
            if next <= u64::from(self.policy().map.limits.max_retained_document_bytes.get())
                && self.charge(128)
            {
                self.summary.retained_document_bytes = next;
                self.captures.push(RetainedCapture {
                    url: fetched.url,
                    response: fetched.response,
                });
            } else {
                self.omit();
                self.source_outcomes.push(SourceOutcome {
                    source: DiscoverySource::HtmlLink,
                    source_url: Some(fetched.url),
                    status: SourceStatus::Failed(SourceFailure::RetentionLimit),
                });
            }
        }
    }

    fn links(&mut self, document: &Document, url: &Url) -> Result<Vec<Url>, SourceFailure> {
        let plan = Plan::new([
            output(
                "canonical",
                css("link[rel][href]")
                    .map_err(|_| SourceFailure::Parse)?
                    .attribute("href")
                    .map_err(|_| SourceFailure::Parse)?,
            )
            .map_err(|_| SourceFailure::Parse)?,
            output(
                "link_rel",
                css("link[rel][href]")
                    .map_err(|_| SourceFailure::Parse)?
                    .attribute("rel")
                    .map_err(|_| SourceFailure::Parse)?,
            )
            .map_err(|_| SourceFailure::Parse)?,
            output(
                "base",
                css("base[href]")
                    .map_err(|_| SourceFailure::Parse)?
                    .attribute("href")
                    .map_err(|_| SourceFailure::Parse)?,
            )
            .map_err(|_| SourceFailure::Parse)?,
            output(
                "links",
                css("a[href],area[href]")
                    .map_err(|_| SourceFailure::Parse)?
                    .attribute("href")
                    .map_err(|_| SourceFailure::Parse)?,
            )
            .map_err(|_| SourceFailure::Parse)?,
        ])
        .map_err(|_| SourceFailure::Parse)?;
        let result = match document.bind(self.policy()).locate(&plan) {
            LocateOutcome::Matched { result } => result,
            LocateOutcome::NoMatch { .. } => return Ok(Vec::new()),
            _ => return Err(SourceFailure::Parse),
        };
        let mut base = url.clone();
        for finding in result.findings() {
            if finding.output_id().as_str() == "base"
                && let ProjectedValue::Attribute { value, .. } = finding.value()
                && let Ok(value) = normalize(
                    value,
                    Some(url),
                    self.policy().map.limits.max_url_bytes.get(),
                )
            {
                base = value;
                break;
            }
        }
        let canonical_nodes: HashSet<_> = result
            .findings()
            .iter()
            .filter(|finding| finding.output_id().as_str() == "link_rel")
            .filter(|finding| {
                matches!(finding.value(), ProjectedValue::Attribute { value, .. }
                    if value.split_ascii_whitespace().any(|token| token.eq_ignore_ascii_case("canonical")))
            })
            .map(Finding::coordinate)
            .collect();
        for finding in result
            .findings()
            .iter()
            .filter(|finding| finding.output_id().as_str() == "canonical")
            .filter(|finding| canonical_nodes.contains(finding.coordinate()))
        {
            if let ProjectedValue::Attribute { value, .. } = finding.value() {
                match normalize(
                    value,
                    Some(&base),
                    self.policy().map.limits.max_url_bytes.get(),
                ) {
                    Ok(target) => self.edge(url, &target, RelationshipKind::Canonical),
                    Err(reason) => self.reject(reason),
                }
            }
        }
        let mut links = BTreeSet::new();
        for finding in result
            .findings()
            .iter()
            .filter(|finding| finding.output_id().as_str() == "links")
        {
            if links.len()
                >= usize::try_from(self.policy().map.limits.max_parser_entries.get())
                    .unwrap_or(usize::MAX)
            {
                self.stop(LimitReached::ParserEntries);
                break;
            }
            if let ProjectedValue::Attribute { value, .. } = finding.value() {
                match normalize(
                    value,
                    Some(&base),
                    self.policy().map.limits.max_url_bytes.get(),
                ) {
                    Ok(url) => match self.scope.admit(&url) {
                        Ok(()) => {
                            links.insert(url);
                        }
                        Err(reason) => self.reject(reason),
                    },
                    Err(reason) => self.reject(reason),
                }
            }
        }
        Ok(links.into_iter().collect())
    }
    fn expand(&mut self, from: &Url, depth: u16, links: Vec<Url>, source: DiscoverySource) {
        for url in links {
            let Some(next) = depth.checked_add(1) else {
                self.omit();
                continue;
            };
            self.page(url.clone(), Some(next), source, Some(from));
            self.edge(from, &url, RelationshipKind::Link);
            if self.termination.is_some()
                && self.termination != Some(MapTermination::Limit(LimitReached::Pending))
            {
                break;
            }
        }
    }
    fn finish(mut self) -> MapOutcome {
        let pages: Vec<_> = mem::take(&mut self.pages).into_values().collect();
        let edges: Vec<_> = mem::take(&mut self.edges).into_iter().collect();
        let candidates = pages
            .iter()
            .filter_map(|page| match page.exploration {
                Exploration::Pending => Some(FrontierEntry {
                    page: page.url.clone(),
                    reason: PendingReason::OperationStopped,
                }),
                Exploration::Skipped(SkipReason::Depth) => Some(FrontierEntry {
                    page: page.url.clone(),
                    reason: PendingReason::DepthBoundary,
                }),
                _ => None,
            })
            .chain(self.probes.iter().map(|page| FrontierEntry {
                page: page.clone(),
                reason: PendingReason::ProbeCandidate,
            }))
            .collect::<Vec<_>>();
        let mut frontier = Vec::new();
        for entry in candidates {
            if frontier.len()
                >= usize::try_from(self.policy().map.limits.max_pending.get()).unwrap_or(usize::MAX)
            {
                self.omit();
                self.stop(LimitReached::Pending);
                continue;
            }
            if self.charge(entry.page.as_str().len().saturating_add(64)) {
                frontier.push(entry);
            } else {
                self.omit();
            }
        }
        let mut tree = yosoi_map::tree(&pages, &edges);
        let tree_bytes = tree.iter().fold(0_usize, |total, entry| {
            total
                .saturating_add(entry.page.as_str().len())
                .saturating_add(entry.parent.as_ref().map_or(0, |url| url.as_str().len()))
                .saturating_add(96)
        });
        if !self.charge(tree_bytes) {
            self.summary.omitted = self
                .summary
                .omitted
                .saturating_add(u64::try_from(tree.len()).unwrap_or(u64::MAX));
            tree.clear();
        }
        if self.policy().map.pages == PageDiscovery::Disabled {
            self.source_outcomes.extend(
                [DiscoverySource::Robots, DiscoverySource::Sitemap]
                    .into_iter()
                    .map(|source| SourceOutcome {
                        source,
                        source_url: None,
                        status: SourceStatus::Disabled,
                    }),
            );
        } else if self.robots.is_empty() {
            self.source_outcomes.extend(
                [DiscoverySource::Robots, DiscoverySource::Sitemap]
                    .into_iter()
                    .map(|source| SourceOutcome {
                        source,
                        source_url: None,
                        status: SourceStatus::NotStarted,
                    }),
            );
        }
        MapOutcome {
            snapshot: self.snapshot,
            hosts: self.hosts.into_values().collect(),
            pages,
            relationships: edges,
            frontier,
            support_documents: self.support,
            sources: self.source_outcomes,
            tree,
            captures: self.captures,
            wildcard_names: self.wildcard_names,
            wildcard_entries: self
                .wildcard_entries
                .into_iter()
                .map(|(pattern, observations)| WildcardEntry {
                    pattern,
                    observations,
                })
                .collect(),
            termination: self.termination.unwrap_or(MapTermination::Exhausted),
            summary: self.summary,
            request_trace: self.request_trace,
            omissions: self
                .omissions
                .into_iter()
                .map(|(reason, count)| Omission { reason, count })
                .collect(),
        }
    }
}
