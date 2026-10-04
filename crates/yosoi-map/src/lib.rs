//! Pure, bounded discovery vocabulary and native parsers for Yosoi Map.
//! Acquisition is owned by the public `yosoi::map` Requests composition.

pub mod admission;
pub mod providers;
pub mod sources;

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use url::Url;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum DiscoverySource {
    Seed,
    HtmlLink,
    XmlLink,
    PassiveProvider(providers::PublicProvider),
    Sitemap,
    Robots,
    Redirect,
    PassiveCertificate,
}

impl DiscoverySource {
    pub const fn is_passive(self) -> bool {
        matches!(self, Self::PassiveCertificate | Self::PassiveProvider(_))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct Observation {
    pub source: DiscoverySource,
    pub source_url: Option<Url>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SkipReason {
    Depth,
    Robots,
    NonHtml,
    Budget,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SourceFailure {
    Transport,
    HttpStatus(u16),
    Parse,
    IncompleteDocument,
    RedirectRejected,
    RedirectLimit,
    RetentionLimit,
    RequestDeadline,
    RateLimited,
    UnexpectedSitemapContent,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Exploration {
    Inventoried,
    Pending,
    Inspected,
    Skipped(SkipReason),
    Failed(SourceFailure),
}

#[derive(Clone, Debug)]
pub struct PageEntry {
    pub url: Url,
    pub minimum_link_depth: Option<u16>,
    pub observations: Vec<Observation>,
    pub exploration: Exploration,
}

impl PageEntry {
    pub const fn url(&self) -> &Url {
        &self.url
    }
    pub const fn exploration(&self) -> &Exploration {
        &self.exploration
    }
}

#[derive(Clone, Debug)]
pub struct WildcardEntry {
    pub pattern: String,
    pub observations: Vec<Observation>,
}

#[derive(Clone, Debug)]
pub struct HostEntry {
    pub host: String,
    pub observations: Vec<Observation>,
    pub verification: HostVerification,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HostVerification {
    Unverified,
    HttpObserved,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum RelationshipKind {
    Link,
    Redirect,
    Canonical,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct Relationship {
    pub from: Url,
    pub to: Url,
    pub kind: RelationshipKind,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PendingReason {
    AwaitingExploration,
    DepthBoundary,
    OperationStopped,
    ProbeCandidate,
}

#[derive(Clone, Debug)]
pub struct FrontierEntry {
    pub page: Url,
    pub reason: PendingReason,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SupportDocumentKind {
    Robots,
    Sitemap,
    SitemapIndex,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SourceSkipReason {
    NotSitemap,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SourceStatus {
    Completed,
    Sampled,
    Skipped(SourceSkipReason),
    Disabled,
    Failed(SourceFailure),
    Truncated,
    NotStarted,
}

#[derive(Clone, Debug)]
pub struct SourceOutcome {
    pub source: DiscoverySource,
    pub source_url: Option<Url>,
    pub status: SourceStatus,
}

#[derive(Clone, Debug)]
pub struct SupportDocument {
    pub url: Url,
    pub kind: SupportDocumentKind,
    pub status: SourceStatus,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LimitReached {
    Hosts,
    Urls,
    Relationships,
    Observations,
    Pending,
    Requests,
    Sitemaps,
    SitemapDepth,
    ResponseBytes,
    TotalResponseBytes,
    InventoryBytes,
    ParserEntries,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MapTermination {
    Exhausted,
    Limit(LimitReached),
    Deadline,
    Cancelled,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum OmissionReason {
    Admission(admission::Rejection),
    Robots,
    Depth,
    SitemapDepth,
    Pending,
    Inventory,
    Retention,
    Wildcard,
    Other,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Omission {
    pub reason: OmissionReason,
    pub count: u64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Summary {
    pub requests: u32,
    pub provider_concurrency_peak: u32,
    pub page_concurrency_peak: u32,
    pub unused_page_prefetches: u32,
    pub response_bytes: u64,
    pub inventory_bytes: u64,
    pub observations: u32,
    pub omitted: u64,
    pub retained_document_bytes: u64,
}

#[derive(Clone, Debug)]
pub struct TreeEntry {
    pub page: Url,
    pub parent: Option<Url>,
    pub depth: Option<u16>,
}

/// Deterministic spanning forest; unattached observations retain unknown depth.
pub fn tree(pages: &[PageEntry], edges: &[Relationship]) -> Vec<TreeEntry> {
    let mut parents: BTreeMap<Url, (Option<Url>, Option<u16>)> = pages
        .iter()
        .map(|page| (page.url.clone(), (None, None)))
        .collect();
    let mut queue = VecDeque::new();
    let roots = pages
        .iter()
        .filter(|page| {
            page.minimum_link_depth == Some(0)
                && page.observations.iter().any(|observation| {
                    observation.source == DiscoverySource::Seed || observation.source.is_passive()
                })
        })
        .map(|page| page.url.clone())
        .collect::<BTreeSet<_>>();
    for root in roots {
        parents.insert(root.clone(), (None, Some(0)));
        queue.push_back((root, 0_u16));
    }
    let mut sorted = edges.to_vec();
    sorted.sort();
    while let Some((parent, depth)) = queue.pop_front() {
        if parents
            .get(&parent)
            .is_none_or(|entry| entry.1 != Some(depth))
        {
            continue;
        }
        for edge in sorted
            .iter()
            .filter(|edge| edge.from == parent && edge.kind != RelationshipKind::Canonical)
        {
            let next = if edge.kind == RelationshipKind::Redirect {
                Some(depth)
            } else {
                depth.checked_add(1)
            };
            if let (Some(next_depth), Some(entry)) = (next, parents.get_mut(&edge.to))
                && entry.1.is_none_or(|previous| next_depth < previous)
            {
                *entry = (Some(parent.clone()), Some(next_depth));
                if edge.kind == RelationshipKind::Redirect {
                    queue.push_front((edge.to.clone(), next_depth));
                } else {
                    queue.push_back((edge.to.clone(), next_depth));
                }
            }
        }
    }
    parents
        .into_iter()
        .map(|(page, (parent, depth))| TreeEntry {
            page,
            parent,
            depth,
        })
        .collect()
}
