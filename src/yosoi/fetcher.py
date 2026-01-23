"""
HTML Fetcher Module - Pluggable HTML Retrieval with Content Detection
======================================================================

This module provides a pluggable interface for fetching HTML from URLs.
Now includes detection for:
- Tailwind CSS (utility-first CSS that breaks selector discovery)
- RSS feeds (XML, not HTML)
- JavaScript-heavy sites (require browser rendering)

Usage:
    from yosoi.fetcher import SimpleFetcher

    fetcher = SimpleFetcher()
    result = fetcher.fetch(url)

    if result.is_rss:
        print("This is an RSS feed!")
    elif result.is_tailwind_heavy:
        print("Heavy Tailwind usage - use heuristics")
    elif result.requires_js:
        print("Needs JavaScript rendering")
"""

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
    is_tailwind_heavy: bool = False
    requires_js: bool = False
    content_type: str = 'html'  # 'html', 'rss', 'xml', 'json'

    # Tailwind detection details
    tailwind_class_count: int = 0

    # JavaScript detection details
    js_framework: str | None = None  # 'react', 'vue', 'angular', etc.

    # Additional metadata
    has_body_tag: bool = True
    has_main_tag: bool = False
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

    # NEW: Content metadata
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
    def is_tailwind_heavy(self) -> bool:
        """Shortcut to check if content uses heavy Tailwind."""
        return self.metadata.is_tailwind_heavy

    @property
    def requires_js(self) -> bool:
        """Shortcut to check if content requires JavaScript."""
        return self.metadata.requires_js

    @property
    def should_use_heuristics(self) -> bool:
        """Whether we should skip AI and use heuristics."""
        return self.is_rss or self.is_tailwind_heavy or self.requires_js


class ContentAnalyzer:
    """Analyzes fetched content to detect special cases."""

    @staticmethod
    def analyze(html: str, url: str) -> ContentMetadata:  # noqa: ARG004
        """
        Analyze HTML content and return metadata.

        Args:
            html: HTML content to analyze
            url: URL being analyzed (for context)

        Returns:
            ContentMetadata with detection results
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

        # 2. Check for basic HTML structure
        metadata.has_body_tag = '<body' in html_lower
        metadata.has_main_tag = '<main' in html_lower

        # 3. Detect Tailwind CSS
        tailwind_data = ContentAnalyzer._detect_tailwind(html, html_lower)
        metadata.is_tailwind_heavy = tailwind_data['is_heavy']
        metadata.tailwind_class_count = tailwind_data['count']

        # 4. Detect JavaScript-heavy sites
        js_data = ContentAnalyzer._detect_javascript_heavy(html, html_lower)
        metadata.requires_js = js_data['requires_js']
        metadata.js_framework = js_data['framework']

        return metadata

    @staticmethod
    def _detect_rss(_html: str, html_lower: str) -> bool:  # Prefix with _
        """
        Detect if content is an RSS/Atom feed.

        RSS feeds are XML, not HTML, and can't be scraped with CSS selectors.
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
    def _detect_tailwind(html: str, _html_lower: str) -> dict:  # Prefix with _
        """
        Detect heavy Tailwind CSS usage.

        Tailwind uses utility classes with special characters like:
        - lg:flex, md:hidden (responsive)
        - hover:bg-blue-500 (pseudo-classes)
        - [&_a]:underline (arbitrary values)

        These break JSON parsing in Pydantic AI.
        """
        tailwind_patterns = [
            r'lg:',
            r'md:',
            r'sm:',
            r'xl:',
            r'2xl:',
            r'hover:',
            r'focus:',
            r'active:',
            r'dark:',
            r'\[&_',
            r'text-\w+',
            r'bg-\w+',
            r'p-\d+',
            r'm-\d+',
            r'w-\d+',
            r'h-\d+',
            r'flex-\w+',
            r'grid-\w+',
        ]

        count = 0
        for pattern in tailwind_patterns:
            matches = re.findall(pattern, html)
            count += len(matches)

        # Thresholds
        # Light usage: < 50 (maybe a few utility classes)
        # Medium usage: 50-200 (mixed approach)
        # Heavy usage: > 200 (full Tailwind)
        is_heavy = count > 200

        return {'is_heavy': is_heavy, 'count': count}

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

        Args:
            html: HTML content to check
            status_code: HTTP status code

        Returns:
            (is_blocked, indicators) tuple
        """
        if not html or len(html) < 100:
            return True, ['HTML too short']

        # Check status code
        if status_code in [403, 429]:
            return True, [f'HTTP {status_code}']

        # Check for common block indicators
        html_lower = html.lower()

        block_indicators = {
            'captcha': 'CAPTCHA required',
            'access denied': 'Access denied',
            'cloudflare': 'Cloudflare protection',
            'please verify you are a human': 'Human verification required',
            'rate limit': 'Rate limited',
            'too many requests': 'Too many requests',
            'firewall': 'Firewall block',
            'forbidden': 'Forbidden',
        }

        found = []
        for indicator, message in block_indicators.items():
            if indicator in html_lower:
                found.append(message)

        return bool(found), found

    def _analyze_content(self, html: str, url: str) -> ContentMetadata:
        """Analyze fetched content."""
        return ContentAnalyzer.analyze(html, url)


class SimpleFetcher(HTMLFetcher):
    """
    Simple HTTP fetcher with realistic browser headers.

    Fast and works for most sites (~70%).
    Now includes content analysis.
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }

    def fetch(self, url: str) -> FetchResult:
        """Fetch HTML using simple HTTP request with content analysis."""
        start_time = time.time()

        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            html = response.text
            status_code = response.status_code

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
