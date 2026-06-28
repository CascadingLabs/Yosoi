"""Policy-driven bounded-concurrency DFS crawl coordinator."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

import lxml.html

from yosoi.core.crawler.frontier import CrawlFrontier, FrontierEntry
from yosoi.core.crawler.links import CrawlLink, LinkExtractor
from yosoi.core.page import PageAcquisition
from yosoi.generalization.fingerprint import PageFingerprint, PageObservation
from yosoi.policy import CrawlRuntimeConfig
from yosoi.policy.robots import RobotsGate

CrawlStatus = Literal['succeeded', 'failed', 'policy_blocked']
_ROUTE_ARTIFACT_SEGMENTS = frozenset({'agents', 'readme', 'license', 'contributing', 'security', 'code_of_conduct'})


@dataclass(frozen=True)
class CrawlJob:
    """A worker assignment reserved from the shared frontier."""

    url: str
    depth: int
    source_url: str | None
    batch_index: int


@dataclass(frozen=True)
class CrawlResult:
    """A worker result returned to the coordinator bridge."""

    job: CrawlJob
    status: CrawlStatus
    discovered_links: tuple[CrawlLink, ...] = ()
    html_chars: int = 0
    html: str = ''
    fetch_time: float = 0.0
    error: str | None = None
    content_type: str | None = None
    status_code: int | None = None
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


@dataclass
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
    scraped_content: dict[str, Any] = field(default_factory=dict)
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

    def path_prefix_counts(self, *, depth: int = 1) -> dict[str, int]:
        """Count succeeded URLs by leading path prefix for crawl coverage inspection."""
        counts: dict[str, int] = {}
        for result in self.results:
            if result.status != 'succeeded':
                continue
            path = urlparse(result.job.url).path.strip('/')
            parts = tuple(part for part in path.split('/') if part)
            prefix = '/' + '/'.join(parts[:depth]) if parts else '/'
            counts[prefix] = counts.get(prefix, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    def content_type_counts(self) -> dict[str, int]:
        """Count succeeded URLs by response content-type family."""
        counts: dict[str, int] = {}
        for result in self.results:
            if result.status != 'succeeded':
                continue
            content_type = (result.content_type or 'unknown').split(';', 1)[0].strip().lower() or 'unknown'
            counts[content_type] = counts.get(content_type, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    def representative_urls(self, *, limit: int | None = None, html_only: bool = True) -> list[str]:
        """Return neutral representative URLs from the crawl inventory.

        Selection is contract-agnostic: choose one URL per observed structural
        fingerprint/path-shape cluster, then fill from remaining successful pages
        in crawl order.
        """
        results = [result for result in self.results if _representative_eligible(result, html_only=html_only)]
        return _cluster_representative_urls(results, limit=limit)

    def scrape_target_urls(self, *, limit: int | None = None, html_only: bool = True) -> list[str]:
        """Return neutral crawl URLs worth trying with scrape/discovery.

        This is not contract-fit scoring. It is neutral inventory sampling: prefer
        non-seed pages with stronger content evidence and lower outdegree, then
        dedupe by structural/path cluster. If a crawl only fetched seeds, eligible
        seeds are returned so single-page crawls remain scrapeable.
        """
        non_seed = [
            result
            for result in self.results
            if result.job.depth > 0 and _representative_eligible(result, html_only=html_only)
        ]
        source = non_seed or [
            result for result in self.results if _representative_eligible(result, html_only=html_only)
        ]
        ordered = sorted(source, key=_scrape_target_sort_key)
        return _cluster_representative_urls(ordered, limit=limit)


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
        self._pages_reserved_by_host: dict[str, int] = {}
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
            results = [await task for task in asyncio.as_completed(tasks)]
            for result in sorted(results, key=lambda item: item.job.batch_index):
                self._commit_result(result, summary)
                if self.reporter is not None:
                    self.reporter.result(result, summary)

        if self.persist_frontier:
            await self.frontier.save()
        summary.wall_time = time.monotonic() - started
        self._refresh_summary_counts(summary)
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
                if not self._reserve_host_page_slot(host):
                    return CrawlResult(job=job, status='policy_blocked', error=self._host_page_cap_message(host))
                await self.frontier.respect_politeness(job.url)
                try:
                    snapshot = await self.acquisition.acquire(job.url, fetcher=self.fetcher)
                except Exception:
                    self._release_host_page_slot(host)
                    raise
        except Exception as exc:  # noqa: BLE001 - record worker failures instead of killing the crawl
            return CrawlResult(job=job, status='failed', error=str(exc), fetch_time=time.monotonic() - started)

        if not self.config.allow_redirects and snapshot.final_url != job.url:
            self._release_host_page_slot(host)
            return CrawlResult(
                job=job,
                status='policy_blocked',
                error=f'redirect blocked by policy: {job.url} -> {snapshot.final_url}',
                fetch_time=time.monotonic() - started,
                content_type=_content_type(getattr(snapshot.fetch_result, 'headers', None)),
                status_code=getattr(snapshot.fetch_result, 'status_code', None),
            )

        links: tuple[CrawlLink, ...] = ()
        if job.depth < self.config.max_depth:
            extracted = self.extractor.extract(
                snapshot.raw_html, base_url=job.url, allowed_hosts=self._effective_allowed_hosts() or None
            )
            links = tuple(extracted)

        html_text = snapshot.html_for_discovery
        content_type = _content_type(getattr(snapshot.fetch_result, 'headers', None))
        if host:
            self._pages_fetched_by_host[host] = self._pages_fetched_by_host.get(host, 0) + 1
            self._release_host_page_slot(host)

        return CrawlResult(
            job=job,
            status='succeeded',
            discovered_links=links,
            html_chars=len(html_text),
            html=html_text,
            fetch_time=time.monotonic() - started,
            content_type=content_type,
            status_code=getattr(snapshot.fetch_result, 'status_code', None),
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
        if self._host_page_budget_used(host) >= cap:
            return self._host_page_cap_message(host)
        return None

    def _reserve_host_page_slot(self, host: str) -> bool:
        cap = self.config.max_pages_per_host
        if cap is None or not host:
            return True
        if self._host_page_budget_used(host) >= cap:
            return False
        self._pages_reserved_by_host[host] = self._pages_reserved_by_host.get(host, 0) + 1
        return True

    def _release_host_page_slot(self, host: str) -> None:
        if not host:
            return
        reserved = self._pages_reserved_by_host.get(host, 0)
        if reserved <= 1:
            self._pages_reserved_by_host.pop(host, None)
        else:
            self._pages_reserved_by_host[host] = reserved - 1

    def _host_page_budget_used(self, host: str) -> int:
        return self._pages_fetched_by_host.get(host, 0) + self._pages_reserved_by_host.get(host, 0)

    def _host_page_cap_message(self, host: str) -> str:
        return f'host page cap reached by policy: {host}'

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
        self._refresh_summary_counts(summary)
        if result.status != 'succeeded':
            return
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
        self._refresh_summary_counts(summary)

    def _refresh_summary_counts(self, summary: CrawlRunSummary) -> None:
        summary.pages_fetched = self.frontier.pages_fetched
        summary.attempted_urls = len(summary.results)
        summary.unique_urls_seen = self.frontier.seen_count
        summary.failures = self.frontier.failed_count
        summary.policy_blocked = self.frontier.policy_blocked_count

    def _planned_link_score(self, link: CrawlLink, _summary: CrawlRunSummary) -> float:
        return self._target_intent_link_score(link)

    def _target_intent_link_score(self, link: CrawlLink) -> float:
        score = link.score
        parsed = urlparse(link.url)
        link_tokens = _tokens_from_text(f'{parsed.path} {parsed.query} {link.text}')
        for target in self.config.target_contracts:
            target_tokens = set(target.intent_tokens) | _tokens_from_text(target.name)
            matches = link_tokens & target_tokens
            if len(matches) >= 2:
                score = max(score, min(1.0, link.score + 0.40))
            elif matches:
                score = max(score, min(1.0, link.score + 0.25))
        return score


def _cluster_representative_urls(results: list[CrawlResult], *, limit: int | None) -> list[str]:
    selected: list[CrawlResult] = []
    used_clusters: set[tuple[str, object]] = set()
    for result in results:
        cluster = _representative_cluster(result)
        if cluster in used_clusters:
            continue
        selected.append(result)
        used_clusters.add(cluster)
        if limit is not None and len(selected) >= limit:
            return [item.job.url for item in selected]

    if limit is None:
        return [item.job.url for item in selected]

    for result in results:
        if result in selected:
            continue
        selected.append(result)
        if len(selected) >= limit:
            break
    return [item.job.url for item in selected]


def _representative_eligible(result: CrawlResult, *, html_only: bool) -> bool:
    if result.status != 'succeeded':
        return False
    if not html_only:
        return True
    content_type = (result.content_type or '').split(';', 1)[0].strip().lower()
    return content_type in {'', 'text/html', 'application/xhtml+xml'}


def _scrape_target_sort_key(result: CrawlResult) -> tuple[int, float, int, int]:
    return (
        _route_artifact_penalty(result.job.url),
        -_content_evidence_score(result),
        len(result.discovered_links),
        -result.job.depth,
    )


def _route_artifact_penalty(url: str) -> int:
    parsed = urlparse(url)
    segments = {part.strip().lower() for part in parsed.path.strip('/').split('/') if part.strip()}
    return int(bool(segments & _ROUTE_ARTIFACT_SEGMENTS))


def _content_evidence_score(result: CrawlResult) -> float:
    text_len = len(_visible_text(result.html))
    if text_len == 0:
        return 0.0
    text_score = min(1.0, text_len / 1_500)
    outdegree_penalty = min(0.8, len(result.discovered_links) / 50)
    return max(0.0, text_score - outdegree_penalty)


def _visible_text(html: str) -> str:
    if not html.strip():
        return ''
    try:
        root = lxml.html.fromstring(html[:200_000])
    except (TypeError, ValueError):
        return ''
    for element in root.xpath('.//script | .//style | .//noscript | .//nav | .//header | .//footer'):
        element.drop_tree()
    return ' '.join(root.itertext()).strip()


def _representative_cluster(result: CrawlResult) -> tuple[str, object]:
    if result.fingerprint is not None and result.fingerprint.skeleton:
        return ('fingerprint', result.fingerprint.skeleton)
    return ('path_shape', _path_shape(result.job.url))


def _path_shape(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.strip('/').split('/') if part]
    normalized = [':id' if any(char.isdigit() for char in part) else part for part in parts]
    return '/' + '/'.join(normalized)


def _content_type(headers: Any) -> str | None:
    if not isinstance(headers, dict):
        return None
    for key, value in headers.items():
        if str(key).lower() == 'content-type':
            return str(value)
    return None


def _tokens_from_text(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+', text)
        if len(token) >= 3 and token.lower() not in {'dev', 'qscrape'}
    }
