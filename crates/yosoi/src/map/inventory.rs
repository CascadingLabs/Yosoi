use super::{
    DiscoverySource, Exploration, HostEntry, HostVerification, LimitReached, MapTermination,
    Observation, OmissionReason, PageEntry, PageTask, Policy, Rejection, Relationship,
    RelationshipKind, Runner, SkipReason, SourceFailure, SourceStatus,
};
use tokio::time::Instant;
use url::Url;

impl Runner<'_> {
    pub(super) fn policy(&self) -> &Policy {
        self.snapshot.policy()
    }
    pub(super) const fn failure_status(&self, error: SourceFailure) -> SourceStatus {
        if self.termination.is_some() {
            SourceStatus::Truncated
        } else {
            SourceStatus::Failed(error)
        }
    }
    pub(super) fn stop(&mut self, limit: LimitReached) {
        self.termination.get_or_insert(MapTermination::Limit(limit));
    }
    pub(super) fn active(&mut self) -> bool {
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
    pub(super) fn omit_reason(&mut self, reason: OmissionReason) {
        self.summary.omitted = self.summary.omitted.saturating_add(1);
        let count = self.omissions.entry(reason).or_default();
        *count = count.saturating_add(1);
    }
    pub(super) fn omit(&mut self) {
        self.omit_reason(OmissionReason::Other);
    }
    pub(super) fn reject(&mut self, reason: Rejection) {
        self.omit_reason(OmissionReason::Admission(reason));
    }
    pub(super) fn charge(&mut self, bytes: usize) -> bool {
        let count = u64::try_from(bytes).unwrap_or(u64::MAX);
        let next = self.summary.inventory_bytes.saturating_add(count);
        if next > u64::from(self.policy().map.limits.max_inventory_bytes.get()) {
            self.stop(LimitReached::InventoryBytes);
            return false;
        }
        self.summary.inventory_bytes = next;
        true
    }
    pub(super) fn observation(
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
    pub(super) fn host(
        &mut self,
        url: &Url,
        source: DiscoverySource,
        source_url: Option<&Url>,
    ) -> bool {
        let Some(host) = url.host_str() else {
            self.omit();
            return false;
        };
        self.host_name(host, source, source_url)
    }
    pub(super) fn host_name(
        &mut self,
        host: &str,
        source: DiscoverySource,
        source_url: Option<&Url>,
    ) -> bool {
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
    pub(super) fn wildcard(&mut self, value: &str, source_url: &Url, source: DiscoverySource) {
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
    pub(super) fn page(
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
    pub(super) fn edge(&mut self, from: &Url, to: &Url, kind: RelationshipKind) {
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
}
