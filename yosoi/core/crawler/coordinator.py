"""Policy-driven bounded-concurrency DFS crawl coordinator."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

from yosoi.core.crawler.frontier import CrawlFrontier, FrontierEntry
from yosoi.core.crawler.links import CrawlLink, LinkExtractor
from yosoi.policy import CrawlRuntimeConfig

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
    fetch_time: float = 0.0
    error: str | None = None


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
    ) -> None:
        """Create a coordinator for one policy-derived crawl runtime config."""
        self.fetcher = fetcher
        self.config = config
        session_id = config.crawl_session_id or 'crawl-policy-run'
        self.extractor = extractor or LinkExtractor()
        self.persist_frontier = persist_frontier
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

        for seed in crawl_seeds:
            self.frontier.push(seed, depth=0, score=1.0)

        max_attempts = self.config.max_attempts or self.config.max_pages
        while (
            self.frontier.pending_count
            and self.frontier.pages_fetched < self.config.max_pages
            and summary.attempted_urls < max_attempts
        ):
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

            results = await asyncio.gather(*(self._run_worker(job) for job in jobs))
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
        return summary

    async def _run_worker(self, job: CrawlJob) -> CrawlResult:
        started = time.monotonic()
        policy_error = self._policy_error(job.url)
        if policy_error is not None:
            return CrawlResult(job=job, status='policy_blocked', error=policy_error)

        try:
            await self.frontier.respect_politeness(job.url)
            result = await self.fetcher.fetch(job.url)
        except Exception as exc:  # noqa: BLE001 - record worker failures instead of killing the crawl
            return CrawlResult(job=job, status='failed', error=str(exc), fetch_time=time.monotonic() - started)

        html = getattr(result, 'html', None)
        success = bool(getattr(result, 'success', html is not None))
        if not success or not html:
            block_reason = getattr(result, 'block_reason', None)
            return CrawlResult(
                job=job,
                status='failed',
                error=str(block_reason or 'fetch failed'),
                fetch_time=time.monotonic() - started,
            )

        links: tuple[CrawlLink, ...] = ()
        if job.depth < self.config.max_depth:
            allowed_hosts = set(self.config.allowed_hosts) if self.config.allowed_hosts else None
            extracted = self.extractor.extract(str(html), base_url=job.url, allowed_hosts=allowed_hosts)
            links = tuple(extracted)

        return CrawlResult(
            job=job,
            status='succeeded',
            discovered_links=links,
            html_chars=len(str(html)),
            fetch_time=time.monotonic() - started,
        )

    def _policy_error(self, url: str) -> str | None:
        parsed = urlparse(url)
        host = parsed.hostname.lower() if parsed.hostname else ''
        if host in set(self.config.denied_hosts):
            return f'host denied by policy: {host}'
        if self.config.allowed_hosts and host not in set(self.config.allowed_hosts):
            return f'host not allowed by policy: {host}'
        if any(parsed.path.startswith(prefix) for prefix in self.config.blocked_path_prefixes):
            return f'path blocked by policy: {parsed.path}'
        return None

    def _commit_result(self, result: CrawlResult, summary: CrawlRunSummary) -> None:
        self.frontier.commit(result.job.url, result.status)
        summary.results.append(result)
        summary.attempted_urls = len(summary.results)
        if result.status != 'succeeded':
            return

        pushed = self.frontier.push_many(
            [
                FrontierEntry(
                    url=link.url,
                    depth=result.job.depth + 1,
                    source_url=result.job.url,
                    score=link.score,
                )
                for link in result.discovered_links
            ]
        )
        summary.duplicates_blocked += len(result.discovered_links) - pushed
