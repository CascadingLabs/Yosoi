"""Chrome-based fetchers using a persistent browser instance via zendriver.

Provides two single-tier fetchers backed by a shared Chrome browser:

- :class:`HeadlessFetcher` — Chrome with no visible window, fast and low overhead.
- :class:`HeadfulFetcher` — Chrome with a visible window, better bot evasion.

Both share :class:`_SingleTierFetcher` as a private base. Use :mod:`js` for the
three-tier waterfall that orchestrates these alongside :class:`~yosoi.core.fetcher.simple.SimpleFetcher`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import time

import zendriver as zd

from yosoi.core.fetcher.base import ContentAnalyzer, HTMLFetcher
from yosoi.models.results import FetchResult
from yosoi.utils.exceptions import BotDetectionError

# ---------------------------------------------------------------------------
# Chrome auto-detection
# ---------------------------------------------------------------------------

_CHROME_PATHS = [
    '/opt/google/chrome/chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/snap/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
]


def _find_chrome() -> str:
    """Return the path to the first Chrome/Chromium binary found on this system."""
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        found = shutil.which(name)
        if found:
            return found
    for path in _CHROME_PATHS:
        if os.path.isfile(os.path.expandvars(path)):
            return path
    raise RuntimeError(
        'Chrome not found.\n'
        '  Ubuntu/Debian : sudo apt install chromium-browser\n'
        '  macOS         : brew install --cask google-chrome\n'
        '  Windows       : https://www.google.com/chrome'
    )


# ---------------------------------------------------------------------------
# DOM stability wait
# ---------------------------------------------------------------------------

_POLL_INTERVAL = 0.2
_STABLE_CHECKS = 3


async def _wait_for_content(tab: object, timeout: float) -> bool:
    """Poll until the DOM stops changing or the timeout is hit.

    Returns True if the DOM stabilised, False if we hit the timeout.
    """
    deadline = time.time() + timeout
    previous_size = 0
    stable_count = 0

    while time.time() < deadline:
        size = await tab.evaluate(  # type: ignore[union-attr]
            'document.body ? document.body.innerHTML.length : 0'
        )
        if size > 0 and size == previous_size:
            stable_count += 1
            if stable_count >= _STABLE_CHECKS:
                return True
        else:
            stable_count = 0
            previous_size = size
        await asyncio.sleep(_POLL_INTERVAL)

    return False


# ---------------------------------------------------------------------------
# Low-level single-tab fetch helper
# ---------------------------------------------------------------------------


async def _fetch_with_browser(
    browser: zd.Browser,
    url: str,
    semaphore: asyncio.Semaphore,
    timeout: float,
) -> tuple[str | None, bool, str | None]:
    """Fetch *url* in a new tab using *browser*.

    Returns:
        ``(html, stabilised, error)``
    """
    async with semaphore:
        tab = None
        try:
            tab = await browser.get(url, new_tab=True)
            await tab.wait_for_ready_state('complete', timeout=timeout)
            stabilised = await _wait_for_content(tab, timeout=min(timeout, 8.0))
            html = await tab.evaluate('document.body.innerHTML')
            return html.strip() if html else None, stabilised, None
        except Exception as e:  # noqa: BLE001
            return None, False, str(e)
        finally:
            if tab:
                with contextlib.suppress(Exception):
                    await tab.close()


# ---------------------------------------------------------------------------
# _SingleTierFetcher — shared base for HeadlessFetcher and HeadfulFetcher
# ---------------------------------------------------------------------------


class _SingleTierFetcher(HTMLFetcher):
    """Internal base for a single-tier Chrome fetcher."""

    _headless: bool  # set by subclass

    def __init__(
        self,
        timeout: int = 30,
        rotate_user_agent: bool = True,  # noqa: ARG002
        use_session: bool = True,  # noqa: ARG002
        min_delay: float = 0.5,
        max_delay: float = 2.0,
        randomize_headers: bool = True,  # noqa: ARG002
        max_concurrent: int = 5,
        min_content_length: int = 500,
        browser_executable_path: str | None = None,
    ):
        self.timeout = timeout
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_concurrent = max_concurrent
        self.min_content_length = min_content_length
        self.browser_executable_path = browser_executable_path or _find_chrome()

        self._browser: zd.Browser | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self.last_request_time = 0.0
        self.logger = logging.getLogger(__name__)

    async def __aenter__(self) -> _SingleTierFetcher:
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._browser = await zd.start(
            headless=self._headless,
            browser_executable_path=self.browser_executable_path,
        )
        tier = 'headless' if self._headless else 'headful'
        self.logger.info('%s ready (%s)', type(self).__name__, tier)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._browser:
            with contextlib.suppress(Exception):
                await self._browser.stop()
            self._browser = None

    def _is_content_empty(self, html: str | None) -> bool:
        return not html or len(html) < self.min_content_length

    def _assert_ready(self) -> None:
        assert self._browser is not None
        assert self._semaphore is not None

    async def _do_fetch(self, url: str, start_time: float, tier_label: str) -> FetchResult:
        """Run a tab fetch and apply standard post-fetch checks."""
        html, stabilised, error = await _fetch_with_browser(
            self._browser,
            url,
            self._semaphore,
            self.timeout,  # type: ignore[arg-type]
        )

        if error or self._is_content_empty(html):
            reason = error or ('DOM did not stabilise' if not stabilised else 'content too short')
            return FetchResult(
                url=url,
                html=None,
                status_code=None,
                is_blocked=False,
                block_reason=f'[{tier_label}] {reason}',
                fetch_time=time.time() - start_time,
            )

        if len(html) < 100:  # type: ignore[arg-type]
            return FetchResult(
                url=url,
                html=None,
                status_code=None,
                is_blocked=True,
                block_reason='Response too short or empty',
                fetch_time=time.time() - start_time,
            )

        is_blocked, indicators = self._check_for_bot_detection(html, 200, {})
        if is_blocked:
            self.logger.warning('Bot detection triggered for %s via %s: %s', url, tier_label, ', '.join(indicators))
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


# ---------------------------------------------------------------------------
# HeadlessFetcher
# ---------------------------------------------------------------------------


class HeadlessFetcher(_SingleTierFetcher):
    """Single-tier fetcher using headless Chrome.

    Usage::

        async with HeadlessFetcher() as fetcher:
            result = await fetcher.fetch("https://example.com")
    """

    _headless = True

    async def fetch(self, url: str) -> FetchResult:
        """Fetch *url* using headless Chrome."""
        self._assert_ready()
        return await self._do_fetch(url, start_time=time.time(), tier_label='headless')


# ---------------------------------------------------------------------------
# HeadfulFetcher
# ---------------------------------------------------------------------------


class HeadfulFetcher(_SingleTierFetcher):
    """Single-tier fetcher using headful (visible) Chrome.

    Usage::

        async with HeadfulFetcher() as fetcher:
            result = await fetcher.fetch("https://example.com")
    """

    _headless = False

    async def fetch(self, url: str) -> FetchResult:
        """Fetch *url* using headful Chrome."""
        self._assert_ready()
        return await self._do_fetch(url, start_time=time.time(), tier_label='headful')
