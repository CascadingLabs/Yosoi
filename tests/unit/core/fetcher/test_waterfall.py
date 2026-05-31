"""Tests for yosoi.core.fetcher.waterfall."""

from __future__ import annotations

import pytest

from yosoi.core.fetcher.base import ContentAnalyzer
from yosoi.core.fetcher.voiddriver import _VoidCrawlFetcher
from yosoi.core.fetcher.waterfall import JSFetcher
from yosoi.models.results import FetchResult


class _Console:
    def print(self, *_args: object, **_kwargs: object) -> None:
        pass


class _Simple:
    async def fetch(self, url: str) -> FetchResult:
        html = '<html><body><div data-fw="react"><astro-island></astro-island></div></body></html>'
        return FetchResult(url=url, html=html, metadata=ContentAnalyzer.analyze(html))


class _Headless:
    async def _do_fetch(
        self, url: str, start_time: float, tier: str, action_scripts: dict | None = None
    ) -> FetchResult:
        return FetchResult(url=url, html='<html><body><article>rendered</article></body></html>', fetch_time=start_time)


@pytest.mark.asyncio
async def test_waterfall_escalates_astro_shell_instead_of_caching_simple(mocker):
    fetcher = JSFetcher(console=_Console())
    fetcher._simple = _Simple()
    fetcher._strategy_storage = mocker.Mock()
    fetcher._strategy_storage.save = mocker.AsyncMock()
    fetcher._probe_requires_js = mocker.AsyncMock(return_value=False)
    fetcher._ensure_headless = mocker.AsyncMock(return_value=_Headless())

    result = await fetcher._fetch_waterfall('https://qscrape.dev/l2/news/?id=MHH-001', 'qscrape.dev', 1.0)

    assert result.html == '<html><body><article>rendered</article></body></html>'
    assert fetcher._strategy_cache['qscrape.dev'].fetcher == 'headless'
    assert fetcher._strategy_cache['qscrape.dev'].selector_level is None
    fetcher._strategy_storage.save.assert_called_once_with('qscrape.dev', 'headless')


def test_a3node_is_disabled_by_default_on_browser_fetcher():
    fetcher = _VoidCrawlFetcher()

    assert fetcher._experimental_a3node is False
    assert fetcher._a3node_storage is None
    assert fetcher._a3node_cache == {}


def test_browser_executable_path_is_retained_for_browser_config():
    fetcher = _VoidCrawlFetcher(browser_executable_path='/opt/chrome')

    assert fetcher.browser_executable_path == '/opt/chrome'


def test_jsfetcher_passes_explicit_a3node_opt_in_to_chrome_tiers():
    fetcher = JSFetcher(experimental_a3node=True)

    assert fetcher._chrome_kwargs['experimental_a3node'] is True


async def test_update_selector_level_preserves_cached_fetcher(mocker):
    fetcher = JSFetcher()
    fetcher._strategy_storage = mocker.Mock()
    fetcher._strategy_storage.save = mocker.AsyncMock()
    await fetcher._record_success('qscrape.dev', 'headless')

    await fetcher.update_selector_level('qscrape.dev', 'xpath')

    assert fetcher._strategy_cache['qscrape.dev'].fetcher == 'headless'
    assert fetcher._strategy_cache['qscrape.dev'].selector_level == 'xpath'
    fetcher._strategy_storage.save.assert_any_call('qscrape.dev', 'headless', selector_level='xpath')
