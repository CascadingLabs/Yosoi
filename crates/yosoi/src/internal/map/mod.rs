//! Pure, bounded discovery vocabulary and native parsers for Yosoi Map.
//! Acquisition is owned by the public `yosoi::map` Requests composition.

pub mod admission;
pub mod providers;
pub mod sources;

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use serde::Serialize;
use url::Url;

/// Provenance category explaining how a hostname or page entered the inventory.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum DiscoverySource {
    /// The caller's authored seed, rather than an inferred discovery.
    Seed,
    /// A link extracted from an acquired HTML page.
    HtmlLink,
    /// A link extracted from an acquired XML document.
    XmlLink,
    /// A name reported by the specified anonymous historical discovery index.
    PassiveProvider(providers::PublicProvider),
    /// A page or nested support document named by a sitemap.
    Sitemap,
    /// Discovery through an acquired robots document.
    Robots,
    /// A destination observed while handling an HTTP redirect.
    Redirect,
    /// A name reported by certificate evidence, without an HTTP reachability claim.
    PassiveCertificate,
}

impl DiscoverySource {
    /// Returns whether this category uses passive index evidence rather than page exploration.
    pub const fn is_passive(self) -> bool {
        matches!(self, Self::PassiveCertificate | Self::PassiveProvider(_))
    }
}

/// One retained provenance observation; passive evidence does not verify reachability.
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize)]
pub struct Observation {
    /// Mechanism that reported the name or page.
    pub source: DiscoverySource,
    /// Reporting page or index endpoint, absent when no source URL applies.
    pub source_url: Option<Url>,
}

/// Policy or budget reason an inventoried page was not explored.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SkipReason {
    /// The known link depth exceeds the declared exploration boundary.
    Depth,
    /// Applicable robots rules disallow exploration.
    Robots,
    /// Acquired content is not an HTML page suitable for link exploration.
    NonHtml,
    /// A resource budget prevented further exploration.
    Budget,
}

/// Acquisition or parsing failure for one discovery source, without response excerpts.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum SourceFailure {
    /// The acquisition transport did not yield a usable response.
    Transport,
    /// The response carried the supplied unsuccessful HTTP status.
    HttpStatus(u16),
    /// The acquired source could not be parsed into supported discovery evidence.
    Parse,
    /// Acquired document evidence was incomplete for the required parser.
    IncompleteDocument,
    /// A redirect destination failed scope or URL admission checks.
    RedirectRejected,
    /// The configured redirect-hop limit prevented following another destination.
    RedirectLimit,
    /// Capture retention could not satisfy the configured resource limits.
    RetentionLimit,
    /// The individual acquisition exceeded its request deadline.
    RequestDeadline,
    /// The discovery provider reported rate limiting.
    RateLimited,
    /// A source expected to contain sitemap XML returned other content.
    UnexpectedSitemapContent,
}

/// Exploration state of one retained page, independent of how it was discovered.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum Exploration {
    /// The page is retained as evidence but has not been scheduled for exploration.
    Inventoried,
    /// The page remains queued for exploration within the current operation.
    Pending,
    /// Acquisition and supported page inspection completed; this is not whole-site completeness.
    Inspected,
    /// Exploration was omitted for the supplied policy or budget reason.
    Skipped(SkipReason),
    /// Exploration started or was attempted but ended with the supplied source failure.
    Failed(SourceFailure),
}

/// A normalized page and its retained discovery and exploration evidence.
#[derive(Clone, Debug, Serialize)]
pub struct PageEntry {
    /// Admitted normalized HTTP(S) page URL, with fragments removed.
    pub url: Url,
    /// Smallest known link depth; `None` means no rooted depth was established.
    pub minimum_link_depth: Option<u16>,
    /// Retained provenance observations, subject to observation and inventory budgets.
    pub observations: Vec<Observation>,
    /// Whether this page was only inventoried, inspected, skipped, failed, or remains pending.
    pub exploration: Exploration,
}

impl PageEntry {
    /// Borrows the normalized page URL without issuing a request.
    pub const fn url(&self) -> &Url {
        &self.url
    }
    /// Borrows retained exploration state; inventory presence alone does not imply inspection.
    pub const fn exploration(&self) -> &Exploration {
        &self.exploration
    }
}

/// A retained wildcard name pattern, not a concrete verified hostname.
#[derive(Clone, Debug, Serialize)]
pub struct WildcardEntry {
    /// Observed wildcard pattern; it is not expanded into guessed hosts.
    pub pattern: String,
    /// Sources reporting this pattern, subject to the configured evidence budgets.
    pub observations: Vec<Observation>,
}

/// An admitted hostname with provenance and an explicit reachability evidence state.
#[derive(Clone, Debug, Serialize)]
pub struct HostEntry {
    /// Canonical admitted hostname, without a scheme or path.
    pub host: String,
    /// Retained observations explaining why this host entered the inventory.
    pub observations: Vec<Observation>,
    /// Whether HTTP acquisition produced evidence for the host.
    pub verification: HostVerification,
}

/// Reachability evidence for a retained hostname; neither variant proves ownership.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HostVerification {
    /// The hostname was discovered without observed HTTP response evidence.
    Unverified,
    /// An HTTP response was observed; application success or future availability is not guaranteed.
    HttpObserved,
}

/// Kind of retained directed relationship between normalized pages.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RelationshipKind {
    /// An extracted hyperlink; traversing it increases rooted link depth.
    Link,
    /// An observed redirect, which preserves rooted link depth.
    Redirect,
    /// An extracted canonical hint; it does not create a traversal-tree parent.
    Canonical,
}

/// One directed relationship retained as discovery evidence, without merging its endpoints.
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize)]
pub struct Relationship {
    /// Page from which the relationship was observed.
    pub from: Url,
    /// Admitted normalized destination of the relationship.
    pub to: Url,
    /// Whether this is a hyperlink, redirect, or canonical hint.
    pub kind: RelationshipKind,
}

/// Reason a retained page remains in the returned frontier.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PendingReason {
    /// The operation exhausted its runnable work while this inventoried page awaited exploration.
    AwaitingExploration,
    /// The page lies beyond the configured rooted link-depth boundary.
    DepthBoundary,
    /// The operation stopped before queued exploration could complete.
    OperationStopped,
    /// The page is a probe candidate without ordinary rooted exploration evidence.
    ProbeCandidate,
}

/// Retained unfinished page work; frontier entries are not promises of later execution.
#[derive(Clone, Debug, Serialize)]
pub struct FrontierEntry {
    /// Normalized page URL for the unfinished work.
    pub page: Url,
    /// Why this page remains unfinished in the returned outcome.
    pub reason: PendingReason,
}

/// Parser role of an acquired support document rather than an ordinary page.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SupportDocumentKind {
    /// Robots rules and sitemap declarations for an origin.
    Robots,
    /// Sitemap listing concrete page URLs.
    Sitemap,
    /// Sitemap index listing child sitemap support documents.
    SitemapIndex,
}

/// Reason an acquired support source was intentionally not parsed as a sitemap.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceSkipReason {
    /// A probe returned content that was not classified as sitemap XML.
    NotSitemap,
}

/// Per-source terminal state, distinct from termination of the whole Map operation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum SourceStatus {
    /// Supported source processing finished within local limits; the source may not cover a whole site.
    Completed,
    /// The provider response is known or likely to be a sample of its index.
    Sampled,
    /// Processing was omitted for the supplied source-classification reason.
    Skipped(SourceSkipReason),
    /// Policy disabled this discovery source.
    Disabled,
    /// Acquisition or source interpretation ended with the supplied typed failure.
    Failed(SourceFailure),
    /// A local resource or stopping boundary prevented retaining or parsing all source evidence.
    Truncated,
    /// The source was retained in the outcome but no acquisition started for it.
    NotStarted,
}

/// Retained execution facts for one selected discovery source.
#[derive(Clone, Debug, Serialize)]
pub struct SourceOutcome {
    /// Discovery mechanism occupying this source slot.
    pub source: DiscoverySource,
    /// Source endpoint or page, absent when no URL applies.
    pub source_url: Option<Url>,
    /// Terminal source processing state, independent of overall operation exhaustion.
    pub status: SourceStatus,
}

/// A robots or sitemap support source and its retained execution state.
#[derive(Clone, Debug, Serialize)]
pub struct SupportDocument {
    /// Normalized support-document URL.
    pub url: Url,
    /// Parser role selected for this support source.
    pub kind: SupportDocumentKind,
    /// Processing state, including failures and incomplete evidence.
    pub status: SourceStatus,
}

/// Resource boundary that stopped Map discovery or retention.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LimitReached {
    /// Maximum retained hostname count was reached.
    Hosts,
    /// Maximum retained page URL count was reached.
    Urls,
    /// Maximum retained directed relationship count was reached.
    Relationships,
    /// Maximum retained provenance observation count was reached.
    Observations,
    /// Maximum pending frontier capacity was reached.
    Pending,
    /// Maximum acquisition request count was reached.
    Requests,
    /// Maximum processed sitemap count was reached.
    Sitemaps,
    /// Maximum nested sitemap traversal depth was reached.
    SitemapDepth,
    /// A single response exceeded the configured byte budget.
    ResponseBytes,
    /// Aggregate acquired response bytes exhausted the operation budget.
    TotalResponseBytes,
    /// Retained inventory evidence exhausted its byte budget.
    InventoryBytes,
    /// A source parser exhausted its configured entry budget.
    ParserEntries,
}

/// Why the Map operation stopped, independent of individual source success.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum MapTermination {
    /// No runnable work remains under the declared scope and policy.
    /// Sources can still be failed, sampled, disabled, or incomplete; this does
    /// not certify an exhaustive inventory of the site or public indexes.
    Exhausted,
    /// The named resource boundary prevented continuing discovery.
    Limit(LimitReached),
    /// The operation's shared discovery deadline expired.
    Deadline,
    /// Execution observed caller cancellation; retained discoveries and acquisition outcomes remain available.
    Cancelled,
}

/// Classification of discovery evidence omitted from retention or exploration.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum OmissionReason {
    /// URL or hostname admission rejected evidence for the supplied reason.
    Admission(admission::Rejection),
    /// Applicable robots rules excluded exploration.
    Robots,
    /// The rooted page exploration depth boundary excluded work.
    Depth,
    /// Nested sitemap depth excluded further traversal.
    SitemapDepth,
    /// Pending frontier capacity prevented queueing additional work.
    Pending,
    /// Inventory capacity prevented retaining additional evidence.
    Inventory,
    /// Source or capture retention limits omitted evidence.
    Retention,
    /// A wildcard was retained as a pattern rather than expanded into concrete hosts.
    Wildcard,
    /// Evidence was omitted for a reason outside the more specific classifications.
    Other,
}

/// Count of omission events in one category, not a count of all undiscovered site items.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct Omission {
    /// Boundary or rejection class responsible for the omitted evidence.
    pub reason: OmissionReason,
    /// Recorded omission-event count for this category.
    pub count: u64,
}

/// Recorded resource accounting and concurrency peaks for one Map operation.
#[derive(Clone, Copy, Debug, Default, Serialize)]
pub struct Summary {
    /// Charged acquisition request count, including discovery support sources.
    pub requests: u32,
    /// Greatest observed number of simultaneous public-provider acquisitions.
    pub provider_concurrency_peak: u32,
    /// Greatest observed number of simultaneous prefetched page acquisitions.
    pub page_concurrency_peak: u32,
    /// Charged speculative page attempts not consumed by the final exploration path.
    pub unused_page_prefetches: u32,
    /// Aggregate response bytes charged to the operation's acquisition budget.
    pub response_bytes: u64,
    /// Bytes charged for retained discovery inventory evidence.
    pub inventory_bytes: u64,
    /// Count of retained provenance observations.
    pub observations: u32,
    /// Aggregate recorded omission events; this does not quantify all undiscovered evidence.
    pub omitted: u64,
    /// Bytes of retained document payloads accounted separately from inventory metadata.
    pub retained_document_bytes: u64,
}

/// One page's position in the deterministic rooted discovery forest.
#[derive(Clone, Debug, Serialize)]
pub struct TreeEntry {
    /// Normalized page URL retained in the inventory.
    pub page: Url,
    /// Selected rooted predecessor, absent for roots and unattached observations.
    pub parent: Option<Url>,
    /// Shortest established rooted link depth, absent when no rooted path was found.
    pub depth: Option<u16>,
}

/// Deterministic spanning forest; unattached observations retain unknown depth.
///
/// Returns owned entries sorted by URL. Seed or passive-source pages at depth
/// zero are roots; hyperlinks add one to depth, redirects preserve depth, and
/// canonical hints do not establish parents. Edges are sorted before traversal
/// so equal-depth choices are deterministic. Only supplied pages are retained;
/// this pure calculation does not acquire pages or verify their availability.
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

#[cfg(test)]
mod integration_tests;
