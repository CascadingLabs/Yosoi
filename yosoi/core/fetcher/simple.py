"""Simple HTTP fetcher with realistic browser headers and anti-bot measures."""

import logging
import random
import time

import requests

from yosoi.core.fetcher.base import ContentAnalyzer, HTMLFetcher
from yosoi.models.results import FetchResult
from yosoi.utils.exceptions import BotDetectionError
from yosoi.utils.headers import HeaderGenerator, UserAgentRotator


class SimpleFetcher(HTMLFetcher):
    """Simple HTTP fetcher with realistic browser headers and anti-bot measures.

    Implements random delays, user agent rotation, and realistic headers
    to avoid rate limiting and bot detection.

    Attributes:
        timeout: Request timeout in seconds (how long to wait for response)
        rotate_user_agent: Whether to rotate user agents between requests
        use_session: Whether to use a requests.Session for connection pooling
        min_delay: Minimum delay between requests in seconds
        max_delay: Maximum delay between requests in seconds
        randomize_headers: Whether to randomize request headers
        session: Requests session instance if use_session is True
        last_request_time: Timestamp of last request for delay calculation

    """

    def __init__(
        self,
        timeout: int = 30,
        rotate_user_agent: bool = True,
        use_session: bool = True,
        min_delay: float = 0.5,
        max_delay: float = 2.0,
        randomize_headers: bool = True,
    ):
        """Intialize the simple fetcher.

        Args:
            timeout: The time between retring to fetch a URL
            rotate_user_agent: If True then will use different user agents for each retry
            use_session: If True will create a session
            min_delay: Minimum time to pause between fetches
            max_delay: Maximum time to pause between fetches
            randomize_headers: If True then will randomize the headers used to fetch

        """
        self.timeout = timeout
        self.rotate_user_agent = rotate_user_agent
        self.use_session = use_session
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.randomize_headers = randomize_headers

        self.session: requests.Session | None
        # Create session if enabled
        if self.use_session:
            self.session = requests.Session()
        else:
            self.session = None

        # Track last request time for delays
        self.last_request_time = 0.0
        self.logger = logging.getLogger(__name__)

    def _apply_request_delay(self):
        """Apply a random delay between requests to appear more human."""
        if self.min_delay > 0:
            elapsed = time.time() - self.last_request_time
            delay_needed = random.uniform(self.min_delay, self.max_delay)

            if elapsed < delay_needed:
                time.sleep(delay_needed - elapsed)

        self.last_request_time = time.time()

    def _get_headers(self) -> dict[str, str]:
        """Get headers for the request.

        Returns:
            A dict of the random headers and user agent

        """
        if self.randomize_headers:
            user_agent = UserAgentRotator.get_random() if self.rotate_user_agent else None
            return HeaderGenerator.generate_headers(user_agent=user_agent)
        # Fallback to static headers
        return {
            'User-Agent': UserAgentRotator.get_chrome_windows(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

    def fetch(self, url: str) -> FetchResult:
        """Fetch HTML using enhanced HTTP request with anti-bot measures.

        Args:
            url: The URL that is being fetched

        Returns:
            The fetched results like the HTML, URL, if it is blocked, etc.

        """
        start_time = time.time()

        # Apply delay to avoid rate limiting
        self._apply_request_delay()

        try:
            # Get headers (potentially randomized)
            headers = self._get_headers()

            # Use session or direct request
            if self.session:
                response = self.session.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
            else:
                response = requests.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)

            status_code = response.status_code

            try:
                # Try to get text with proper encoding
                html = response.text

                # Verify it's actually text
                if html.startswith('\x1f\x8b'):
                    # Force decompression
                    import gzip

                    html = gzip.decompress(response.content).decode('utf-8', errors='replace')

            except Exception:
                # Fallback: try to decode bytes manually
                try:
                    html = response.content.decode('utf-8', errors='replace')
                except UnicodeDecodeError:
                    html = response.content.decode('latin-1', errors='replace')

            # Verify we got actual HTML
            if not html or len(html) < 100:
                return FetchResult(
                    url=url,
                    html=None,
                    status_code=status_code,
                    is_blocked=True,
                    block_reason='Response too short or empty',
                    fetch_time=time.time() - start_time,
                )

            # Check for bot detection
            is_blocked, indicators = self._check_for_bot_detection(html, status_code)

            if is_blocked:
                raise BotDetectionError(url, status_code, indicators)

            # Analyze content
            metadata = ContentAnalyzer.analyze(html)

            fetch_time = time.time() - start_time

            return FetchResult(
                url=url, html=html, status_code=status_code, is_blocked=False, fetch_time=fetch_time, metadata=metadata
            )

        except BotDetectionError:
            raise  # Re-raise bot detection errors

        except Exception as e:
            fetch_time = time.time() - start_time
            return FetchResult(
                url=url, html=None, status_code=None, is_blocked=False, block_reason=str(e), fetch_time=fetch_time
            )

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def close(self):
        """Close the session if it exists."""
        if self.session:
            self.session.close()
