"""Smart waterfall fetcher: try simple first, escalate if blocked."""

from yosoi.core.fetcher.base import HTMLFetcher
from yosoi.core.fetcher.playwright import PlaywrightFetcher
from yosoi.core.fetcher.simple import SimpleFetcher
from yosoi.models.results import FetchResult
from yosoi.utils.exceptions import BotDetectionError


class SmartFetcher(HTMLFetcher):
    """Smart waterfall fetcher: try simple first, escalate if blocked.

    Best balance of speed and effectiveness (~99%).
    """

    def __init__(self, timeout: int = 30, playwright_timeout: int = 60000):
        """Initialize smart fetcher with both simple and Playwright fetchers.

        Args:
            timeout: Timeout for simple fetcher in seconds
            playwright_timeout: Timeout for Playwright fetcher in milliseconds

        """
        self.simple_fetcher = SimpleFetcher(timeout=timeout)
        self.playwright_fetcher = PlaywrightFetcher(timeout=playwright_timeout)

    def fetch(self, url: str) -> FetchResult:
        """Fetch HTML using smart waterfall strategy."""
        # Attempt 1: Simple fetch (fast)
        try:
            result = self.simple_fetcher.fetch(url)
            if result.success:
                return result
        except BotDetectionError:
            # Simple fetch detected bot, try Playwright
            pass

        # Attempt 2: Playwright (slower but effective)
        try:
            result = self.playwright_fetcher.fetch(url)
            return result
        except BotDetectionError:
            raise  # Re-raise if even Playwright is blocked
        except Exception as e:
            # Playwright failed for other reasons
            return FetchResult(
                url=url,
                html=None,
                status_code=None,
                is_blocked=False,
                block_reason=f'All methods failed: {e}',
                fetch_time=0.0,
            )
