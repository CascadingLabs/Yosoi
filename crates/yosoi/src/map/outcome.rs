use std::mem;

use super::{
    DiscoverySource, Exploration, FrontierEntry, LimitReached, MapOutcome, MapTermination,
    Omission, PendingReason, Runner, SkipReason, SourceOutcome, SourceStatus, WildcardEntry,
};
use yosoi_policy::policy::PageDiscovery;

impl Runner<'_> {
    pub(super) fn finish(mut self) -> MapOutcome {
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
