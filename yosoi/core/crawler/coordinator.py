"""Policy-driven bounded-concurrency DFS crawl coordinator."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from yosoi.core.crawler.candidates import CandidateFit, CrawlCandidateEntry, contract_name, score_contract_fit
from yosoi.core.crawler.frontier import CrawlFrontier, FrontierEntry
from yosoi.core.crawler.links import CrawlLink, LinkExtractor, best_path_similarity
from yosoi.core.page import PageAcquisition
from yosoi.generalization.fingerprint import PageFingerprint, PageObservation
from yosoi.policy import CrawlRuntimeConfig
from yosoi.policy.robots import RobotsGate

CrawlStatus = Literal['succeeded', 'failed', 'policy_blocked']


@dataclass(frozen=True, slots=True)
class CrawlJob:
    """A worker assignment reserved from the shared frontier."""

    url: str
    depth: int
    source_url: str | None
    batch_index: int


@dataclass(frozen=True, slots=True)
class CrawlResult:
    """A worker result returned to the coordinator bridge."""

    job: CrawlJob
    status: CrawlStatus
    discovered_links: tuple[CrawlLink, ...] = ()
    html_chars: int = 0
    html: str = ''
    fetch_time: float = 0.0
    error: str | None = None
    fingerprint: PageFingerprint | None = None
    observation: PageObservation | None = None


class CrawlReporter(Protocol):
    """Optional observer for human-facing crawl progress."""

    def start(self, *, seeds: tuple[str, ...], summary: CrawlRunSummary, config: CrawlRuntimeConfig) -> None:
        """Observe crawl startup."""
        ...

    def batch(self, jobs: tuple[CrawlJob, ...], summary: CrawlRunSummary) -> None:
        """Observe a reserved worker batch."""
        ...

    def result(self, result: CrawlResult, summary: CrawlRunSummary) -> None:
        """Observe one committed worker result."""
        ...

    def finish(self, summary: CrawlRunSummary) -> None:
        """Observe crawl completion."""
        ...


@dataclass(slots=True)
class CrawlRunSummary:
    """Aggregated measurements for crawler policy and scheduler decisions."""

    pages_fetched: int = 0
    attempted_urls: int = 0
    unique_urls_seen: int = 0
    duplicates_blocked: int = 0
    policy_blocked: int = 0
    failures: int = 0
    batches: int = 0
    idle_worker_slots: int = 0
    wall_time: float = 0.0
    results: list[CrawlResult] = field(default_factory=list)
    contract_candidate_urls: dict[str, list[str]] = field(default_factory=dict)
    contract_candidate_entries: dict[str, list[CrawlCandidateEntry]] = field(default_factory=dict)
    _max_workers_seen: int = 1

    @property
    def worker_slots_total(self) -> int:
        """Total dispatch slots made available across crawl batches."""
        return self.batches * max(1, self._max_workers_seen)

    @property
    def worker_slots_used(self) -> int:
        """Dispatch slots that received frontier work."""
        return max(0, self.worker_slots_total - self.idle_worker_slots)

    @property
    def average_batch_fill(self) -> float:
        """Average number of workers assigned per dispatch batch."""
        return self.worker_slots_used / self.batches if self.batches else 0.0

    @property
    def dispatch_slot_idle_ratio(self) -> float:
        """Dispatch capacity ratio unused because no frontier work was ready."""
        total_slots = self.worker_slots_total
        return self.idle_worker_slots / total_slots if total_slots else 0.0

    @property
    def idle_worker_ratio(self) -> float:
        """Backward-compatible alias for ``dispatch_slot_idle_ratio``."""
        return self.dispatch_slot_idle_ratio

    @property
    def outcome_lanes(self) -> dict[str, list[str]]:
        """Group attempted URLs into stable outcome lanes."""
        lanes: dict[str, list[str]] = {'succeeded': [], 'failed': [], 'policy_blocked': []}
        for result in self.results:
            lanes[result.status].append(result.job.url)
        return {name: urls for name, urls in lanes.items() if urls}

    def urls_for(
        self,
        contract: object,
        *,
        limit: int | None = None,
        min_score: float = 0.0,
        include_weak: bool = False,
    ) -> list[str]:
        """Return ranked URLs likely to satisfy ``contract`` when passed to ``ys.scrape``."""
        entries = self.candidates_for(contract, limit=limit, min_score=min_score, include_weak=include_weak)
        return [entry.url for entry in entries]

    def candidates_for(
        self,
        contract: object,
        *,
        limit: int | None = None,
        min_score: float = 0.0,
        fit: CandidateFit | None = None,
        include_weak: bool = False,
    ) -> list[CrawlCandidateEntry]:
        """Return explainable crawl candidate entries for a contract class or name."""
        name = contract_name(contract)
        entries = [
            entry
            for entry in self.contract_candidate_entries.get(name, ())
            if entry.score >= min_score
            and (include_weak or fit == 'weak' or entry.fit != 'weak')
            and (fit is None or entry.fit == fit)
        ]
        return list(entries[:limit])


class CrawlCoordinator:
    """Owns frontier mutation while workers fetch and extract links concurrently."""

    def __init__(
        self,
        *,
        fetcher: Any,
        config: CrawlRuntimeConfig,
        extractor: LinkExtractor | None = None,
        frontier: CrawlFrontier | None = None,
        persist_frontier: bool = True,
        reporter: CrawlReporter | None = None,
    ) -> None:
        """Create a coordinator for one policy-derived crawl runtime config."""
        self.fetcher = fetcher
        self.config = config
        # Fail-closed confinement: when cross-domain is disallowed and no explicit
        # allow-list was given, the crawl is pinned to its own seed hosts (populated in
        # run()), so an empty allow-list can never silently mean "follow links anywhere".
        self._seed_confined_hosts: set[str] = set()
        self._host_fetch_semaphores: dict[str, asyncio.Semaphore] = {}
        self._pages_fetched_by_host: dict[str, int] = {}
        session_id = config.crawl_session_id or 'crawl-policy-run'
        self.extractor = extractor or LinkExtractor()
        self.acquisition = PageAcquisition(config.page, fingerprint=True)
        self.persist_frontier = persist_frontier
        self.reporter = reporter
        # robots.txt is policy-gated and default-on; opting out (respect_robots=False) skips the gate.
        self._robots = RobotsGate(fetcher) if config.respect_robots else None
        self.frontier = frontier or CrawlFrontier(
            session_id=session_id,
            max_depth=config.max_depth,
            max_pages=config.max_pages,
            politeness_delay=config.politeness_delay,
            persist=persist_frontier,
        )

    async def run(self, seeds: tuple[str, ...] | None = None) -> CrawlRunSummary:
        """Run the crawl and return a measurement summary."""
        started = time.monotonic()
        summary = CrawlRunSummary(_max_workers_seen=self.config.max_workers)
        crawl_seeds = seeds if seeds is not None else self.config.seeds

        if not self.config.allow_cross_domain and not self.config.allowed_hosts:
            self._seed_confined_hosts = {host.lower() for s in crawl_seeds if (host := urlparse(s).hostname)}

        for seed in crawl_seeds:
            self.frontier.push(seed, depth=0, score=1.0)

        if self.reporter is not None:
            self.reporter.start(seeds=tuple(crawl_seeds), summary=summary, config=self.config)

        max_attempts = self.config.max_attempts or self.config.max_pages
        while (
            self.frontier.pending_count
            and self.frontier.pages_fetched < self.config.max_pages
            and summary.attempted_urls < max_attempts
        ):
            self._reprioritize_frontier(summary)
            remaining_attempts = max_attempts - summary.attempted_urls
            effective_workers = min(
                self.config.max_workers,
                self.frontier.pending_count,
                self.config.max_pages - self.frontier.pages_fetched,
                remaining_attempts,
            )
            entries = self.frontier.reserve_batch(effective_workers)
            if not entries:
                break

            jobs = [
                CrawlJob(url=entry.url, depth=entry.depth, source_url=entry.source_url, batch_index=index)
                for index, entry in enumerate(entries)
            ]
            summary.batches += 1
            summary.idle_worker_slots += max(0, self.config.max_workers - len(jobs))
            if self.reporter is not None:
                self.reporter.batch(tuple(jobs), summary)

            tasks = [asyncio.create_task(self._run_worker(job)) for job in jobs]
            results: list[CrawlResult] = []
            for task in asyncio.as_completed(tasks):
                result = await task
                results.append(result)
                if self.reporter is not None:
                    self.reporter.result(result, summary)
            for result in sorted(results, key=lambda item: item.job.batch_index):
                self._commit_result(result, summary)

        if self.persist_frontier:
            await self.frontier.save()
        summary.wall_time = time.monotonic() - started
        summary.pages_fetched = self.frontier.pages_fetched
        summary.attempted_urls = len(summary.results)
        summary.unique_urls_seen = self.frontier.seen_count
        summary.failures = self.frontier.failed_count
        summary.policy_blocked = self.frontier.policy_blocked_count
        if self.reporter is not None:
            self.reporter.finish(summary)
        return summary

    async def _run_worker(self, job: CrawlJob) -> CrawlResult:
        started = time.monotonic()
        policy_error = self._policy_error(job.url)
        if policy_error is not None:
            return CrawlResult(job=job, status='policy_blocked', error=policy_error)

        if self._robots is not None and not await self._robots.allowed(job.url):
            return CrawlResult(job=job, status='policy_blocked', error='disallowed by robots.txt')

        host = self._host_for(job.url)
        try:
            semaphore = self._host_fetch_semaphore(host)
            async with semaphore:
                host_cap_error = self._host_page_cap_error(host)
                if host_cap_error is not None:
                    return CrawlResult(job=job, status='policy_blocked', error=host_cap_error)
                await self.frontier.respect_politeness(job.url)
                snapshot = await self.acquisition.acquire(job.url, fetcher=self.fetcher)
        except Exception as exc:  # noqa: BLE001 - record worker failures instead of killing the crawl
            return CrawlResult(job=job, status='failed', error=str(exc), fetch_time=time.monotonic() - started)

        if not self.config.allow_redirects and snapshot.final_url != job.url:
            return CrawlResult(
                job=job,
                status='policy_blocked',
                error=f'redirect blocked by policy: {job.url} -> {snapshot.final_url}',
                fetch_time=time.monotonic() - started,
            )

        links: tuple[CrawlLink, ...] = ()
        if job.depth < self.config.max_depth:
            extracted = self.extractor.extract(
                snapshot.raw_html, base_url=job.url, allowed_hosts=self._effective_allowed_hosts() or None
            )
            links = tuple(extracted)

        html_text = snapshot.html_for_discovery
        if host:
            self._pages_fetched_by_host[host] = self._pages_fetched_by_host.get(host, 0) + 1

        return CrawlResult(
            job=job,
            status='succeeded',
            discovered_links=links,
            html_chars=len(html_text),
            html=html_text,
            fetch_time=time.monotonic() - started,
            fingerprint=snapshot.fingerprint,
            observation=snapshot.observation,
        )

    def _effective_allowed_hosts(self) -> set[str]:
        """Hosts this crawl may visit: the explicit allow-list, else seed-host confinement.

        Empty only when cross-domain is explicitly permitted; otherwise an empty
        ``allowed_hosts`` is backfilled with the seed hosts so the crawl fails closed.
        """
        if self.config.allowed_hosts:
            return {h.lower() for h in self.config.allowed_hosts}
        return self._seed_confined_hosts

    def _host_for(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.hostname.lower() if parsed.hostname else ''

    def _host_fetch_semaphore(self, host: str) -> asyncio.Semaphore:
        key = host or ''
        limit = max(1, self.config.per_host_concurrency)
        semaphore = self._host_fetch_semaphores.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(limit)
            self._host_fetch_semaphores[key] = semaphore
        return semaphore

    def _host_page_cap_error(self, host: str) -> str | None:
        cap = self.config.max_pages_per_host
        if cap is None or not host:
            return None
        if self._pages_fetched_by_host.get(host, 0) >= cap:
            return f'host page cap reached by policy: {host}'
        return None

    def _policy_error(self, url: str) -> str | None:
        parsed = urlparse(url)
        host = parsed.hostname.lower() if parsed.hostname else ''
        if host in set(self.config.denied_hosts):
            return f'host denied by policy: {host}'
        allowed_hosts = self._effective_allowed_hosts()
        if allowed_hosts and host not in allowed_hosts:
            return f'host not allowed by policy: {host}'
        if any(parsed.path.startswith(prefix) for prefix in self.config.blocked_path_prefixes):
            return f'path blocked by policy: {parsed.path}'
        host_cap_error = self._host_page_cap_error(host)
        if host_cap_error is not None:
            return host_cap_error
        return None

    def _commit_result(self, result: CrawlResult, summary: CrawlRunSummary) -> None:
        self.frontier.commit(result.job.url, result.status)
        summary.results.append(result)
        summary.attempted_urls = len(summary.results)
        if result.status != 'succeeded':
            return
        self._index_result(result, summary)

        entries = [
            FrontierEntry(
                url=link.url,
                depth=result.job.depth + 1,
                source_url=result.job.url,
                score=self._planned_link_score(link, summary),
            )
            for link in result.discovered_links
        ]
        entries.sort(key=lambda entry: entry.score, reverse=True)
        pushed = self.frontier.push_many(entries)
        summary.duplicates_blocked += len(result.discovered_links) - pushed

    def _index_result(self, result: CrawlResult, summary: CrawlRunSummary) -> None:
        if result.fingerprint is None or result.observation is None:
            return
        for target in self.config.target_contracts:
            name = target.name
            entries = summary.contract_candidate_entries.setdefault(name, [])
            limit = target.max_budget_pages or self.config.max_pages

            entry = score_contract_fit(
                name,
                url=result.job.url,
                source_url=result.job.source_url,
                fingerprint=result.fingerprint,
                observation=result.observation,
                html=result.html,
            )
            if entry is None or entry.score < target.min_fit_score:
                continue
            by_url = {existing.url: existing for existing in entries}
            current = by_url.get(entry.url)
            if current is None or entry.score > current.score:
                by_url[entry.url] = entry
            ranked = sorted(by_url.values(), key=lambda item: item.score, reverse=True)[:limit]
            summary.contract_candidate_entries[name] = ranked
            summary.contract_candidate_urls[name] = [item.url for item in ranked if item.fit != 'weak']

    def _reprioritize_frontier(self, summary: CrawlRunSummary) -> None:
        if not self._path_planning_enabled():
            return
        references = self._candidate_reference_urls(summary)
        if not references:
            return
        self.frontier.reprioritize(lambda entry: self._planned_url_score(entry.url, entry.score, references))

    def _planned_link_score(self, link: CrawlLink, summary: CrawlRunSummary) -> float:
        if not self._path_planning_enabled():
            return link.score
        references = self._candidate_reference_urls(summary)
        if not references:
            return link.score
        return self._planned_url_score(link.url, link.score, references)

    def _planned_url_score(self, url: str, base_score: float, references: tuple[str, ...]) -> float:
        if not self._path_planning_enabled():
            return base_score
        planning = self.config.path_planning
        similarity = best_path_similarity(url, references)
        if similarity < planning.min_similarity:
            return base_score
        return min(1.0, base_score + (planning.score_boost * similarity))

    def _candidate_reference_urls(self, summary: CrawlRunSummary) -> tuple[str, ...]:
        planning = self.config.path_planning
        urls: list[str] = []
        for entries in summary.contract_candidate_entries.values():
            for entry in entries:
                if entry.fit == 'weak':
                    continue
                urls.append(entry.url)
                if len(urls) >= planning.max_reference_urls:
                    return tuple(urls)
        return tuple(urls)

    def _path_planning_enabled(self) -> bool:
        return bool(self.config.path_planning.enabled and self.config.path_planning.score_boost > 0)
