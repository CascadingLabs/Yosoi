//! Fixed public indexes executed concurrently through the existing Requests client.
use std::{collections::BTreeMap, sync::Arc};

use crate::internal::map::providers::{self, ProviderNames};
use crate::internal::policy::policy::{PageDiscovery, Subdomains};
use tokio::task::JoinSet;
use tokio::time::{Instant, sleep_until};
use url::Url;

use super::{
    DiscoverySource, LimitReached, MapTermination, PageTask, PublicProvider, Runner, SourceFailure,
    SourceOutcome, SourceStatus,
};

mod budget;
mod rate;
#[cfg(test)]
mod tests;
mod transport;

struct Job {
    provider: PublicProvider,
    url: Url,
}
struct ResultEntry {
    provider: PublicProvider,
    url: Url,
    result: Result<ProviderNames, transport::Failure>,
}

const fn source(provider: PublicProvider) -> DiscoverySource {
    match provider {
        PublicProvider::CrtSh => DiscoverySource::PassiveCertificate,
        other => DiscoverySource::PassiveProvider(other),
    }
}

impl Runner<'_> {
    pub(super) async fn passive(&mut self) {
        if self.policy().map.subdomains == Subdomains::Disabled {
            self.source_outcomes
                .extend(PublicProvider::all().iter().map(|&provider| SourceOutcome {
                    source: source(provider),
                    source_url: None,
                    status: SourceStatus::Disabled,
                }));
            return;
        }
        let Some(domain) = self.scope.domain().map(str::to_owned) else {
            self.source_outcomes
                .extend(PublicProvider::all().iter().map(|&provider| SourceOutcome {
                    source: source(provider),
                    source_url: None,
                    status: SourceStatus::NotStarted,
                }));
            return;
        };
        let mut jobs = Vec::new();
        for &provider in PublicProvider::all() {
            let Ok(url) = provider.endpoint(&domain) else {
                self.source_outcomes.push(SourceOutcome {
                    source: source(provider),
                    source_url: None,
                    status: SourceStatus::Failed(SourceFailure::Parse),
                });
                continue;
            };
            if !self.charge(url.as_str().len().saturating_add(128)) {
                self.source_outcomes.push(SourceOutcome {
                    source: source(provider),
                    source_url: None,
                    status: SourceStatus::NotStarted,
                });
                continue;
            }
            jobs.push(Job { provider, url });
        }
        self.collect_sources(jobs).await;
        self.source_outcomes.sort_by_key(|outcome| {
            PublicProvider::all()
                .iter()
                .position(|&provider| source(provider) == outcome.source)
                .unwrap_or(usize::MAX)
        });
    }

    async fn collect_sources(&mut self, jobs: Vec<Job>) {
        if !self.active() {
            self.source_outcomes
                .extend(jobs.into_iter().map(|job| SourceOutcome {
                    source: source(job.provider),
                    source_url: Some(job.url),
                    status: SourceStatus::NotStarted,
                }));
            return;
        }
        let policy = self.policy().clone();
        let limits = &policy.map.limits;
        let budget = budget::Budget::new(
            limits
                .max_requests
                .get()
                .saturating_sub(self.summary.requests),
            u64::from(limits.max_total_response_bytes.get())
                .saturating_sub(self.summary.response_bytes),
            u64::from(limits.max_response_bytes.get()),
            u64::from(limits.max_inventory_bytes.get())
                .saturating_sub(self.summary.inventory_bytes),
        );
        let token = self.cancellation.child_token();
        let concurrency =
            usize::try_from(limits.max_concurrency.get().min(limits.max_pending.get()))
                .unwrap_or(1);
        let entries = usize::try_from(limits.max_parser_entries.get()).unwrap_or(usize::MAX);
        let selected: BTreeMap<_, _> = jobs
            .iter()
            .enumerate()
            .map(|(index, job)| (index, (job.provider, job.url.clone())))
            .collect();
        let mut pending = jobs.into_iter().enumerate();
        let mut running = JoinSet::new();
        let mut results = BTreeMap::new();

        let mut stopped = false;
        let mut scheduled = 0_usize;
        loop {
            while !stopped && running.len() < concurrency {
                let Some((index, job)) = pending.next() else {
                    break;
                };
                let fetcher = transport::Transport {
                    policy: policy.clone(),
                    executor: self.executor.clone(),
                    budget: Arc::clone(&budget),
                    token: token.clone(),
                    deadline: self.deadline,
                    provider: Some(job.provider),
                };
                scheduled = index.saturating_add(1);
                running.spawn(async move {
                    let result = fetcher.fetch(&job.url).await.and_then(|bytes| {
                        parse_response(
                            job.provider,
                            &bytes,
                            entries,
                            &fetcher.token,
                            fetcher.deadline,
                        )
                    });
                    (
                        index,
                        ResultEntry {
                            provider: job.provider,
                            url: job.url,
                            result,
                        },
                    )
                });
            }
            if running.is_empty() {
                break;
            }
            let joined = if stopped {
                running.join_next().await
            } else {
                tokio::select! {
                    value = running.join_next() => value,
                    () = self.cancellation.cancelled() => { self.termination = Some(MapTermination::Cancelled); token.cancel(); stopped = true; continue; },
                    () = sleep_until(self.deadline) => { self.termination = Some(MapTermination::Deadline); token.cancel(); stopped = true; continue; },
                }
            };
            match joined {
                Some(Ok((index, result))) => {
                    if let Err(transport::Failure::Limit(limit)) = &result.result {
                        self.stop(*limit);
                        token.cancel();
                        stopped = true;
                    }
                    results.insert(index, result);
                }
                Some(Err(_)) => {
                    token.cancel();
                    stopped = true;
                }
                None => break,
            }
            if Instant::now() >= self.deadline || self.cancellation.is_cancelled() {
                self.termination = Some(if self.cancellation.is_cancelled() {
                    MapTermination::Cancelled
                } else {
                    MapTermination::Deadline
                });
                token.cancel();
                stopped = true;
            }
        }
        for (index, (provider, url)) in selected {
            results.entry(index).or_insert_with(|| ResultEntry {
                provider,
                url,
                result: if index < scheduled {
                    Err(transport::Failure::Source(SourceFailure::Transport))
                } else {
                    Err(transport::Failure::Stopped)
                },
            });
        }
        // Every catalog slot is represented above, including unscheduled work.
        let _ = pending;

        let consumed = budget.consumption().await;
        self.summary.requests = self
            .summary
            .requests
            .saturating_add(u32::try_from(consumed.traces.len()).unwrap_or(u32::MAX));
        self.summary.response_bytes = self.summary.response_bytes.saturating_add(consumed.charged);
        self.summary.inventory_bytes = self
            .summary
            .inventory_bytes
            .saturating_add(consumed.inventory);
        self.summary.provider_concurrency_peak =
            self.summary.provider_concurrency_peak.max(consumed.peak);
        self.request_trace.extend(consumed.traces);
        // Commit in catalog order so a response race cannot choose the capped host subset.
        for (_, entry) in results {
            let status = match entry.result {
                Ok(names) => self.merge_provider(entry.provider, &entry.url, names),
                Err(transport::Failure::Source(error)) => SourceStatus::Failed(error),
                Err(transport::Failure::Limit(limit)) => {
                    self.stop(limit);
                    SourceStatus::NotStarted
                }
                Err(transport::Failure::Stopped) => SourceStatus::NotStarted,
                Err(transport::Failure::ParsingStopped) => SourceStatus::Truncated,
            };
            self.source_outcomes.push(SourceOutcome {
                source: source(entry.provider),
                source_url: Some(entry.url),
                status,
            });
        }
        if let Some(limit) = consumed.limit {
            self.stop(limit);
        }
    }

    fn merge_provider(
        &mut self,
        provider: PublicProvider,
        url: &Url,
        names: ProviderNames,
    ) -> SourceStatus {
        let previous = self.termination.take();
        let status = self.merge_provider_names(provider, url, names);
        self.termination = previous.or(self.termination);
        status
    }

    fn merge_provider_names(
        &mut self,
        provider: PublicProvider,
        url: &Url,
        names: ProviderNames,
    ) -> SourceStatus {
        for wildcard in names.entries.wildcard_names {
            self.wildcard(&wildcard, url, source(provider));
            if self.termination.is_some() {
                break;
            }
        }
        for host in names.entries.names {
            if !self.host_name(&host, source(provider), Some(url)) {
                if self.termination.is_some() {
                    break;
                }
                continue;
            }
            if self.policy().map.pages == PageDiscovery::Explore
                && let Some(hostname) = self
                    .hosts
                    .keys()
                    .find(|candidate| candidate.eq_ignore_ascii_case(&host))
            {
                let mut candidate = self.seed.clone();
                if candidate.set_host(Some(hostname)).is_ok()
                    && candidate != self.seed
                    && self.probes.insert(candidate.clone())
                {
                    if self.probes.len()
                        > usize::try_from(self.policy().map.limits.max_pending.get())
                            .unwrap_or(usize::MAX)
                    {
                        self.probes.remove(&candidate);
                        self.stop(LimitReached::Pending);
                        break;
                    }
                    if !self.charge(candidate.as_str().len().saturating_add(64)) {
                        break;
                    }
                    self.queue.push_back(PageTask {
                        url: candidate,
                        depth: 0,
                        probe: true,
                    });
                }
            }
            if self.termination.is_some() {
                break;
            }
        }
        if names.entries.truncated || self.termination.is_some() {
            SourceStatus::Truncated
        } else if names.sample_limited {
            SourceStatus::Sampled
        } else {
            SourceStatus::Completed
        }
    }
}

fn parse_response(
    provider: PublicProvider,
    bytes: &[u8],
    entries: usize,
    token: &super::CancellationToken,
    deadline: Instant,
) -> Result<ProviderNames, transport::Failure> {
    if token.is_cancelled() || Instant::now() >= deadline {
        return Err(transport::Failure::ParsingStopped);
    }
    let result = providers::parse(provider, bytes, entries)
        .map_err(|_| transport::Failure::Source(SourceFailure::Parse));
    if token.is_cancelled() || Instant::now() >= deadline {
        return Err(transport::Failure::ParsingStopped);
    }
    result
}
