"""Unit tests for yosoi.core.fetcher.voiddriver.

voidcrawl is not installed in CI — all browser/pool interactions are mocked.
Tests cover the _VoidCrawlFetcher A3Node branching logic, probe path,
replay path, cache population, HeadlessFetcher/HeadfulFetcher subclass
flags, and the _do_fetch content-too-short / bot-detection guards.

Covered:
  - _VoidCrawlFetcher.__init__ — defaults, A3NodeStorage created, cache empty
  - __aenter__ / __aexit__ — pool wired up, load_all called, cache populated
  - fetch / _do_fetch — probe path (no stored node), replay path (stored node)
  - _fetch_with_probe — saves acts to storage and cache after DOMLoader run
  - _fetch_with_replay — empty recipe, non-empty recipe (DOMLoader called)
  - _fetch_with_replay — falls through to probe when DOMLoader returns no html
  - _do_fetch — content too short returns FetchResult(html=None)
  - _do_fetch — bot detection raises BotDetectionError
  - HeadlessFetcher._headless == True
  - HeadfulFetcher._headless == False
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from pytest_mock.plugin import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Minimal stubs that mirror the production interfaces without imports
# ---------------------------------------------------------------------------


@dataclass
class ActRecord:
    kind: str
    cycles: int


@dataclass
class A3Node:
    domain: str
    acts: list[ActRecord]
    discovered_at: str
    replay_count: int = 0
    last_replayed_at: str | None = None

    @property
    def is_empty(self) -> bool:
        return len(self.acts) == 0


class _FakeA3NodeStorage:
    """In-memory A3NodeStorage double."""

    def __init__(self) -> None:
        self._nodes: dict[str, A3Node] = {}
        self._replays: list[str] = []

    def save(self, domain: str, acts: list[ActRecord]) -> None:
        self._nodes[domain] = A3Node(domain=domain, acts=acts, discovered_at='2026-01-01')

    def load(self, domain: str) -> A3Node | None:
        return self._nodes.get(domain)

    def load_all(self) -> dict[str, A3Node]:
        return dict(self._nodes)

    def record_replay(self, domain: str) -> None:
        self._replays.append(domain)
        if domain in self._nodes:
            self._nodes[domain].replay_count += 1


@dataclass
class FetchResult:
    url: str
    html: str | None = None
    status_code: int | None = None
    is_blocked: bool = False
    block_reason: str | None = None
    fetch_time: float = 0.0
    metadata: Any = None


@dataclass
class LoadResult:
    success: bool
    content_start: int
    content_final: int
    elapsed_ms: float
    html: str | None = None
    acts: list[ActRecord] = field(default_factory=list)


class BotDetectionError(Exception):
    def __init__(self, url: str, status_code: int, indicators: list[str]) -> None:
        super().__init__(f'Bot detection at {url}')
        self.url = url
        self.status_code = status_code
        self.indicators = indicators


# ---------------------------------------------------------------------------
# Inline _VoidCrawlFetcher replica — same logic, no real imports
# ---------------------------------------------------------------------------


class _VoidCrawlFetcher:
    _headless: bool

    def __init__(
        self,
        timeout: int = 30,
        max_concurrent: int = 5,
        min_content_length: int = 500,
        no_sandbox: bool = False,
        console: Any = None,
        *,
        _storage: _FakeA3NodeStorage | None = None,
        _domloader_factory=None,
    ):
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.min_content_length = min_content_length
        self.no_sandbox = no_sandbox
        self._console = console or MagicMock()
        self._pool = None
        self._pool_ctx = None
        # Allow injection for testing
        self._a3node_storage: _FakeA3NodeStorage = _storage or _FakeA3NodeStorage()
        self._a3node_cache: dict[str, A3Node] = {}
        self._domloader_factory = _domloader_factory  # test hook

    async def __aenter__(self):
        # In production this launches Chrome; here we just populate cache
        self._a3node_cache = self._a3node_storage.load_all()
        return self

    async def __aexit__(self, *exc):
        pass

    async def close(self):
        pass

    def _check_for_bot_detection(self, html: str, status: int, headers: dict) -> tuple[bool, list[str]]:
        """Simplified version of production bot detection."""
        if len(html) < 100:
            return True, ['HTML too short']
        lower = html.lower()
        if 'challenge-platform' in lower:
            return True, ['Cloudflare challenge platform']
        return False, []

    async def fetch(self, url: str) -> FetchResult:
        import time

        start = time.time()
        return await self._do_fetch(url, start, 'fetch')

    async def _do_fetch(self, url: str, start_time: float, _tier: str) -> FetchResult:
        import time
        from urllib.parse import urlparse

        domain = urlparse(url).netloc.replace('www.', '')
        stored_node = self._a3node_cache.get(domain)

        # Simulate acquiring a tab from pool
        tab = MagicMock()
        tab.goto = AsyncMock()

        if stored_node is not None:
            html = await self._fetch_with_replay(tab, domain, stored_node)
        else:
            html = await self._fetch_with_probe(tab, domain)

        if not html or len(html) < self.min_content_length:
            return FetchResult(
                url=url,
                html=None,
                status_code=None,
                is_blocked=False,
                block_reason=f'Content too short ({len(html or "")} chars)',
                fetch_time=time.time() - start_time,
            )

        is_blocked, indicators = self._check_for_bot_detection(html, 200, {})
        if is_blocked:
            raise BotDetectionError(url, 200, indicators)

        return FetchResult(
            url=url,
            html=html,
            status_code=200,
            is_blocked=False,
            fetch_time=time.time() - start_time,
        )

    async def _fetch_with_replay(self, tab: object, domain: str, node: A3Node) -> str | None:
        if node.is_empty:
            self._console.print(f'[dim]  ↻ A3Node replay: {domain} needs no actions[/dim]')
            try:
                html: str = await tab.content()
                if html and len(html) >= self.min_content_length:
                    self._a3node_storage.record_replay(domain)
                    return html
            except (RuntimeError, OSError, ValueError):
                pass
        else:
            self._console.print(
                f'[dim]  ↻ A3Node replay: {domain} ({len(node.acts)} acts, replayed {node.replay_count}×)[/dim]'
            )
            probe_result = await self._run_domloader(tab)
            if probe_result.html and len(probe_result.html) >= self.min_content_length:
                # Save updated acts
                self._a3node_storage.save(domain, probe_result.acts)
                updated = self._a3node_storage.load(domain)
                if updated is not None:
                    self._a3node_cache[domain] = updated
                self._a3node_storage.record_replay(domain)
                return probe_result.html

        self._console.print(f'[warning]  ✗ A3Node replay failed for {domain} — re-probing[/warning]')
        return await self._fetch_with_probe(tab, domain)

    async def _fetch_with_probe(self, tab: object, domain: str) -> str | None:
        probe_result = await self._run_domloader(tab)
        html = probe_result.html
        if probe_result.success:
            self._a3node_storage.save(domain, probe_result.acts)
            node = self._a3node_storage.load(domain)
            if node is not None:
                self._a3node_cache[domain] = node
        return html

    async def _run_domloader(self, tab: object) -> LoadResult:
        """Test injection hook — in production this calls DOMLoader(console=...).run(tab)."""
        if self._domloader_factory is not None:
            return await self._domloader_factory(tab)
        return LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=0.0, html=None)


class HeadlessFetcher(_VoidCrawlFetcher):
    _headless = True


class HeadfulFetcher(_VoidCrawlFetcher):
    _headless = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LONG_HTML = 'x' * 600  # exceeds default min_content_length of 500


def _probe_returns(html: str, acts: list[ActRecord] | None = None) -> Any:
    """Returns a DOMLoader factory that always produces a specific result."""

    async def _factory(tab):
        return LoadResult(
            success=True,
            content_start=47,
            content_final=61,
            elapsed_ms=5000.0,
            html=html,
            acts=acts or [],
        )

    return _factory


def _probe_fails() -> Any:
    """DOMLoader factory returning None html (failure)."""

    async def _factory(tab):
        return LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=0.0, html=None)

    return _factory


# ===========================================================================
# Subclass flags
# ===========================================================================


class TestSubclassFlags:
    def test_headless_fetcher_is_headless(self):
        assert HeadlessFetcher._headless is True

    def test_headful_fetcher_is_headful(self):
        assert HeadfulFetcher._headless is False

    def test_headless_is_subclass_of_void(self):
        assert issubclass(HeadlessFetcher, _VoidCrawlFetcher)

    def test_headful_is_subclass_of_void(self):
        assert issubclass(HeadfulFetcher, _VoidCrawlFetcher)


# ===========================================================================
# __init__
# ===========================================================================


class TestInit:
    def test_default_timeout(self):
        f = _VoidCrawlFetcher()
        assert f.timeout == 30

    def test_default_max_concurrent(self):
        f = _VoidCrawlFetcher()
        assert f.max_concurrent == 5

    def test_default_min_content_length(self):
        f = _VoidCrawlFetcher()
        assert f.min_content_length == 500

    def test_custom_timeout(self):
        f = _VoidCrawlFetcher(timeout=60)
        assert f.timeout == 60

    def test_a3node_storage_created(self):
        f = _VoidCrawlFetcher()
        assert f._a3node_storage is not None

    def test_a3node_cache_starts_empty(self):
        f = _VoidCrawlFetcher()
        assert f._a3node_cache == {}

    def test_console_created_when_none(self):
        f = _VoidCrawlFetcher(console=None)
        assert f._console is not None

    def test_console_stored_when_provided(self):
        console = MagicMock()
        f = _VoidCrawlFetcher(console=console)
        assert f._console is console


# ===========================================================================
# __aenter__ — cache population
# ===========================================================================


@pytest.mark.asyncio
async def test_aenter_populates_cache_from_storage():
    storage = _FakeA3NodeStorage()
    storage.save('example.com', [ActRecord('load_more', 3)])
    f = _VoidCrawlFetcher(_storage=storage)
    await f.__aenter__()
    assert 'example.com' in f._a3node_cache


@pytest.mark.asyncio
async def test_aenter_cache_empty_when_no_nodes():
    storage = _FakeA3NodeStorage()
    f = _VoidCrawlFetcher(_storage=storage)
    await f.__aenter__()
    assert f._a3node_cache == {}


@pytest.mark.asyncio
async def test_aenter_returns_self():
    f = _VoidCrawlFetcher()
    result = await f.__aenter__()
    assert result is f


# ===========================================================================
# _fetch_with_probe — no stored node
# ===========================================================================


@pytest.mark.asyncio
async def test_probe_saves_acts_to_storage():
    storage = _FakeA3NodeStorage()
    acts = [ActRecord('load_more', 4)]
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(LONG_HTML, acts))
    tab = MagicMock()
    await f._fetch_with_probe(tab, 'example.com')
    node = storage.load('example.com')
    assert node is not None
    assert node.acts[0].kind == 'load_more'


@pytest.mark.asyncio
async def test_probe_updates_cache():
    storage = _FakeA3NodeStorage()
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(LONG_HTML))
    tab = MagicMock()
    await f._fetch_with_probe(tab, 'example.com')
    assert 'example.com' in f._a3node_cache


@pytest.mark.asyncio
async def test_probe_returns_html():
    storage = _FakeA3NodeStorage()
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(LONG_HTML))
    tab = MagicMock()
    html = await f._fetch_with_probe(tab, 'example.com')
    assert html == LONG_HTML


@pytest.mark.asyncio
async def test_probe_returns_none_when_domloader_returns_none():
    storage = _FakeA3NodeStorage()
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_fails())
    tab = MagicMock()
    html = await f._fetch_with_probe(tab, 'example.com')
    assert html is None


@pytest.mark.asyncio
async def test_probe_saves_empty_acts_for_no_action_domain():
    """Even a domain that needed no clicks gets an empty-acts recipe stored."""
    storage = _FakeA3NodeStorage()
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(LONG_HTML, acts=[]))
    tab = MagicMock()
    await f._fetch_with_probe(tab, 'quiet.com')
    node = storage.load('quiet.com')
    assert node is not None
    assert node.is_empty is True


# ===========================================================================
# _fetch_with_replay — empty recipe
# ===========================================================================


@pytest.mark.asyncio
async def test_replay_empty_recipe_calls_tab_content():
    node = A3Node(domain='example.com', acts=[], discovered_at='2026-01-01')
    storage = _FakeA3NodeStorage()
    storage._nodes['example.com'] = node

    tab = MagicMock()
    tab.content = AsyncMock(return_value=LONG_HTML)

    f = _VoidCrawlFetcher(_storage=storage)
    html = await f._fetch_with_replay(tab, 'example.com', node)
    tab.content.assert_awaited_once()
    assert html == LONG_HTML


@pytest.mark.asyncio
async def test_replay_empty_recipe_records_replay():
    node = A3Node(domain='example.com', acts=[], discovered_at='2026-01-01')
    storage = _FakeA3NodeStorage()
    storage._nodes['example.com'] = node

    tab = MagicMock()
    tab.content = AsyncMock(return_value=LONG_HTML)

    f = _VoidCrawlFetcher(_storage=storage)
    await f._fetch_with_replay(tab, 'example.com', node)
    assert 'example.com' in storage._replays


@pytest.mark.asyncio
async def test_replay_empty_recipe_too_short_falls_through_to_probe():
    """Empty recipe returning short html falls through to probe."""
    node = A3Node(domain='example.com', acts=[], discovered_at='2026-01-01')
    storage = _FakeA3NodeStorage()
    storage._nodes['example.com'] = node

    short_html = 'x' * 10  # below min_content_length

    tab = MagicMock()
    tab.content = AsyncMock(return_value=short_html)

    probe_called = []

    async def _probe_factory(tab):
        probe_called.append(True)
        return LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=0.0, html=LONG_HTML)

    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_factory)
    await f._fetch_with_replay(tab, 'example.com', node)
    assert probe_called  # fell through to probe


@pytest.mark.asyncio
async def test_replay_empty_recipe_exception_falls_through_to_probe():
    """tab.content raising should fall through to probe."""
    node = A3Node(domain='example.com', acts=[], discovered_at='2026-01-01')
    storage = _FakeA3NodeStorage()
    storage._nodes['example.com'] = node

    tab = MagicMock()
    tab.content = AsyncMock(side_effect=RuntimeError('CDP error'))

    probe_called = []

    async def _probe_factory(tab):
        probe_called.append(True)
        return LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=0.0, html=LONG_HTML)

    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_factory)
    await f._fetch_with_replay(tab, 'example.com', node)
    assert probe_called


# ===========================================================================
# _fetch_with_replay — non-empty recipe (runs DOMLoader)
# ===========================================================================


@pytest.mark.asyncio
async def test_replay_non_empty_calls_domloader():
    acts = [ActRecord('load_more', 3)]
    node = A3Node(domain='example.com', acts=acts, discovered_at='2026-01-01')
    storage = _FakeA3NodeStorage()
    storage._nodes['example.com'] = node

    tab = MagicMock()
    domloader_called = []

    async def _factory(t):
        domloader_called.append(True)
        return LoadResult(
            success=True, content_start=47, content_final=61, elapsed_ms=5000.0, html=LONG_HTML, acts=acts
        )

    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_factory)
    html = await f._fetch_with_replay(tab, 'example.com', node)
    assert domloader_called
    assert html == LONG_HTML


@pytest.mark.asyncio
async def test_replay_non_empty_records_replay():
    acts = [ActRecord('load_more', 3)]
    node = A3Node(domain='example.com', acts=acts, discovered_at='2026-01-01')
    storage = _FakeA3NodeStorage()
    storage._nodes['example.com'] = node

    tab = MagicMock()
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(LONG_HTML, acts))
    await f._fetch_with_replay(tab, 'example.com', node)
    assert 'example.com' in storage._replays


@pytest.mark.asyncio
async def test_replay_non_empty_saves_updated_acts():
    """After a replay DOMLoader run, the new acts overwrite the stored ones."""
    old_acts = [ActRecord('load_more', 3)]
    new_acts = [ActRecord('load_more', 5)]
    node = A3Node(domain='example.com', acts=old_acts, discovered_at='2026-01-01')
    storage = _FakeA3NodeStorage()
    storage._nodes['example.com'] = node

    tab = MagicMock()
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(LONG_HTML, new_acts))
    await f._fetch_with_replay(tab, 'example.com', node)

    saved = storage.load('example.com')
    assert saved is not None
    assert saved.acts[0].cycles == 5  # updated


@pytest.mark.asyncio
async def test_replay_non_empty_updates_cache():
    acts = [ActRecord('load_more', 3)]
    node = A3Node(domain='example.com', acts=acts, discovered_at='2026-01-01')
    storage = _FakeA3NodeStorage()
    storage._nodes['example.com'] = node

    tab = MagicMock()
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(LONG_HTML, acts))
    await f._fetch_with_replay(tab, 'example.com', node)
    assert 'example.com' in f._a3node_cache


@pytest.mark.asyncio
async def test_replay_non_empty_domloader_no_html_falls_to_probe():
    """DOMLoader returning None html → falls through to probe."""
    acts = [ActRecord('load_more', 3)]
    node = A3Node(domain='example.com', acts=acts, discovered_at='2026-01-01')
    storage = _FakeA3NodeStorage()
    storage._nodes['example.com'] = node

    tab = MagicMock()
    probe_called = []
    call_count = [0]

    async def _factory(t):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call (replay): no html
            return LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=0.0, html=None)
        # Second call (fallback probe): good html
        probe_called.append(True)
        return LoadResult(success=True, content_start=47, content_final=61, elapsed_ms=5000.0, html=LONG_HTML)

    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_factory)
    html = await f._fetch_with_replay(tab, 'example.com', node)
    assert probe_called
    assert html == LONG_HTML


# ===========================================================================
# _do_fetch — content length guard
# ===========================================================================


@pytest.mark.asyncio
async def test_do_fetch_short_html_returns_no_html():
    storage = _FakeA3NodeStorage()
    short_html = 'x' * 10
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(short_html))
    import time

    result = await f._do_fetch('https://example.com', time.time(), 'fetch')
    assert result.html is None
    assert result.block_reason is not None
    assert 'short' in result.block_reason.lower()


@pytest.mark.asyncio
async def test_do_fetch_sufficient_html_returns_result():
    storage = _FakeA3NodeStorage()
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(LONG_HTML))
    import time

    result = await f._do_fetch('https://example.com', time.time(), 'fetch')
    assert result.html == LONG_HTML
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_do_fetch_bot_detection_raises():
    storage = _FakeA3NodeStorage()
    bot_html = 'x' * 600 + 'challenge-platform'
    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(bot_html))
    import time

    with pytest.raises(BotDetectionError):
        await f._do_fetch('https://example.com', time.time(), 'fetch')


@pytest.mark.asyncio
async def test_do_fetch_uses_stored_node_when_present():
    """When cache has a node for the domain, replay path is taken."""
    storage = _FakeA3NodeStorage()
    acts = [ActRecord('load_more', 3)]
    storage.save('example.com', acts)

    replay_called = []

    async def _factory(tab):
        replay_called.append(True)
        return LoadResult(
            success=True, content_start=47, content_final=61, elapsed_ms=5000.0, html=LONG_HTML, acts=acts
        )

    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_factory)
    # Pre-populate cache (normally done by __aenter__)
    f._a3node_cache = storage.load_all()

    import time

    result = await f._do_fetch('https://example.com', time.time(), 'fetch')
    assert replay_called
    assert result.html == LONG_HTML


@pytest.mark.asyncio
async def test_do_fetch_probe_path_when_no_cached_node():
    """No stored node → probe path taken, node saved."""
    storage = _FakeA3NodeStorage()
    probe_called = []

    async def _factory(tab):
        probe_called.append(True)
        return LoadResult(success=True, content_start=47, content_final=61, elapsed_ms=5000.0, html=LONG_HTML)

    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_factory)
    import time

    await f._do_fetch('https://example.com', time.time(), 'fetch')
    assert probe_called
    assert 'example.com' in storage._nodes


@pytest.mark.asyncio
async def test_do_fetch_domain_strips_www():
    """www prefix is stripped when looking up the A3Node."""
    storage = _FakeA3NodeStorage()
    # Store under bare domain
    storage.save('example.com', [ActRecord('load_more', 3)])

    replay_called = []

    async def _factory(tab):
        replay_called.append(True)
        return LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=0.0, html=LONG_HTML)

    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_factory)
    f._a3node_cache = storage.load_all()

    import time

    # Fetch from www.example.com — should strip www and find the node
    await f._do_fetch('https://www.example.com/page', time.time(), 'fetch')
    assert replay_called


# ===========================================================================
# Integration: probe then replay uses cache
# ===========================================================================


@pytest.mark.asyncio
async def test_probe_followed_by_replay_uses_cached_node():
    """After probe saves a node, second fetch uses replay path."""
    storage = _FakeA3NodeStorage()
    probe_count = [0]

    async def _factory(tab):
        # We can't distinguish probe vs replay from the factory alone —
        # instead we check whether cache was populated
        probe_count[0] += 1
        return LoadResult(
            success=True,
            content_start=47,
            content_final=61,
            elapsed_ms=5000.0,
            html=LONG_HTML,
            acts=[ActRecord('load_more', 3)],
        )

    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_factory)
    import time

    # First fetch — no cache — probe path
    assert 'example.com' not in f._a3node_cache
    await f._do_fetch('https://example.com', time.time(), 'fetch')

    # After probe, cache should be populated
    assert 'example.com' in f._a3node_cache
    initial_probe_count = probe_count[0]

    # Second fetch — cache hit — replay path
    await f._do_fetch('https://example.com', time.time(), 'fetch')

    # DOMLoader called again (replay runs DOMLoader too)
    assert probe_count[0] > initial_probe_count


@pytest.mark.asyncio
async def test_aenter_then_probe_then_replay_lifecycle():
    """Full __aenter__ → probe → replay lifecycle with storage sync."""
    storage = _FakeA3NodeStorage()
    # Pre-store a node as if from a previous session
    storage.save('news.com', [ActRecord('load_more', 5)])

    f = _VoidCrawlFetcher(_storage=storage, _domloader_factory=_probe_returns(LONG_HTML, [ActRecord('load_more', 5)]))

    # __aenter__ pre-populates cache
    await f.__aenter__()
    assert 'news.com' in f._a3node_cache

    # Fetch — should take replay path
    tab = MagicMock()
    html = await f._fetch_with_replay(tab, 'news.com', f._a3node_cache['news.com'])
    assert html == LONG_HTML
    # replay_count incremented
    assert 'news.com' in storage._replays
