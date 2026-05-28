"""Opt-in live smoke tests for Yosoi's VoidCrawl-backed bot-check wiring."""

from __future__ import annotations

import os

import pytest

from yosoi.core.fetcher.voiddriver import _import_voidcrawl

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.getenv('YOSOI_LIVE_SMOKE') != '1',
        reason='set YOSOI_LIVE_SMOKE=1 to run live VoidCrawl smoke tests',
    ),
]


BOTCHECK_URL = 'https://botcheck.com/'


@pytest.mark.asyncio
async def test_botcheck_renders_with_yosoi_voidcrawl_wiring() -> None:
    BrowserPool, BrowserConfig, PoolConfig = _import_voidcrawl()
    config = PoolConfig(
        browsers=1,
        tabs_per_browser=1,
        browser=BrowserConfig(headless=False, stealth=True),
    )

    async with BrowserPool(config) as pool, pool.acquire() as tab:
        await tab.goto(BOTCHECK_URL, timeout=60.0)
        await tab.wait_for_network_idle(timeout=10.0)
        html = (await tab.content()).lower()

    assert 'bot' in html
    assert 'challenge-platform' not in html
    assert 'just a moment' not in html
