"""Abstract base class for HTML fetchers and content analyzer."""

import re
from abc import ABC, abstractmethod

from yosoi.models.results import ContentMetadata, FetchResult


class ContentAnalyzer:
    """Analyzes fetched content to detect special cases."""

    @staticmethod
    def analyze(html: str) -> ContentMetadata:
        """Analyze HTML content and return metadata.

        Args:
            html: The HTML of the URL

        Returns:
            The metadata of the HTML from the URL

        """
        metadata = ContentMetadata()
        metadata.content_length = len(html)

        # Convert to lowercase for case-insensitive checks
        html_lower = html.lower()

        # 1. Check if it's RSS/XML
        metadata.is_rss = ContentAnalyzer._detect_rss(html_lower)
        if metadata.is_rss:
            metadata.content_type = 'rss'
            return metadata

        # 2. Detect JavaScript-heavy sites
        js_data = ContentAnalyzer._detect_javascript_heavy(html_lower)
        metadata.requires_js = js_data['requires_js']
        metadata.js_framework = js_data['framework']

        return metadata

    @staticmethod
    def _detect_rss(html_lower: str) -> bool:
        """Detect if content is an RSS/Atom feed.

        Args:
            html_lower: The HTML of the URL in all lowercase

        Returns:
            True if the HTML has RSS indicators

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
    def _detect_javascript_heavy(html_lower: str) -> dict:
        """Detect JavaScript-heavy sites that need browser rendering.

        Args:
            html_lower: The HTML of the URL in all lowercase

        Returns:
            A dict of if it has JS and if so what framework of JS

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
    """Abstract base class for HTML fetchers.

    Implement this interface to create custom HTML fetchers.
    """

    @abstractmethod
    def fetch(self, url: str) -> FetchResult:
        """Fetch HTML from a URL.

        Args:
            url: URL to fetch

        Returns:
            FetchResult with HTML, metadata, and status

        Raises:
            BotDetectionError: If bot detection is triggered

        """
        pass

    def _check_for_bot_detection(self, html: str, status_code: int) -> tuple[bool, list[str]]:
        """Check if HTML indicates bot detection.

        Args:
            html: The HTML of the URL
            status_code: The status code of the URL returned

        Returns:
            Tuple of (is_blocked, indicators) where is_blocked is True if bot
            detection triggered, and indicators is a list of detection reasons.
            Returns (False, []) if no blocking detected.

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
