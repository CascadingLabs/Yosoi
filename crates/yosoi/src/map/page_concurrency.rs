//! Bounded frontier batches: overlap acquisition, commit in frontier order.
use super::{
    Exploration, MapTermination, OmissionReason, PageTask, Runner, SkipReason, SourceFailure,
    acquisition,
};
use std::collections::{BTreeMap, BTreeSet};
use tokio::{task::JoinSet, time::sleep_until};

impl Runner<'_> {
    pub(super) async fn explore_pages(&mut self) {
        while self.active() {
            let (tasks, requests) = self.page_batch().await;
            if tasks.is_empty() {
                break;
            }
            let token = self.cancellation.child_token();
            let mut running = JoinSet::new();
            let mut admitted = BTreeMap::new();
            for work in requests {
                let index = work.ordinal;
                let executor = self.executor.clone();
                let cancellation = token.child_token();
                let deadline = self.deadline;
                let task_work = work.clone();
                admitted.insert(index, work);
                // Own a bounded request Policy in each task. Inventory stays with the coordinator.
                running.spawn(async move {
                    (
                        index,
                        acquisition::execute(&task_work, &executor, &cancellation, deadline).await,
                    )
                });
            }
            self.summary.page_concurrency_peak = self
                .summary
                .page_concurrency_peak
                .max(u32::try_from(running.len()).unwrap_or(u32::MAX));
            let mut finished = BTreeMap::new();
            let mut stopped = false;
            while !running.is_empty() {
                let joined = if stopped {
                    running.join_next().await
                } else {
                    tokio::select! {
                        joined = running.join_next() => joined,
                        () = self.cancellation.cancelled() => { self.termination = Some(MapTermination::Cancelled); token.cancel(); stopped = true; continue; },
                        () = sleep_until(self.deadline) => { self.termination = Some(MapTermination::Deadline); token.cancel(); stopped = true; continue; },
                    }
                };
                match joined {
                    Some(Ok((index, result))) => {
                        finished.insert(index, result);
                    }
                    Some(Err(_)) => {
                        token.cancel();
                        stopped = true;
                    }
                    None => break,
                }
            }
            for (index, work) in admitted {
                let result = finished
                    .remove(&index)
                    .unwrap_or(Err(SourceFailure::Transport));
                self.account_request(&work, &result);
                self.ready_responses
                    .insert(work.url.clone(), (work, result));
            }
            for task in tasks {
                if !self.active() {
                    break;
                }
                if self
                    .pages
                    .get(&task.url)
                    .is_some_and(|page| page.minimum_link_depth != Some(task.depth))
                    && !task.probe
                {
                    continue;
                }
                self.explore(task).await;
            }
            // Every admitted response has been charged, even if a bound prevents inspection.
            self.summary.unused_page_prefetches = self
                .summary
                .unused_page_prefetches
                .saturating_add(u32::try_from(self.ready_responses.len()).unwrap_or(u32::MAX));
            self.ready_responses.clear();
        }
    }

    async fn page_batch(&mut self) -> (Vec<PageTask>, Vec<acquisition::PreparedRequest>) {
        let maximum = usize::try_from(
            self.policy()
                .map
                .limits
                .max_concurrency
                .get()
                .min(self.policy().map.limits.max_pending.get()),
        )
        .unwrap_or(1);
        let mut tasks = Vec::new();
        let mut requests = Vec::new();
        let mut urls = BTreeSet::new();
        while self.active() && requests.len() < maximum {
            let Some(front) = self.queue.front() else {
                break;
            };
            // Finish a batch before new-origin metadata or cache expansion can consume its reservations.
            if !requests.is_empty()
                && ((self.cache.contains_key(&front.url)
                    || self.redirects.contains_key(&front.url))
                    || !self
                        .robots
                        .contains_key(&front.url.origin().ascii_serialization())
                    || self.completed_page_state(&front.url).is_some()
                    || self.summary.requests >= self.policy().map.limits.max_requests.get()
                    || u64::from(self.policy().map.limits.max_total_response_bytes.get())
                        .saturating_sub(self.summary.response_bytes)
                        .saturating_sub(self.reserved_response_bytes)
                        < u64::from(self.policy().map.limits.max_response_bytes.get())
                    || self.summary.inventory_bytes.saturating_add(
                        u64::try_from(front.url.as_str().len().saturating_add(96))
                            .unwrap_or(u64::MAX),
                    ) > u64::from(self.policy().map.limits.max_inventory_bytes.get()))
            {
                break;
            }
            let Some(task) = self.queue.pop_front() else {
                break;
            };
            if self
                .pages
                .get(&task.url)
                .is_some_and(|page| page.minimum_link_depth != Some(task.depth))
                && !task.probe
            {
                continue;
            }
            if self.redirects.contains_key(&task.url) {
                self.explore(task).await;
                continue;
            }
            if let Some(links) = self.cache.get(&task.url).cloned() {
                self.expand(&task.url, task.depth, links.urls, links.source);
                continue;
            }
            if !urls.insert(task.url.clone()) {
                continue;
            }
            if task.probe && self.reuse_completed_probe(&task.url, task.depth) {
                continue;
            }
            if !task.probe && self.completed_page_state(&task.url).is_some() {
                continue;
            }
            self.ensure_origin(&task.url).await;
            if !self.active() {
                break;
            }
            if !self.allowed(&task.url) {
                self.probes.remove(&task.url);
                self.omit_reason(OmissionReason::Robots);
                if let Some(page) = self.pages.get_mut(&task.url) {
                    page.exploration = Exploration::Skipped(SkipReason::Robots);
                }
                continue;
            }
            match self.prepare_request(&task.url) {
                Ok(work) => {
                    requests.push(work);
                    tasks.push(task);
                }
                Err(error) => {
                    if self.termination.is_some() {
                        break;
                    }
                    self.probes.remove(&task.url);
                    if let Some(page) = self.pages.get_mut(&task.url) {
                        page.exploration = Exploration::Failed(error.clone());
                    }
                    self.source_outcomes.push(super::SourceOutcome {
                        source: super::DiscoverySource::HtmlLink,
                        source_url: Some(task.url),
                        status: super::SourceStatus::Failed(error),
                    });
                }
            }
        }
        (tasks, requests)
    }
    pub(super) fn completed_page_state(&self, url: &url::Url) -> Option<Exploration> {
        if self.cache.contains_key(url) {
            return Some(Exploration::Inspected);
        }
        self.pages
            .get(url)
            .and_then(|page| match &page.exploration {
                Exploration::Inspected
                | Exploration::Failed(_)
                | Exploration::Skipped(SkipReason::NonHtml | SkipReason::Robots) => {
                    Some(page.exploration.clone())
                }
                _ => None,
            })
    }

    pub(super) fn reuse_completed_probe(&mut self, url: &url::Url, depth: u16) -> bool {
        if self.redirects.contains_key(url) {
            return false;
        }
        let Some(exploration) = self.completed_page_state(url) else {
            return false;
        };
        self.probes.remove(url);
        self.page(
            url.clone(),
            Some(depth),
            super::DiscoverySource::PassiveCertificate,
            None,
        );
        if let Some(page) = self.pages.get_mut(url) {
            page.exploration = exploration;
        }
        if let Some(links) = self.cache.get(url).cloned() {
            self.expand(url, depth, links.urls, links.source);
        }
        true
    }
}
