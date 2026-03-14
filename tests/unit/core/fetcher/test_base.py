"""Tests for yosoi.core.fetcher.base — ContentAnalyzer and HTMLFetcher base class."""

import pytest

from yosoi.core.fetcher.base import ContentAnalyzer, HTMLFetcher
from yosoi.models.results import FetchResult

# ---------------------------------------------------------------------------
# ContentAnalyzer.analyze
# ---------------------------------------------------------------------------


class TestContentAnalyzer:
    def test_rss_feed_detected(self):
        """RSS content is detected from feed indicators."""
        html = '<?xml version="1.0"?><rss><channel>...</channel></rss>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.is_rss is True
        assert meta.content_type == 'rss'

    def test_atom_feed_detected(self):
        """Atom feed (xmlns) is detected."""
        html = '<feed xmlns="http://www.w3.org/2005/Atom">...</feed>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.is_rss is True

    def test_rss_only_checks_first_500_chars(self):
        """RSS indicators beyond 500 chars are ignored."""
        html = 'x' * 501 + '<?xml'
        meta = ContentAnalyzer.analyze(html)
        assert meta.is_rss is False

    def test_regular_html_not_rss(self):
        """Normal HTML page is not flagged as RSS."""
        html = '<html><head><title>Test</title></head><body><p>Hello</p></body></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.is_rss is False
        assert meta.content_length == len(html)

    def test_react_framework_detected(self):
        """React framework is detected from data-reactroot."""
        html = '<html><body><div data-reactroot>App</div></body></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.js_framework == 'react'

    def test_vue_framework_detected(self):
        """Vue framework is detected from v-if directive."""
        html = '<html><body><div v-if="show">Content</div></body></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.js_framework == 'vue'

    def test_angular_framework_detected(self):
        """Angular framework is detected from ng-app."""
        html = '<html><body ng-app="myApp"><div>Content</div></body></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.js_framework == 'angular'

    def test_next_framework_detected(self):
        """Next.js framework is detected from __next."""
        html = '<html><body><div id="__next">Content</div></body></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.js_framework == 'next'

    def test_svelte_framework_detected(self):
        """Svelte framework is detected."""
        html = '<html><body><div class="svelte-abc">Content</div></body></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.js_framework == 'svelte'

    def test_js_required_when_framework_and_minimal_content(self):
        """requires_js is True when framework detected AND body content is minimal."""
        html = '<html><body><div id="__next"><script>app.render()</script></div></body></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.requires_js is True

    def test_js_not_required_when_framework_but_rich_content(self):
        """requires_js is False when framework detected but body has substantial content."""
        body_content = '<p>' + 'A' * 200 + '</p>'
        html = f'<html><body><div data-reactroot>{body_content}</div></body></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.js_framework == 'react'
        assert meta.requires_js is False

    def test_noscript_warning_triggers_requires_js(self):
        """noscript warning with 'enable javascript' triggers requires_js."""
        html = '<html><body><noscript>Please enable javascript to continue</noscript></body></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.requires_js is True

    def test_no_body_tag_still_works(self):
        """When there's no <body> tag, still analyzes content."""
        html = '<html><div data-reactroot>tiny</div></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.content_length == len(html)

    def test_no_framework_no_js_required(self):
        """Plain HTML without frameworks doesn't require JS."""
        html = '<html><body><h1>Title</h1><p>Content here</p></body></html>'
        meta = ContentAnalyzer.analyze(html)
        assert meta.requires_js is False
        assert meta.js_framework is None


# ---------------------------------------------------------------------------
# HTMLFetcher — abstract base & context manager
# ---------------------------------------------------------------------------


class _ConcreteFetcher(HTMLFetcher):
    """Minimal concrete fetcher for testing base class behavior."""

    async def fetch(self, url: str) -> FetchResult:
        raise NotImplementedError


class TestHTMLFetcherBase:
    @pytest.mark.asyncio
    async def test_context_manager(self):
        """HTMLFetcher supports async context manager protocol."""
        async with _ConcreteFetcher() as f:
            assert isinstance(f, HTMLFetcher)

    @pytest.mark.asyncio
    async def test_close_is_noop_by_default(self):
        """Default close() does nothing (no error)."""
        f = _ConcreteFetcher()
        await f.close()

    def test_scan_body_patterns(self):
        """_scan_body_patterns appends matching messages."""
        f = _ConcreteFetcher()
        found: list[str] = []
        f._scan_body_patterns('challenge-platform is here', HTMLFetcher._BOT_BODY_PATTERNS, found)
        assert 'Cloudflare challenge platform' in found

    def test_scan_body_patterns_no_duplicates(self):
        """_scan_body_patterns doesn't add duplicate messages."""
        f = _ConcreteFetcher()
        found = ['Cloudflare challenge platform']
        f._scan_body_patterns('challenge-platform', HTMLFetcher._BOT_BODY_PATTERNS, found)
        assert found.count('Cloudflare challenge platform') == 1

    def test_enrich_with_header_context(self):
        """_enrich_with_header_context adds Retry-After, Cloudflare server, CF-Ray."""
        f = _ConcreteFetcher()
        headers = {'retry-after': '10', 'server': 'cloudflare', 'cf-ray': 'abc'}
        found: list[str] = []
        result = f._enrich_with_header_context(found, headers)
        assert 'Retry-After: 10' in result
        assert 'Cloudflare server' in result
        assert 'CF-Ray: abc' in result
