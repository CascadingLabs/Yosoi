"""Browser-based HTML fetcher using yosoi_driver (Rust CDP bindings).

Renders JavaScript-heavy pages by controlling a real Chromium instance.
Falls back gracefully with a clear error if yosoi_driver is not installed.
"""

from __future__ import annotations

import logging
import time

from yosoi.core.fetcher.base import ContentAnalyzer, HTMLFetcher
from yosoi.models.results import FetchResult
from yosoi.utils.exceptions import BotDetectionError

try:
    from yosoi_driver import BrowserSession, Page  # type: ignore[import-untyped]

    _HAS_BROWSER = True
except ImportError:
    _HAS_BROWSER = False

logger = logging.getLogger(__name__)


class BrowserFetcher(HTMLFetcher):
    """Fetch HTML by rendering pages in a headless Chromium browser.

    Requires the ``yosoi-driver`` native extension (install via
    ``cd yosoi_driver && ./build.sh``).

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
    ):
        """Initialize the browser fetcher.

        Args:
            headless: If True, run browser without visible window.
            stealth: If True, apply anti-detection patches.
            no_sandbox: If True, disable Chrome sandbox (needed in containers).
            proxy: Optional proxy server URL.
            chrome_executable: Optional path to Chrome/Chromium binary.
            wait_after_load_ms: Extra wait time in ms after page load event.

        Raises:
            ImportError: If yosoi_driver native extension is not installed.

        """
        if not _HAS_BROWSER:
            raise ImportError('yosoi_driver is not installed. Build it with: cd yosoi_driver && ./build.sh')

        self.headless = headless
        self.stealth = stealth
        self.no_sandbox = no_sandbox
        self.proxy = proxy
        self.chrome_executable = chrome_executable
        self.wait_after_load_ms = wait_after_load_ms

        self._session: BrowserSession | None = None

    async def __aenter__(self) -> BrowserFetcher:
        """Launch the browser."""
        self._session = BrowserSession(
            headless=self.headless,
            stealth=self.stealth,
            no_sandbox=self.no_sandbox,
            proxy=self.proxy,
            chrome_executable=self.chrome_executable,
        )
        self._session = await self._session.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Close the browser."""
        await self.close()

    async def close(self) -> None:
        """Close the browser session."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def fetch(self, url: str) -> FetchResult:
        """Fetch HTML by navigating a real browser to the URL.

        Args:
            url: URL to fetch.

        Returns:
            FetchResult with rendered HTML, metadata, and status.

        Raises:
            BotDetectionError: If bot detection is triggered.
            RuntimeError: If browser session is not started.

        """
        if self._session is None:
            raise RuntimeError('Browser not launched — use `async with BrowserFetcher()` or call __aenter__ first.')

        start_time = time.time()

        try:
            page: Page = await self._session.new_page(url)

            # Optional extra wait for JS rendering
            if self.wait_after_load_ms > 0:
                import asyncio

                await asyncio.sleep(self.wait_after_load_ms / 1000.0)

            html = await page.content()
            await page.close()

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
