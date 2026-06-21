"""Persistable depth-first crawl frontier."""

from __future__ import annotations

import asyncio
import json
import logging
import posixpath
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic
from typing import Literal
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from yosoi.utils.files import atomic_write_json, init_yosoi

logger = logging.getLogger(__name__)

_DEFAULT_PORTS = {'http': 80, 'https': 443}
CrawlTerminalStatus = Literal['succeeded', 'failed', 'policy_blocked']


@dataclass(frozen=True, slots=True)
class FrontierEntry:
    """One URL waiting in the DFS stack."""

    url: str
    depth: int
    source_url: str | None = None
    score: float = 1.0


def canonicalize_url(url: str) -> str | None:
    """Canonicalize an HTTP(S) URL for crawl identity."""
    try:
        parsed = urlparse(url.strip())
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    if scheme not in {'http', 'https'}:
        return None

    host = parsed.hostname.lower() if parsed.hostname else ''
    if not host:
        return None

    netloc = host
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        netloc = f'{host}:{port}'

    path = quote(posixpath.normpath(parsed.path or '/'), safe='/%:@')
    if parsed.path.endswith('/') and path != '/':
        path = f'{path}/'

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunparse((scheme, netloc, path, '', query, ''))


class CrawlFrontier:
    """LIFO DFS frontier with canonical dedup, politeness, and persistence."""

    def __init__(
        self,
        *,
        session_id: str,
        max_depth: int,
        max_pages: int,
        politeness_delay: float = 1.0,
        storage_dir: str = 'crawler',
        persist: bool = True,
    ) -> None:
        """Initialize frontier state for one crawl session."""
        self.session_id = session_id
        self.max_depth = max(0, max_depth)
        self.max_pages = max(1, max_pages)
        self.politeness_delay = max(0.0, politeness_delay)
        self._filepath: Path | None = None
        if persist:
            storage_path = Path(str(init_yosoi(storage_dir)))
            self._filepath = storage_path / f'{session_id}.json'
        self._stack: list[FrontierEntry] = []
        self._seen: set[str] = set()
        self._in_flight: dict[str, FrontierEntry] = {}
        self._succeeded: set[str] = set()
        self._failed: set[str] = set()
        self._policy_blocked: set[str] = set()
        self._last_fetch_by_host: dict[str, float] = {}
        self._politeness_locks: dict[str, asyncio.Lock] = {}

        if self._filepath is not None and self._filepath.exists():
            self._load()

    @property
    def pages_fetched(self) -> int:
        """Number of canonical URLs successfully fetched by the crawl."""
        return len(self._succeeded)

    @property
    def seen_count(self) -> int:
        """Number of canonical URLs discovered across stack and fetched sets."""
        return len(self._seen)

    @property
    def pending_count(self) -> int:
        """Number of URLs still waiting in the DFS stack."""
        return len(self._stack)

    @property
    def in_flight_count(self) -> int:
        """Number of URLs currently reserved by workers."""
        return len(self._in_flight)

    @property
    def failed_count(self) -> int:
        """Number of URLs whose workers failed."""
        return len(self._failed)

    @property
    def policy_blocked_count(self) -> int:
        """Number of URLs skipped by policy before fetch."""
        return len(self._policy_blocked)

    def push(self, url: str, *, depth: int, source_url: str | None = None, score: float = 1.0) -> bool:
        """Push a URL onto the DFS stack if it is in budget and unseen."""
        if depth > self.max_depth or self.pages_fetched >= self.max_pages:
            return False

        canonical = canonicalize_url(url)
        if canonical is None or canonical in self._seen:
            return False

        self._seen.add(canonical)
        self._stack.append(FrontierEntry(url=canonical, depth=depth, source_url=source_url, score=score))
        logger.debug('crawler frontier push url=%s depth=%d score=%.2f', canonical, depth, score)
        return True

    def push_many(self, entries: list[FrontierEntry]) -> int:
        """Push entries preserving their listed order under DFS pop semantics."""
        pushed = 0
        for entry in reversed(entries):
            if self.push(entry.url, depth=entry.depth, source_url=entry.source_url, score=entry.score):
                pushed += 1
        return pushed

    def reprioritize(self, scorer: Callable[[FrontierEntry], float]) -> None:
        """Update pending entry scores while preserving the frontier's LIFO mechanics."""
        updated: list[FrontierEntry] = []
        for entry in self._stack:
            score = max(entry.score, float(scorer(entry)))
            updated.append(FrontierEntry(url=entry.url, depth=entry.depth, source_url=entry.source_url, score=score))
        updated.sort(key=lambda entry: entry.score)
        self._stack = updated

    def reserve_batch(self, limit: int) -> list[FrontierEntry]:
        """Reserve up to ``limit`` URLs in LIFO order for concurrent workers."""
        if limit < 1 or self.pages_fetched >= self.max_pages:
            return []
        remaining_budget = self.max_pages - self.pages_fetched - self.in_flight_count
        if remaining_budget <= 0:
            return []

        batch: list[FrontierEntry] = []
        while self._stack and len(batch) < min(limit, remaining_budget):
            entry = self._stack.pop()
            self._in_flight[entry.url] = entry
            batch.append(entry)
        return batch

    def commit(self, url: str, status: CrawlTerminalStatus) -> None:
        """Move a reserved URL into a terminal crawl status."""
        canonical = canonicalize_url(url)
        if canonical is None:
            return
        self._in_flight.pop(canonical, None)
        if status == 'succeeded':
            self._succeeded.add(canonical)
        elif status == 'failed':
            self._failed.add(canonical)
        else:
            self._policy_blocked.add(canonical)

    async def save(self) -> None:
        """Persist frontier state atomically for crawl resume."""
        if self._filepath is None:
            return
        payload = {
            'session_id': self.session_id,
            'max_depth': self.max_depth,
            'max_pages': self.max_pages,
            'politeness_delay': self.politeness_delay,
            'stack': [asdict(entry) for entry in self._stack],
            'in_flight': [asdict(entry) for entry in self._in_flight.values()],
            'seen': sorted(self._seen),
            'succeeded': sorted(self._succeeded),
            'failed': sorted(self._failed),
            'policy_blocked': sorted(self._policy_blocked),
            'last_fetch_by_host': self._last_fetch_by_host,
        }
        atomic_write_json(self._filepath, payload, ensure_ascii=False)

    def _load(self) -> None:
        try:
            if self._filepath is None:
                return
            data = json.loads(self._filepath.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning('could not load crawl frontier %s: %s', self._filepath, exc)
            return

        self._seen = {str(value) for value in data.get('seen', [])}
        self._succeeded = {str(value) for value in data.get('succeeded', data.get('fetched', []))}
        self._failed = {str(value) for value in data.get('failed', [])}
        self._policy_blocked = {str(value) for value in data.get('policy_blocked', data.get('skipped_robots', []))}
        self._last_fetch_by_host = {
            str(host): float(timestamp) for host, timestamp in dict(data.get('last_fetch_by_host', {})).items()
        }
        self._stack = []
        self._in_flight = {}
        terminal = self._succeeded | self._failed | self._policy_blocked
        for raw in [*data.get('stack', []), *data.get('in_flight', [])]:
            if not isinstance(raw, dict):
                continue
            canonical = canonicalize_url(str(raw.get('url', '')))
            if canonical is None or canonical in terminal:
                continue
            self._stack.append(
                FrontierEntry(
                    url=canonical,
                    depth=int(raw.get('depth', 0)),
                    source_url=raw.get('source_url') if isinstance(raw.get('source_url'), str) else None,
                    score=float(raw.get('score', 1.0)),
                )
            )
            self._seen.add(canonical)

    async def respect_politeness(self, url: str) -> None:
        """Apply per-host crawl delay before a worker fetches ``url``."""
        if self.politeness_delay <= 0:
            return
        canonical = canonicalize_url(url)
        host = urlparse(canonical).hostname if canonical else None
        if not host:
            return

        lock = self._politeness_locks.setdefault(host, asyncio.Lock())
        async with lock:
            last_fetch = self._last_fetch_by_host.get(host)
            now = monotonic()
            if last_fetch is not None:
                wait_for = self.politeness_delay - (now - last_fetch)
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
            self._last_fetch_by_host[host] = monotonic()
