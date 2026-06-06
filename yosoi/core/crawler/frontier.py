"""Crawl frontier for score-priority scraping with politeness and persistence.

Design constraints (CAS-49):
- Priority queue (max-heap by score) as the scrape queue — highest scoring
  URLs are scraped first regardless of insertion order.
- Visited set for URL dedup using normalised URLs.
- URL normalisation: lowercase scheme and host, strip trailing slashes,
  drop default ports (80 for http, 443 for https).
- Per-host politeness: minimum 1.0s between fetches of the same host.
- Persistable to .yosoi/frontier/<session_id>.json — scrape queue and
  visited set serialised as JSON.
- Resumable — on init check for an existing frontier file and reload it.
- No robots.txt.
- Frontier does not own fetching — fetcher is passed in from Pipeline.scrape().
"""

from __future__ import annotations

import asyncio
import heapq
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from yosoi.utils.files import init_yosoi

logger = logging.getLogger(__name__)

# Default ports that should be stripped during normalisation.
_DEFAULT_PORTS: dict[str, int] = {'http': 80, 'https': 443}

# Minimum seconds between fetches of the same host.
_POLITENESS_DELAY: float = 1.0


def normalize_url(url: str) -> str | None:
    """Normalise a URL for dedup purposes.

    Rules:
    - Lowercase scheme and host.
    - Strip trailing slashes from path.
    - Drop default ports (80 for http, 443 for https).
    - Strip fragment.
    - Return None for non-http(s) URLs.

    Args:
        url: Raw URL string.

    Returns:
        Normalised URL string, or None if the URL is not http(s).
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    if scheme not in ('http', 'https'):
        return None

    host = parsed.hostname
    if not host:
        return None
    host = host.lower()

    port = parsed.port
    if port is not None and port == _DEFAULT_PORTS.get(scheme):
        port = None

    netloc = host if port is None else f'{host}:{port}'
    path = parsed.path.rstrip('/') or '/'
    normalised = urlunparse((scheme, netloc, path, parsed.params, parsed.query, ''))
    return normalised


class Frontier:
    """Score-priority crawl frontier with dedup, politeness, and JSON persistence.

    URLs are scraped in descending score order — the highest-scoring URL is
    always scraped next, regardless of when it was pushed. Equal scores are
    broken by insertion order (FIFO within the same score).

    Usage::

        frontier = Frontier(session_id="my-run", score_threshold=0.3)
        frontier.push("https://example.com", depth=0, score=1.0)

        while not frontier.is_empty():
            url, depth = await frontier.popleft()
            # ... fetch and scrape url ...
            frontier.push(child_url, depth + 1, score=0.7)

        await frontier.save()

    Attributes:
        session_id: Stable identifier for this crawl session. Used as the
            persistence filename.
        score_threshold: Links with score below this value are never enqueued.
        pages_scraped: Number of URLs returned by popleft() so far.
    """

    def __init__(
        self,
        session_id: str,
        score_threshold: float = 0.0,
        politeness_delay: float = _POLITENESS_DELAY,
        storage_dir: str = 'frontier',
        seed_domain: str | None = None,
    ) -> None:
        """Initialise the frontier, reloading any persisted state for session_id.

        Args:
            session_id: Stable crawl session identifier.
            score_threshold: Minimum score for a URL to be enqueued.
            politeness_delay: Minimum seconds between fetches of the same host.
            storage_dir: Sub-directory under .yosoi/ for persistence files.
            seed_domain: Base domain of the seed URL; cross-domain links are
                penalised (score halved) before threshold check.
        """
        self.session_id = session_id
        self.score_threshold = score_threshold
        self.politeness_delay = politeness_delay
        self._storage_dir = Path(str(init_yosoi(storage_dir)))
        self._seed_domain = seed_domain

        # Core state — heap entries are (-score, insertion_index, url, depth)
        # Negated score so heapq (min-heap) pops highest score first.
        # insertion_index breaks ties in FIFO order.
        self._queue: list[tuple[float, int, str, int]] = []
        self._insertion_counter: int = 0
        self._visited: set[str] = set()
        self._pages_scraped: int = 0

        # Per-host last-fetch timestamp for politeness
        self._last_fetch: dict[str, float] = {}

        # Try to resume from a previous run
        self._filepath = self._storage_dir / f'{session_id}.json'
        if self._filepath.exists():
            self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def pages_scraped(self) -> int:
        """Number of URLs that have been popped and scraped so far."""
        return self._pages_scraped

    def push(self, url: str, depth: int, score: float) -> bool:
        """Enqueue a URL if it passes dedup, threshold, and domain checks.

        Args:
            url: URL to enqueue.
            depth: Crawl depth of this URL.
            score: Relevance score (0.0-1.0). Higher scores are scraped first.

        Returns:
            True if the URL was enqueued, False if rejected (duplicate,
            below threshold, or invalid).
        """
        # Cross-domain penalty — halve score for links outside the seed domain
        if self._seed_domain:
            normalised_check = normalize_url(url)
            host = urlparse(normalised_check or '').hostname or ''
            if host != self._seed_domain and not host.endswith('.' + self._seed_domain):
                score *= 0.5

        if score < self.score_threshold:
            return False

        normalised = normalize_url(url)
        if normalised is None:
            return False

        if normalised in self._visited:
            return False

        self._visited.add(normalised)
        heapq.heappush(self._queue, (-score, self._insertion_counter, normalised, depth))
        self._insertion_counter += 1
        logger.debug('Frontier.push url=%s depth=%d score=%.2f', normalised, depth, score)
        return True

    async def popleft(self) -> tuple[str, int]:
        """Return the highest-scoring (url, depth) to scrape.

        Respects per-host politeness delay. Increments pages_scraped.

        Returns:
            Tuple of (normalised_url, depth).

        Raises:
            IndexError: If the queue is empty (check is_empty() first).
        """
        _, _, url, depth = heapq.heappop(self._queue)
        self._pages_scraped += 1

        host = urlparse(url).hostname or ''
        now = time.monotonic()
        last = self._last_fetch.get(host, 0.0)
        wait = self.politeness_delay - (now - last)
        if wait > 0:
            logger.debug('Frontier politeness: waiting %.2fs for host %s', wait, host)
            await asyncio.sleep(wait)

        self._last_fetch[host] = time.monotonic()
        return url, depth

    def is_empty(self) -> bool:
        """Return True when there are no more URLs to scrape."""
        return len(self._queue) == 0

    def queue_size(self) -> int:
        """Return the number of URLs currently waiting in the queue."""
        return len(self._queue)

    def visited_count(self) -> int:
        """Return the total number of unique URLs seen (queued or already scraped)."""
        return len(self._visited)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def save(self) -> None:
        """Persist the current queue and visited set to disk.

        Writes atomically via a temp file so a crash mid-write never leaves
        a corrupt frontier file.
        """
        from yosoi.utils.files import atomic_write_json_async

        # Serialise as [score, insertion_index, url, depth] — store positive score
        data = {
            'session_id': self.session_id,
            'score_threshold': self.score_threshold,
            'seed_domain': self._seed_domain,
            'pages_scraped': self._pages_scraped,
            'insertion_counter': self._insertion_counter,
            'visited': sorted(self._visited),
            'queue': [[-neg_score, idx, url, depth] for neg_score, idx, url, depth in self._queue],
        }
        await atomic_write_json_async(self._filepath, data)
        logger.debug(
            'Frontier saved session=%s queue=%d visited=%d',
            self.session_id,
            len(self._queue),
            len(self._visited),
        )

    def _load(self) -> None:
        """Reload persisted frontier state from disk (called from __init__)."""
        try:
            data = json.loads(self._filepath.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning('Could not load frontier %s: %s', self._filepath, exc)
            return

        self._visited = set(data.get('visited', []))
        self._pages_scraped = int(data.get('pages_scraped', 0))
        self._insertion_counter = int(data.get('insertion_counter', 0))
        self._seed_domain = data.get('seed_domain')

        for entry in data.get('queue', []):
            if isinstance(entry, (list, tuple)) and len(entry) == 4:
                score, idx, url, depth = entry
                heapq.heappush(self._queue, (-float(score), int(idx), str(url), int(depth)))
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                # Legacy format: (url, depth) with no score — use 0.5 as default
                heapq.heappush(self._queue, (-0.5, self._insertion_counter, str(entry[0]), int(entry[1])))
                self._insertion_counter += 1

        logger.info(
            'Frontier resumed session=%s queue=%d visited=%d scraped=%d',
            self.session_id,
            len(self._queue),
            len(self._visited),
            self._pages_scraped,
        )
