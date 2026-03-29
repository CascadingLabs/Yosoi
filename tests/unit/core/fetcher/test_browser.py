"""Tests for the BrowserFetcher (yosoi_driver CDP integration).

These tests require a real Chromium binary and the yosoi_driver native extension.
They exercise the full fetch pipeline: launch browser → navigate → extract HTML.
"""

from __future__ import annotations

import pytest

from yosoi.core.fetcher import create_fetcher
from yosoi.core.fetcher.browser import BrowserFetcher

pytestmark = pytest.mark.integration


# ── Factory tests ────────────────────────────────────────────────────────


def test_create_fetcher_browser_type():
    """create_fetcher('browser') returns a BrowserFetcher instance."""
    fetcher = create_fetcher('browser', no_sandbox=True)
    assert isinstance(fetcher, BrowserFetcher)


def test_create_fetcher_unknown_type_lists_browser():
    """Error message for unknown fetcher type mentions 'browser'."""
    with pytest.raises(ValueError, match='browser'):
        create_fetcher('nonexistent')


# ── Context manager lifecycle ────────────────────────────────────────────


async def test_browser_fetcher_context_manager():
    """BrowserFetcher can be used as an async context manager."""
    async with BrowserFetcher(no_sandbox=True) as fetcher:
        assert fetcher._session is not None
    assert fetcher._session is None


async def test_browser_fetcher_fetch_without_context_raises():
    """Calling fetch() without entering context manager raises RuntimeError."""
    fetcher = BrowserFetcher(no_sandbox=True)
    with pytest.raises(RuntimeError, match='not launched'):
        await fetcher.fetch('https://example.com')


# ── End-to-end fetch tests ──────────────────────────────────────────────


async def test_fetch_example_com():
    """Fetch example.com and verify HTML content is returned."""
    async with BrowserFetcher(no_sandbox=True) as fetcher:
        result = await fetcher.fetch('https://example.com')

    assert result.status_code == 200
    assert not result.is_blocked
    assert result.html is not None
    assert 'Example Domain' in result.html
    assert result.fetch_time > 0


async def test_fetch_returns_metadata():
    """Fetch result includes content metadata from ContentAnalyzer."""
    async with BrowserFetcher(no_sandbox=True) as fetcher:
        result = await fetcher.fetch('https://example.com')

    assert result.metadata is not None
    assert not result.metadata.is_rss
    assert result.metadata.content_length > 0


async def test_fetch_invalid_url_returns_error_page():
    """Fetching an unreachable URL returns Chrome's error page (DNS error), not a crash."""
    async with BrowserFetcher(no_sandbox=True) as fetcher:
        result = await fetcher.fetch('https://this-domain-does-not-exist-1234567.com')

    # Chrome renders its own error page for DNS failures rather than throwing.
    # The HTML will contain Chrome's "can't be reached" error page.
    assert result.html is not None
    assert 'DNS' in result.html or "can't be reached" in result.html


# ── BrowserSession direct tests ──────────────────────────────────────────


async def test_browser_session_direct():
    """Test yosoi_driver.BrowserSession directly for page operations."""
    from yosoi_driver import BrowserSession

    async with BrowserSession(headless=True, no_sandbox=True) as browser:
        page = await browser.new_page('https://example.com')

        # Content
        html = await page.content()
        assert 'Example Domain' in html

        # Title
        title = await page.title()
        assert title == 'Example Domain'

        # URL
        url = await page.url()
        assert url == 'https://example.com/'

        # JS evaluation
        js_result = await page.evaluate_js('1 + 1')
        assert js_result == '2'

        # Query selector
        h1_html = await page.query_selector('h1')
        assert h1_html is not None
        assert 'Example Domain' in h1_html

        await page.close()


async def test_browser_session_navigate():
    """Test navigating to a second URL within the same page."""
    from yosoi_driver import BrowserSession

    async with BrowserSession(headless=True, no_sandbox=True) as browser:
        page = await browser.new_page('https://example.com')

        # Navigate to a different page
        await page.navigate('https://www.iana.org/domains/reserved')
        html = await page.content()
        assert 'IANA' in html or 'iana' in html.lower()

        await page.close()


async def test_browser_session_no_stealth():
    """Test launching without stealth mode."""
    from yosoi_driver import BrowserSession

    async with BrowserSession(headless=True, no_sandbox=True, stealth=False) as browser:
        page = await browser.new_page('https://example.com')
        html = await page.content()
        assert 'Example Domain' in html
        await page.close()
