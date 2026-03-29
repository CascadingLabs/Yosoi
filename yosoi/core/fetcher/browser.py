"""Browser-based HTML fetcher using void_crawl (Rust CDP bindings).

Renders JavaScript-heavy pages by controlling a real Chromium instance.
Falls back gracefully with a clear error if void_crawl is not installed.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from yosoi.core.fetcher.base import ContentAnalyzer, HTMLFetcher
from yosoi.models.results import FetchResult
from yosoi.utils.exceptions import BotDetectionError

try:
    from yosoi.vc import PoolConfig
    from yosoi.vc import create_pool as _create_pool

    _HAS_BROWSER = True
except Exception:  # noqa: BLE001 — void_crawl may not be installed
    _HAS_BROWSER = False

if TYPE_CHECKING:
    from void_crawl import BrowserPool as BrowserPoolType

logger = logging.getLogger(__name__)


class BrowserFetcher(HTMLFetcher):
    """Fetch HTML by rendering pages in a headless Chromium browser.

    Uses a :class:`BrowserPool` to recycle tabs across requests instead of
    launching a new browser per fetch.  When no pool is provided one is
    created lazily from environment variables on first use.

    Requires the ``yosoi-driver`` native extension (install via
    ``cd void_crawl && ./build.sh``).

    Attributes:
        headless: Whether to run the browser headless.
        stealth: Whether to enable anti-detection measures.
        no_sandbox: Whether to disable the Chrome sandbox.
        proxy: Optional proxy URL.
        chrome_executable: Optional path to Chrome binary.
        wait_after_load_ms: Extra time (ms) to wait after load for JS rendering.

    """

    def __init__(
        self,
        headless: bool = True,
        stealth: bool = True,
        no_sandbox: bool = False,
        proxy: str | None = None,
        chrome_executable: str | None = None,
        wait_after_load_ms: int = 0,
        pool: BrowserPoolType | None = None,
    ):
        """Initialize the browser fetcher.

        Args:
            headless: If True, run browser without visible window.
            stealth: If True, apply anti-detection patches.
            no_sandbox: If True, disable Chrome sandbox (needed in containers).
            proxy: Optional proxy server URL.
            chrome_executable: Optional path to Chrome/Chromium binary.
            wait_after_load_ms: Extra wait time in ms after page load event.
            pool: Optional pre-configured BrowserPool. If None, one is created
                from environment variables on first use.

        Raises:
            ImportError: If void_crawl native extension is not installed.

        """
        if not _HAS_BROWSER:
            raise ImportError('void_crawl is not installed. Build it with: cd void_crawl && ./build.sh')

        self.headless = headless
        self.stealth = stealth
        self.no_sandbox = no_sandbox
        self.proxy = proxy
        self.chrome_executable = chrome_executable
        self.wait_after_load_ms = wait_after_load_ms

        self._pool: BrowserPoolType | None = pool
        self._owns_pool: bool = pool is None

    async def _ensure_pool(self) -> BrowserPoolType:
        """Lazily create and warm up a pool if one hasn't been provided."""
        if self._pool is None:
            cfg = PoolConfig(headless=self.headless, no_sandbox=self.no_sandbox)
            self._pool = await _create_pool(cfg)
            await self._pool.warmup()
            self._owns_pool = True
        return self._pool

    async def __aenter__(self) -> BrowserFetcher:
        """Warm up the pool (or create one)."""
        await self._ensure_pool()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Close the pool if we own it."""
        await self.close()

    async def close(self) -> None:
        """Close the pool if this fetcher owns it."""
        if self._owns_pool and self._pool is not None:
            await self._pool.__aexit__(None, None, None)
            self._pool = None

    async def fetch(self, url: str) -> FetchResult:
        """Fetch HTML by navigating a pooled browser tab to the URL.

        Args:
            url: URL to fetch.

        Returns:
            FetchResult with rendered HTML, metadata, and status.

        Raises:
            BotDetectionError: If bot detection is triggered.
            RuntimeError: If browser session is not started.

        """
        pool = await self._ensure_pool()

        start_time = time.time()

        try:
            async with await pool.acquire() as tab:
                await tab.navigate(url)

                # Optional extra wait for JS rendering
                if self.wait_after_load_ms > 0:
                    import asyncio

                    await asyncio.sleep(self.wait_after_load_ms / 1000.0)

                html = await tab.content()

        except (RuntimeError, OSError, ConnectionError) as e:
            fetch_time = time.time() - start_time
            return FetchResult(
                url=url,
                html=None,
                status_code=None,
                is_blocked=False,
                block_reason=str(e),
                fetch_time=fetch_time,
            )

        fetch_time = time.time() - start_time

        if not html or len(html) < 100:
            return FetchResult(
                url=url,
                html=None,
                status_code=200,
                is_blocked=True,
                block_reason='Response too short or empty',
                fetch_time=fetch_time,
            )

        # Check for bot detection patterns
        is_blocked, indicators = self._check_for_bot_detection(html, 200)

        if is_blocked:
            logger.warning(
                'Bot detection triggered for %s: %s',
                url,
                ', '.join(indicators),
            )
            raise BotDetectionError(url, 200, indicators)

        metadata = ContentAnalyzer.analyze(html)

        return FetchResult(
            url=url,
            html=html,
            status_code=200,
            is_blocked=False,
            fetch_time=fetch_time,
            metadata=metadata,
        )
