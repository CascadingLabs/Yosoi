"""Three-tier JS fetcher: Simple HTTP → Headless Chrome → Headful Chrome.

Fetch waterfall
---------------
1. **SimpleFetcher** (plain HTTP, no Chrome)
   - On success with no JS detected → return immediately.
   - On failure **or** ``result.metadata.requires_js`` → fall through.
2. **HeadlessFetcher** (headless Chrome, fast)
   - On success → return immediately.
   - On failure (empty content, DOM timeout, hard error) → fall through.
3. **HeadfulFetcher** (visible Chrome, best bot evasion)
   - Result is returned regardless (best-effort final tier).

The winning tier for each domain is saved to .yosoi/fetch/ via
:class:`~yosoi.storage.strategy.FetchStrategyStorage`. On the next run
the waterfall is skipped and the cached tier is used immediately.

Usage (drop-in for SimpleFetcher)::

    async with JSFetcher() as fetcher:
        result = await fetcher.fetch("https://finance.yahoo.com/article")
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

from yosoi.core.fetcher.base import HTMLFetcher
from yosoi.core.fetcher.simple import SimpleFetcher
from yosoi.core.fetcher.zendriver import HeadfulFetcher, HeadlessFetcher
from yosoi.models.results import FetchResult
from yosoi.storage.strategy import FetchStrategyStorage


class JSFetcher(HTMLFetcher):
    """Three-tier JS fetcher: Simple HTTP → Headless Chrome → Headful Chrome.

    The winning tier for each domain is saved to .yosoi/fetch/ via
    FetchStrategyStorage. On the next run the waterfall is skipped
    and the cached tier is used immediately.

    Usage::

        async with JSFetcher() as fetcher:
            result = await fetcher.fetch("https://finance.yahoo.com/article")
    """

    def __init__(
        self,
        timeout: int = 30,
        rotate_user_agent: bool = True,
        use_session: bool = True,
        min_delay: float = 0.5,
        max_delay: float = 2.0,
        randomize_headers: bool = True,
        max_concurrent: int = 5,
        min_content_length: int = 500,
        browser_executable_path: str | None = None,
    ):
        """Initialise the three-tier JS fetcher."""
        self._simple = SimpleFetcher(
            timeout=timeout,
            rotate_user_agent=rotate_user_agent,
            use_session=use_session,
            min_delay=min_delay,
            max_delay=max_delay,
            randomize_headers=randomize_headers,
        )
        self._chrome_kwargs: dict = {
            'timeout': timeout,
            'min_delay': min_delay,
            'max_delay': max_delay,
            'max_concurrent': max_concurrent,
            'min_content_length': min_content_length,
            'browser_executable_path': browser_executable_path,
        }
        self._headless: HeadlessFetcher | None = None
        self._headful: HeadfulFetcher | None = None

        # In-memory cache populated from disk on __aenter__
        self._strategy_cache: dict[str, str] = {}
        self._strategy_storage = FetchStrategyStorage()

        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> JSFetcher:
        """Start the simple fetcher eagerly; Chrome tiers start lazily."""
        await self._simple.__aenter__()
        self._strategy_cache = self._strategy_storage.load_all()
        self.logger.info(
            'JSFetcher ready (simple tier active, %d domain strategies cached)',
            len(self._strategy_cache),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context manager and close all tiers."""
        await self.close()

    async def close(self) -> None:
        """Close all active fetcher tiers."""
        await self._simple.close()
        if self._headless is not None:
            await self._headless.close()
            self._headless = None
        if self._headful is not None:
            await self._headful.close()
            self._headful = None

    # ------------------------------------------------------------------
    # Strategy cache helpers
    # ------------------------------------------------------------------

    def _preferred_tier(self, domain: str) -> str | None:
        """Return the cached tier for *domain*, or None if unknown."""
        return self._strategy_cache.get(domain)

    def _record_success(self, domain: str, tier: str) -> None:
        """Save the winning tier for *domain* if it changed."""
        if self._strategy_cache.get(domain) != tier:
            self._strategy_cache[domain] = tier
            self._strategy_storage.save(domain, tier)
            self.logger.info('Fetch strategy cached: %s -> %s', domain, tier)

    # ------------------------------------------------------------------
    # Lazy Chrome tier startup
    # ------------------------------------------------------------------

    async def _ensure_headless(self) -> HeadlessFetcher:
        if self._headless is None:
            self.logger.info('Starting headless Chrome (tier 2)...')
            self._headless = HeadlessFetcher(**self._chrome_kwargs)
            await self._headless.__aenter__()
        return self._headless

    async def _ensure_headful(self) -> HeadfulFetcher:
        if self._headful is None:
            self.logger.info('Starting headful Chrome (tier 3)...')
            self._headful = HeadfulFetcher(**self._chrome_kwargs)
            await self._headful.__aenter__()
        return self._headful

    # ------------------------------------------------------------------
    # Public fetch interface
    # ------------------------------------------------------------------

    async def fetch(self, url: str) -> FetchResult:
        """Fetch a page using the Simple → Headless → Headful waterfall.

        If a winning tier is cached for this domain the waterfall is
        skipped and that tier is used directly.

        Args:
            url: The URL to fetch.

        Returns:
            FetchResult with rendered HTML and metadata on success.

        Raises:
            BotDetectionError: If bot-detection indicators are found.
        """
        start_time = time.time()
        domain = urlparse(url).netloc.replace('www.', '')
        cached_tier = self._preferred_tier(domain)

        # ── Fast path: cached tier ───────────────────────────────────────────
        if cached_tier == 'simple':
            result = await self._simple.fetch(url)
            if result.html:
                return result
            self.logger.info('Cached simple tier failed for %s — running waterfall', domain)

        elif cached_tier == 'headless':
            headless = await self._ensure_headless()
            result = await headless._do_fetch(url, start_time, 'headless')
            if result.html:
                return result
            self.logger.info('Cached headless tier failed for %s — trying headful', domain)
            headful = await self._ensure_headful()
            result = await headful._do_fetch(url, start_time, 'headful')
            if result.html:
                self._record_success(domain, 'headful')
            return result

        elif cached_tier == 'headful':
            headful = await self._ensure_headful()
            return await headful._do_fetch(url, start_time, 'headful')

        # ── Waterfall: no cache for this domain ──────────────────────────────

        # Tier 1: Simple
        result = await self._simple.fetch(url)
        if result.html and not result.requires_js:
            self._record_success(domain, 'simple')
            return result

        if result.html and result.requires_js:
            self.logger.info('JS detected on %s — escalating to headless Chrome', domain)
        else:
            self.logger.info(
                'Simple fetch failed for %s (%s) — escalating to headless Chrome',
                domain,
                result.block_reason or 'unknown',
            )

        # Tier 2: Headless
        headless = await self._ensure_headless()
        result = await headless._do_fetch(url, start_time, 'headless')
        if result.html:
            self._record_success(domain, 'headless')
            return result

        self.logger.info(
            'Headless failed for %s (%s) — escalating to headful Chrome',
            domain,
            result.block_reason or 'unknown',
        )

        # Tier 3: Headful (best effort)
        headful = await self._ensure_headful()
        result = await headful._do_fetch(url, start_time, 'headful')
        if result.html:
            self._record_success(domain, 'headful')
        return result
