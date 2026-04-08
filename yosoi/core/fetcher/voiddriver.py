"""Chrome-based fetchers using a persistent browser instance via voidcrawl."""

from __future__ import annotations

import time

from yosoi.core.fetcher.base import ContentAnalyzer, HTMLFetcher
from yosoi.models.results import FetchResult
from yosoi.utils.exceptions import BotDetectionError


def _import_voidcrawl():
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
        **_kwargs,
    ):
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.min_content_length = min_content_length
        self.no_sandbox = no_sandbox
        self._pool = None
        self._pool_ctx = None

    async def __aenter__(self):
        BrowserPool, BrowserConfig, PoolConfig = _import_voidcrawl()
        config = PoolConfig(
            browsers=1,
            tabs_per_browser=self.max_concurrent,
            browser=BrowserConfig(
                headless=self._headless,
                stealth=True,
                no_sandbox=self.no_sandbox,
            ),
        )
        self._pool_ctx = BrowserPool(config)
        self._pool = await self._pool_ctx.__aenter__()
        return self

    async def __aexit__(self, *exc):
        if self._pool is not None:
            await self._pool_ctx.__aexit__(*exc)
            self._pool = None

    async def close(self):
        if self._pool is not None:
            await self._pool_ctx.__aexit__(None, None, None)
            self._pool = None

    async def fetch(self, url: str) -> FetchResult:
        start = time.time()
        return await self._do_fetch(url, start, 'fetch')

    async def _do_fetch(self, url: str, start_time: float, _tier: str) -> FetchResult:
        async with self._pool.acquire() as tab:
            await tab.goto(url, timeout=float(self.timeout))
            html = await tab.content()

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


class HeadlessFetcher(_VoidCrawlFetcher):
    """Chrome fetcher running in headless mode (no visible window)."""

    _headless = True


class HeadfulFetcher(_VoidCrawlFetcher):
    """Chrome fetcher running in headful mode (visible window, best bot evasion)."""

    _headless = False
