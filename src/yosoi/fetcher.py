"""
HTML Fetcher Module - HTML Retrieval with Content Detection
======================================================================

This module provides a interface for fetching HTML from URLs.
"""

import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests


class BotDetectionError(Exception):
    """Raised when bot detection is triggered."""

    def __init__(self, url: str, status_code: int, indicators: list[str]):
        self.url = url
        self.status_code = status_code
        self.indicators = indicators
        super().__init__(f'Bot detection triggered on {url} (status={status_code}): {", ".join(indicators)}')


@dataclass
class ContentMetadata:
    """Metadata about the fetched content."""

    is_rss: bool = False
    requires_js: bool = False
    content_type: str = 'html'

    js_framework: str | None = None

    content_length: int = 0


@dataclass
class FetchResult:
    """Result of an HTML fetch operation."""

    url: str
    html: str | None = None
    status_code: int | None = None
    is_blocked: bool = False
    block_reason: str | None = None
    fetch_time: float = 0.0

    # Content metadata
    metadata: ContentMetadata = field(default_factory=ContentMetadata)

    @property
    def success(self) -> bool:
        """Whether the fetch was successful."""
        return self.html is not None and not self.is_blocked

    @property
    def is_rss(self) -> bool:
        """Shortcut to check if content is RSS."""
        return self.metadata.is_rss

    @property
    def requires_js(self) -> bool:
        """Shortcut to check if content requires JavaScript."""
        return self.metadata.requires_js

    @property
    def should_use_heuristics(self) -> bool:
        """Whether we should skip AI and use heuristics."""
        return self.is_rss or self.requires_js


class ContentAnalyzer:
    """Analyzes fetched content to detect special cases."""

    @staticmethod
    def analyze(html: str, url: str) -> ContentMetadata:  # noqa: ARG004
        """
        Analyze HTML content and return metadata.
        """
        metadata = ContentMetadata()
        metadata.content_length = len(html)

        # Convert to lowercase for case-insensitive checks
        html_lower = html.lower()

        # 1. Check if it's RSS/XML
        metadata.is_rss = ContentAnalyzer._detect_rss(html, html_lower)
        if metadata.is_rss:
            metadata.content_type = 'rss'
            return metadata  # Early return for RSS

        # 2. Detect JavaScript-heavy sites
        js_data = ContentAnalyzer._detect_javascript_heavy(html, html_lower)
        metadata.requires_js = js_data['requires_js']
        metadata.js_framework = js_data['framework']

        return metadata

    @staticmethod
    def _detect_rss(_html: str, html_lower: str) -> bool:  # Prefix with _
        """
        Detect if content is an RSS/Atom feed.
        """
        rss_indicators = [
            '<?xml',
            '<rss',
            '<feed',
            '<channel>',
            'xmlns="http://www.w3.org/2005/atom"',
            'xmlns="http://purl.org/rss/1.0/"',
        ]

        # Check first 500 chars (RSS declarations are at the top)
        start = html_lower[:500]

        return any(indicator in start for indicator in rss_indicators)

    @staticmethod
    def _detect_javascript_heavy(_html: str, html_lower: str) -> dict:  # Prefix with _
        """
        Detect JavaScript-heavy sites that need browser rendering.

        These sites won't work with simple HTML fetching because:
        - Content is rendered client-side
        - No meaningful HTML in initial response
        - Need Playwright/Selenium
        """
        # 1. Check for JS framework signatures
        frameworks = {
            'react': [
                'id="root"',
                'id="app"',
                'data-reactroot',
                'react-root',
                '__react',
            ],
            'vue': [
                'id="app"',
                'v-if=',
                'v-for=',
                'vue.js',
                '__vue',
            ],
            'angular': [
                'ng-app',
                'ng-controller',
                'angular.js',
                'ng-version',
            ],
            'next': [
                '__next',
                '_next/static',
                'next.js',
            ],
            'svelte': [
                'svelte',
                '__svelte',
            ],
        }

        detected_framework = None
        for framework, indicators in frameworks.items():
            if any(indicator in html_lower for indicator in indicators):
                detected_framework = framework
                break

        # 2. Check for minimal content (sign of client-side rendering)
        body_match = re.search(r'<body[^>]*>(.*?)</body>', html_lower, re.DOTALL)
        if body_match:
            body_content = body_match.group(1)
            # Remove scripts, styles, and whitespace
            body_content = re.sub(r'<script[^>]*>.*?</script>', '', body_content, flags=re.DOTALL)
            body_content = re.sub(r'<style[^>]*>.*?</style>', '', body_content, flags=re.DOTALL)
            body_content = body_content.strip()

            # If body has < 100 chars of actual content, it's probably JS-rendered
            minimal_content = len(body_content) < 100
        else:
            minimal_content = False

        # 3. Check for "noscript" warnings
        has_noscript_warning = '<noscript>' in html_lower and (
            'enable javascript' in html_lower or 'requires javascript' in html_lower
        )

        # Determine if JS is required
        requires_js = (detected_framework is not None and minimal_content) or has_noscript_warning

        return {'requires_js': requires_js, 'framework': detected_framework}


class UserAgentRotator:
    """Manages a pool of realistic user agents."""

    # Pool of realistic, recent user agents
    USER_AGENTS = [
        # Chrome on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        # Chrome on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        # Firefox on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
        # Firefox on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
        # Safari on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        # Edge on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
        # Chrome on Linux
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]

    @classmethod
    def get_random(cls) -> str:
        """Get a random user agent."""
        return random.choice(cls.USER_AGENTS)

    @classmethod
    def get_chrome_windows(cls) -> str:
        """Get a Chrome on Windows user agent (most common)."""
        chrome_windows = [ua for ua in cls.USER_AGENTS if 'Chrome' in ua and 'Windows' in ua and 'Edg' not in ua]
        return random.choice(chrome_windows)

    @classmethod
    def get_firefox(cls) -> str:
        """Get a Firefox user agent."""
        firefox = [ua for ua in cls.USER_AGENTS if 'Firefox' in ua]
        return random.choice(firefox)


class HeaderGenerator:
    """Generates realistic browser headers with variation."""

    @staticmethod
    def generate_headers(user_agent: str | None = None, referer: str | None = None) -> dict[str, str]:
        """
        Generate realistic browser headers with randomization.
        """
        if user_agent is None:
            user_agent = UserAgentRotator.get_random()

        # Base headers that all browsers send
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': HeaderGenerator._get_accept_language(),
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        # Add Sec-Fetch-* headers (Chrome/Edge specific)
        if 'Chrome' in user_agent or 'Edg' in user_agent:
            headers.update(
                {
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none' if referer is None else 'same-origin',
                    'Sec-Fetch-User': '?1',
                }
            )

        # Add referer if provided
        if referer:
            headers['Referer'] = referer

        # Randomly add some optional headers
        if random.random() > 0.5:
            headers['Cache-Control'] = random.choice(['no-cache', 'max-age=0'])

        return headers

    @staticmethod
    def _get_accept_language() -> str:
        """Get a randomized Accept-Language header."""
        languages = [
            'en-US,en;q=0.9',
            'en-GB,en;q=0.9',
            'en-US,en;q=0.9,es;q=0.8',
            'en-US,en;q=0.9,fr;q=0.8',
            'en-US,en;q=0.5',
        ]
        return random.choice(languages)


class HTMLFetcher(ABC):
    """
    Abstract base class for HTML fetchers.
    Implement this interface to create custom HTML fetchers.
    """

    @abstractmethod
    def fetch(self, url: str) -> FetchResult:
        """
        Fetch HTML from a URL.

        Args:
            url: URL to fetch

        Returns:
            FetchResult with HTML, metadata, and status

        Raises:
            BotDetectionError: If bot detection is triggered
        """
        pass

    def _check_for_bot_detection(self, html: str, status_code: int) -> tuple[bool, list[str]]:
        """
        Check if HTML indicates bot detection.
        """
        if not html or len(html) < 100:
            return True, ['HTML too short']

        # Block immediately on known bad status codes
        if status_code in [403, 429, 503]:
            return True, [f'HTTP {status_code}']

        # For 200 OK responses, be conservative (avoid false positives)
        if status_code == 200:
            # Only check first 2000 chars where block messages appear
            html_check = html[:2000].lower()

            # Very specific patterns that indicate actual blocking
            strict_indicators = {
                'challenge-form': 'Cloudflare challenge',
                'cf-captcha': 'Cloudflare CAPTCHA',
                'access denied</title>': 'Access denied page',
                'rate limit exceeded': 'Rate limit',
                'please verify you are human': 'Human verification',
                'enable javascript to continue': 'JavaScript block',
            }

            found = []
            for indicator, message in strict_indicators.items():
                if indicator in html_check:
                    found.append(message)

            return bool(found), found

        # For other bad status codes (4xx, 5xx), be more aggressive
        if status_code >= 400:
            html_check = html[:2000].lower()

            block_indicators = {
                'captcha': 'CAPTCHA required',
                'access denied': 'Access denied',
                'cloudflare': 'Cloudflare protection',
                'rate limit': 'Rate limited',
                'too many requests': 'Too many requests',
                'forbidden': 'Forbidden',
            }

            found = []
            for indicator, message in block_indicators.items():
                if indicator in html_check:
                    found.append(message)

            return bool(found), found

        # No blocking detected
        return False, []

    def _analyze_content(self, html: str, url: str) -> ContentMetadata:
        """Analyze fetched content."""
        return ContentAnalyzer.analyze(html, url)


class SimpleFetcher(HTMLFetcher):
    """
    Simple HTTP fetcher with realistic browser headers.
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
        self.timeout = timeout
        self.rotate_user_agent = rotate_user_agent
        self.use_session = use_session
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.randomize_headers = randomize_headers

        # Create session if enabled
        if self.use_session:
            self.session = requests.Session()
        else:
            self.session = None

        # Track last request time for delays
        self.last_request_time = 0.0

    def _apply_request_delay(self):
        """Apply a random delay between requests to appear more human."""
        if self.min_delay > 0:
            elapsed = time.time() - self.last_request_time
            delay_needed = random.uniform(self.min_delay, self.max_delay)

            if elapsed < delay_needed:
                time.sleep(delay_needed - elapsed)

        self.last_request_time = time.time()

    def _get_headers(self, url: str) -> dict[str, str]:  # noqa: ARG002
        """
        Get headers for the request.
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
        """
        Fetch HTML using enhanced HTTP request with anti-bot measures.
        """
        start_time = time.time()

        # Apply delay to avoid rate limiting
        self._apply_request_delay()

        try:
            # Get headers (potentially randomized)
            headers = self._get_headers(url)

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
            metadata = self._analyze_content(html, url)

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


class PlaywrightFetcher(HTMLFetcher):
    """
    Playwright-based fetcher using a real browser.

    Slower but bypasses most bot detection (~95%).
    Also handles JavaScript-heavy sites.
    """

    def __init__(self, timeout: int = 60000, headless: bool = True):
        self.timeout = timeout
        self.headless = headless

    def fetch(self, url: str) -> FetchResult:
        """Fetch HTML using Playwright (real browser) with content analysis."""
        start_time = time.time()

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as err:
            raise ImportError(
                'Playwright not installed. Install with: pip install playwright && playwright install chromium'
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
                metadata = self._analyze_content(html, url)

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


class SmartFetcher(HTMLFetcher):
    """
    Smart waterfall fetcher: try simple first, escalate if blocked.

    Best balance of speed and effectiveness (~99%).
    """

    def __init__(self, timeout: int = 30, playwright_timeout: int = 60000):
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


# Factory function for easy fetcher creation
def create_fetcher(fetcher_type: str = 'simple', **kwargs) -> HTMLFetcher:
    """
    Create an HTML fetcher.

    Args:
        fetcher_type: Type of fetcher ('simple', 'playwright', 'smart')
        **kwargs: Additional arguments for the fetcher

    Returns:
        HTMLFetcher instance

    Examples:
        >>> fetcher = create_fetcher('simple')
        >>> fetcher = create_fetcher('playwright', headless=True)
        >>> fetcher = create_fetcher('smart')
    """
    fetchers: dict[str, type[HTMLFetcher]] = {
        'simple': SimpleFetcher,
        'playwright': PlaywrightFetcher,
        'smart': SmartFetcher,
    }

    if fetcher_type not in fetchers:
        raise ValueError(f'Unknown fetcher type: {fetcher_type}. Choose from: {list(fetchers.keys())}')

    return fetchers[fetcher_type](**kwargs)
