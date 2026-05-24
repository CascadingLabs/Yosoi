"""Chrome-based fetchers using a persistent browser instance via voidcrawl.

A3Node replay
-------------
On each fetch the caller (_VoidCrawlFetcher) checks A3NodeStorage for a
stored stability recipe. If one exists, the acts are replayed in order
before capturing HTML — skipping the full probe phase entirely.

If replay produces less content than the stored recipe previously achieved
(or the recipe is empty / no acts needed), the result is accepted as-is.

After any full probe run (no stored node, or replay failed), the new acts
are saved via A3NodeStorage so the next visit skips the probe.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

from rich.console import Console

from yosoi.core.fetcher.base import ContentAnalyzer, HTMLFetcher
from yosoi.core.fetcher.dom import DOMLoader
from yosoi.models.results import FetchResult
from yosoi.storage.a3node import A3Node, A3NodeStorage
from yosoi.utils.exceptions import BotDetectionError

logger = logging.getLogger(__name__)


def _import_voidcrawl() -> tuple[Any, Any, Any]:
    try:
        from voidcrawl import BrowserConfig, BrowserPool, PoolConfig

        return BrowserPool, BrowserConfig, PoolConfig
    except ImportError as e:
        raise ImportError(
            'voidcrawl is required for browser-based fetching. '
            'Install it with: uv add voidcrawl\n'
            'Or build from source: https://github.com/CascadingLabs/VoidCrawl'
        ) from e


class _VoidCrawlFetcher(HTMLFetcher):
    _headless: bool

    def __init__(
        self,
        timeout: int = 30,
        max_concurrent: int = 5,
        min_content_length: int = 500,
        no_sandbox: bool = False,
        console: Console | None = None,
        **_kwargs: Any,
    ) -> None:
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.min_content_length = min_content_length
        self.no_sandbox = no_sandbox
        self._console = console or Console()
        self._pool: Any = None
        self._pool_ctx: Any = None
        self._a3node_storage = A3NodeStorage()
        # Pre-populate in-memory cache at startup (mirrors FetchStrategyStorage pattern)
        self._a3node_cache: dict[str, A3Node] = {}

    async def __aenter__(self) -> _VoidCrawlFetcher:
        BrowserPool, BrowserConfig, PoolConfig = _import_voidcrawl()
        config = PoolConfig(
            browsers=1,
            tabs_per_browser=self.max_concurrent,
            tab_max_idle_secs=300,
            browser=BrowserConfig(
                headless=self._headless,
                stealth=True,
                no_sandbox=self.no_sandbox,
            ),
        )
        self._pool_ctx = BrowserPool(config)
        self._pool = await self._pool_ctx.__aenter__()
        self._a3node_cache = self._a3node_storage.load_all()
        logger.info('VoidCrawl fetcher ready (%d A3Nodes cached)', len(self._a3node_cache))
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._pool is not None:
            await self._pool_ctx.__aexit__(*exc)
            self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool_ctx.__aexit__(None, None, None)
            self._pool = None

    async def fetch(self, url: str) -> FetchResult:
        start = time.time()
        return await self._do_fetch(url, start, 'fetch')

    async def _do_fetch(
        self,
        url: str,
        start_time: float,
        _tier: str,
    ) -> FetchResult:
        domain = urlparse(url).netloc.replace('www.', '')
        stored_node = self._a3node_cache.get(domain)

        async with self._pool.acquire() as tab:
            await tab.goto(url, timeout=float(self.timeout))

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

        metadata = ContentAnalyzer.analyze(html)
        return FetchResult(
            url=url,
            html=html,
            status_code=200,
            is_blocked=False,
            fetch_time=time.time() - start_time,
            metadata=metadata,
        )

    async def _fetch_with_replay(self, tab: Any, domain: str, node: A3Node) -> str | None:
        if node.is_empty:
            self._console.print(f'[dim]  ↻ A3Node replay: {domain} needs no actions[/dim]')
            try:
                html: str = await tab.content()
                if html and len(html) >= self.min_content_length:
                    self._a3node_storage.record_replay(domain)
                    return html
            except (RuntimeError, OSError, ValueError) as exc:
                logger.debug('A3Node empty-recipe content capture failed: %s', exc)
        else:
            self._console.print(
                f'[dim]  ↻ A3Node replay: {domain} ({len(node.acts)} acts, replayed {node.replay_count}×)[/dim]'
            )
            probe_result = await DOMLoader(console=self._console).run(tab)
            if probe_result.success:
                self._a3node_storage.save(domain, probe_result.acts)
                _updated = self._a3node_storage.load(domain)
                if _updated is not None:
                    self._a3node_cache[domain] = _updated
            return probe_result.html

        self._console.print(f'[warning]  ✗ A3Node replay failed for {domain} — re-probing[/warning]')
        return await self._fetch_with_probe(tab, domain)

    async def _fetch_with_probe(self, tab: object, domain: str) -> str | None:
        """Run the full DOMLoader probe and persist the resulting recipe."""
        probe_result = await DOMLoader(console=self._console).run(tab)
        html = probe_result.html

        # Persist the acts regardless of content length — even "no action needed"
        # is a valid and useful recipe to store
        if probe_result.success:
            self._a3node_storage.save(domain, probe_result.acts)
            # Update in-memory cache
            node = self._a3node_storage.load(domain)
            if node is not None:
                self._a3node_cache[domain] = node
                verb = 'stored (no actions needed)' if node.is_empty else f'stored ({len(node.acts)} acts)'
                self._console.print(f'[success]  ✓ A3Node {verb} for {domain}[/success]')

        return html


class HeadlessFetcher(_VoidCrawlFetcher):
    """Chrome fetcher running in headless mode (no visible window)."""

    _headless = True


class HeadfulFetcher(_VoidCrawlFetcher):
    """Chrome fetcher running in headful mode (visible window, best bot evasion)."""

    _headless = False
