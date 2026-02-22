"""Playwright-based fetcher using a real browser."""

import time

from yosoi.core.fetcher.base import ContentAnalyzer, HTMLFetcher
from yosoi.models.results import FetchResult
from yosoi.utils.exceptions import BotDetectionError


class PlaywrightFetcher(HTMLFetcher):
    """Playwright-based fetcher using a real browser.

    Slower but bypasses most bot detection.
    Also handles JavaScript-heavy sites.
    """

    def __init__(self, timeout: int = 60000, headless: bool = True):
        """Initialize Playwright fetcher.

        Args:
            timeout: Page load timeout in milliseconds
            headless: Run browser in headless mode

        """
        self.timeout = timeout
        self.headless = headless

    def fetch(self, url: str) -> FetchResult:
        """Fetch HTML using Playwright (real browser) with content analysis."""
        start_time = time.time()

        try:
            # NOTE: playwright is not supported yet, only in dev deps to prevent bloating package size
            from playwright.sync_api import sync_playwright
        except ImportError as err:
            raise ImportError(
                'Playwright not installed. Install with: uv add playwright && playwright install chromium'
            ) from err

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.headless, args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
                )

                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US',
                )

                page = context.new_page()
                response = page.goto(url, wait_until='networkidle', timeout=self.timeout)
                page.wait_for_timeout(1000)  # Look human

                html = page.content()
                status_code = response.status if response else None

                browser.close()

                # Check for bot detection
                is_blocked, indicators = self._check_for_bot_detection(html, status_code or 200)

                if is_blocked:
                    raise BotDetectionError(url, status_code or 0, indicators)

                # Analyze content
                metadata = ContentAnalyzer.analyze(html)

                fetch_time = time.time() - start_time

                return FetchResult(
                    url=url,
                    html=html,
                    status_code=status_code,
                    is_blocked=False,
                    fetch_time=fetch_time,
                    metadata=metadata,
                )

        except BotDetectionError:
            raise  # Re-raise bot detection errors

        except Exception as e:
            fetch_time = time.time() - start_time
            return FetchResult(
                url=url, html=None, status_code=None, is_blocked=False, block_reason=str(e), fetch_time=fetch_time
            )
