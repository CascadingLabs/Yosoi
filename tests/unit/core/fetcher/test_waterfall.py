"""Tests for yosoi.core.fetcher.waterfall."""

from __future__ import annotations

import pytest

from yosoi.core.fetcher.base import ContentAnalyzer
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
    async def _do_fetch(self, url: str, start_time: float, tier: str) -> FetchResult:
        return FetchResult(url=url, html='<html><body><article>rendered</article></body></html>', fetch_time=start_time)


@pytest.mark.asyncio
async def test_waterfall_escalates_astro_shell_instead_of_caching_simple(mocker):
    fetcher = JSFetcher(console=_Console())
    fetcher._simple = _Simple()
    fetcher._strategy_storage = mocker.Mock()
    fetcher._probe_requires_js = mocker.AsyncMock(return_value=False)
    fetcher._ensure_headless = mocker.AsyncMock(return_value=_Headless())

    result = await fetcher._fetch_waterfall('https://qscrape.dev/l2/news/?id=MHH-001', 'qscrape.dev', 1.0)

    assert result.html == '<html><body><article>rendered</article></body></html>'
    assert fetcher._strategy_cache == {'qscrape.dev': 'headless'}
    fetcher._strategy_storage.save.assert_called_once_with('qscrape.dev', 'headless')
