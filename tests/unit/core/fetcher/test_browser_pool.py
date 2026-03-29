"""Tests for BrowserPool-backed fetching (yosoi_driver pool integration).

These tests require a real Chromium binary and the yosoi_driver native extension.
They exercise the pool lifecycle: warmup → acquire → navigate → release.
"""

from __future__ import annotations

import asyncio

import pytest

from yosoi.core.fetcher import create_fetcher
from yosoi.core.fetcher.browser import BrowserFetcher

pytestmark = pytest.mark.integration


# ── Pool lifecycle ──────────────────────────────────────────────────────


async def test_pool_fetch_single():
    """Acquire a single tab from the pool and fetch a page."""
    from yosoi_driver import BrowserPool

    pool = await BrowserPool.from_env()
    async with pool, await pool.acquire() as tab:
        await tab.navigate('https://example.com')
        html = await tab.content()
        assert 'Example Domain' in html


async def test_pool_fetch_parallel():
    """Fetch multiple pages concurrently through the pool."""
    from yosoi_driver import BrowserPool

    async def pool_fetch(p: BrowserPool, url: str) -> str:
        async with await p.acquire() as tab:
            await tab.navigate(url)
            return await tab.content()

    pool = await BrowserPool.from_env()
    async with pool:
        results = await asyncio.gather(
            *[
                pool_fetch(pool, url)
                for url in [
                    'https://example.com',
                    'https://example.com',
                    'https://example.com',
                ]
            ]
        )
        assert all('Example Domain' in r for r in results)


async def test_pool_tab_recycled(monkeypatch: pytest.MonkeyPatch):
    """Tabs returned to the pool increment their use_count."""
    from yosoi_driver import BrowserPool

    # Force a single tab so we're guaranteed to get the same one back
    monkeypatch.setenv('TABS_PER_BROWSER', '1')
    pool = await BrowserPool.from_env()
    async with pool:
        # First acquire — fresh tab
        tab = await pool.acquire()
        assert tab.use_count == 0
        await pool.release(tab)

        # Second acquire — recycled tab
        tab = await pool.acquire()
        assert tab.use_count == 1
        await pool.release(tab)


# ── BrowserFetcher with pool ───────────────────────────────────────────


async def test_browser_fetcher_uses_pool():
    """BrowserFetcher backed by pool can fetch multiple URLs."""
    fetcher = create_fetcher('browser', no_sandbox=True)
    assert isinstance(fetcher, BrowserFetcher)

    async with fetcher:
        r1 = await fetcher.fetch('https://example.com')
        r2 = await fetcher.fetch('https://example.com')
        assert r1.html is not None
        assert r2.html is not None
        assert 'Example Domain' in r1.html
        assert 'Example Domain' in r2.html
