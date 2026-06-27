"""Tests for yosoi.core.fetcher.waterfall."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from yosoi.core.fetcher.base import ContentAnalyzer
from yosoi.core.fetcher.voiddriver import _crawl_frontier_signature, _VoidCrawlFetcher
from yosoi.core.fetcher.waterfall import JSFetcher
from yosoi.models.results import FetchResult


class _Console:
    def print(self, *_args: object, **_kwargs: object) -> None:
        pass


class _HydratingTab:
    def __init__(self) -> None:
        self.calls = 0

    async def content(self) -> str:
        self.calls += 1
        if self.calls == 1:
            return '<html><body><main>loading</main></body></html>'
        return '<html><body><a href="/ready">ready</a></body></html>'


class _Simple:
    def __init__(self, html: str | None = None) -> None:
        self.html = html or '<html><body><div data-fw="react"><astro-island></astro-island></div></body></html>'

    async def fetch(self, url: str) -> FetchResult:
        return FetchResult(url=url, html=self.html, metadata=ContentAnalyzer.analyze(self.html))


class _Headless:
    def __init__(self, *, crawl_result: FetchResult | None = None) -> None:
        self.crawl_calls = 0
        self.full_calls = 0
        self.crawl_result = crawl_result

    async def _do_fetch_crawl(self, url: str, start_time: float, tier: str) -> FetchResult:
        self.crawl_calls += 1
        if self.crawl_result is not None:
            return self.crawl_result
        return FetchResult(url=url, html='<html><body><a href="/next">next</a></body></html>', fetch_time=start_time)

    async def _do_fetch(
        self,
        url: str,
        start_time: float,
        tier: str,
        action_scripts: dict | None = None,
        download_specs: dict | None = None,
    ) -> FetchResult:
        self.full_calls += 1
        return FetchResult(url=url, html='<html><body><article>rendered</article></body></html>', fetch_time=start_time)


def test_crawl_frontier_signature_tracks_href_identity_not_just_count() -> None:
    first = '<html><body><a href="/aa">A</a></body></html>'
    second = '<html><body><a href="/bb">A</a></body></html>'

    assert len(first) == len(second)
    assert _crawl_frontier_signature(first) != _crawl_frontier_signature(second)


@pytest.mark.asyncio
async def test_crawl_frontier_content_waits_for_link_inventory_to_stabilize(mocker):
    mocker.patch('yosoi.core.fetcher.voiddriver.asyncio.sleep', mocker.AsyncMock())
    tab = _HydratingTab()

    html = await _VoidCrawlFetcher()._crawl_frontier_content(tab)

    assert html == '<html><body><a href="/ready">ready</a></body></html>'
    assert tab.calls == 3


@pytest.mark.asyncio
async def test_waterfall_accepts_simple_js_shell_for_crawl_discovery(mocker):
    fetcher = JSFetcher(console=_Console(), accept_simple_requires_js=True)
    fetcher._simple = _Simple()
    fetcher._strategy_storage = mocker.Mock()
    fetcher._strategy_storage.save = mocker.AsyncMock()
    fetcher._probe_requires_js = mocker.AsyncMock(return_value=False)
    fetcher._ensure_headless = mocker.AsyncMock(return_value=_Headless())

    result = await fetcher._fetch_waterfall('https://qscrape.dev/l2/news/?id=MHH-001', 'qscrape.dev', 1.0)

    assert result.html == '<html><body><div data-fw="react"><astro-island></astro-island></div></body></html>'
    assert 'qscrape.dev' not in fetcher._strategy_cache
    fetcher._strategy_storage.save.assert_not_called()
    fetcher._ensure_headless.assert_not_called()


@pytest.mark.asyncio
async def test_waterfall_crawl_frontier_accepts_simple_js_marked_html_with_links(mocker):
    html = (
        '<html><body><astro-island data-fw="react">'
        '<a href="/news/">news</a><a href="/products/">products</a><a href="/scores/">scores</a>'
        '</astro-island></body></html>'
    )
    fetcher = JSFetcher(console=_Console(), crawl_frontier_only=True)
    fetcher._simple = _Simple(html)
    fetcher._strategy_storage = mocker.Mock()
    fetcher._strategy_storage.save = mocker.AsyncMock()
    fetcher._probe_requires_js = mocker.AsyncMock(return_value=False)
    fetcher._ensure_headless = mocker.AsyncMock(return_value=_Headless())

    result = await fetcher._fetch_waterfall('https://qscrape.dev/l2/news/?id=MHH-001', 'qscrape.dev', 1.0)

    assert result.html == html
    fetcher._ensure_headless.assert_not_called()
    fetcher._strategy_storage.save.assert_not_called()


@pytest.mark.asyncio
async def test_waterfall_crawl_frontier_renders_js_marked_html_with_only_one_nav_link(mocker):
    html = '<html><body><astro-island data-fw="react"><a href="/next">next</a></astro-island></body></html>'
    fetcher = JSFetcher(console=_Console(), crawl_frontier_only=True)
    headless = _Headless()
    fetcher._simple = _Simple(html)
    fetcher._strategy_storage = mocker.Mock()
    fetcher._strategy_storage.save = mocker.AsyncMock()
    fetcher._probe_requires_js = mocker.AsyncMock(return_value=False)
    fetcher._ensure_headless = mocker.AsyncMock(return_value=headless)

    result = await fetcher._fetch_waterfall('https://qscrape.dev/l2/news/?id=MHH-001', 'qscrape.dev', 1.0)

    assert result.html == '<html><body><a href="/next">next</a></body></html>'
    assert headless.crawl_calls == 1


@pytest.mark.asyncio
async def test_waterfall_browser_tier_can_use_lightweight_crawl_fetch(mocker):
    fetcher = JSFetcher(console=_Console(), crawl_frontier_only=True)
    headless = _Headless()
    fetcher._simple = _Simple()
    fetcher._strategy_storage = mocker.Mock()
    fetcher._strategy_storage.save = mocker.AsyncMock()
    fetcher._probe_requires_js = mocker.AsyncMock(return_value=False)
    fetcher._ensure_headless = mocker.AsyncMock(return_value=headless)

    result = await fetcher._fetch_waterfall('https://qscrape.dev/l2/news/?id=MHH-001', 'qscrape.dev', 1.0)

    assert result.html == '<html><body><a href="/next">next</a></body></html>'
    assert headless.crawl_calls == 1
    assert headless.full_calls == 0
    fetcher._strategy_storage.save.assert_not_called()
    assert 'qscrape.dev' not in fetcher._strategy_cache


@pytest.mark.asyncio
async def test_waterfall_crawl_frontier_browser_tier_does_not_retry_timeouts(mocker):
    timeout_result = FetchResult(url='https://qscrape.dev/slow', html=None, block_reason='request timed out')
    headless = _Headless(crawl_result=timeout_result)
    fetcher = JSFetcher(console=_Console(), crawl_frontier_only=True)
    fetcher._simple = _Simple()
    fetcher._strategy_storage = mocker.Mock()
    fetcher._strategy_storage.save = mocker.AsyncMock()
    fetcher._probe_requires_js = mocker.AsyncMock(return_value=False)
    fetcher._ensure_headless = mocker.AsyncMock(return_value=headless)

    result = await fetcher._fetch_waterfall('https://qscrape.dev/slow', 'qscrape.dev', 1.0)

    assert result is timeout_result
    assert headless.crawl_calls == 1


@pytest.mark.asyncio
async def test_waterfall_escalates_astro_shell_by_default_instead_of_caching_simple(mocker):
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
    fetcher._strategy_storage.save.assert_called_once_with(
        'qscrape.dev', 'headless', selector_level=None, identity_id=None
    )


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


def test_jsfetcher_supports_browse_so_downloads_arent_gated_out():
    # Regression: the waterfall escalates to a browser tier and can run ys.File() downloads,
    # so the download gate (Pipeline._resolve_download_specs) must not reject fetcher_type=waterfall.
    assert JSFetcher().supports_browse is True


async def test_probe_does_not_force_browser_for_small_non_html_assets(mocker):
    class _Response:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {'content-type': 'application/pdf', 'content-length': '1200'}

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def head(self, *_args: object, **_kwargs: object) -> _Response:
            return _Response()

    mocker.patch('yosoi.core.fetcher.waterfall.httpx2.AsyncClient', _Client)

    assert await JSFetcher()._probe_requires_js('https://example.com/file.pdf') is False


async def test_update_selector_level_preserves_cached_fetcher(mocker):
    fetcher = JSFetcher()
    fetcher._strategy_storage = mocker.Mock()
    fetcher._strategy_storage.save = mocker.AsyncMock()
    await fetcher._record_success('qscrape.dev', 'headless')

    await fetcher.update_selector_level('qscrape.dev', 'xpath')

    assert fetcher._strategy_cache['qscrape.dev'].fetcher == 'headless'
    assert fetcher._strategy_cache['qscrape.dev'].selector_level == 'xpath'
    fetcher._strategy_storage.save.assert_any_call('qscrape.dev', 'headless', selector_level='xpath', identity_id=None)


@pytest.mark.asyncio
async def test_concurrent_headless_first_use_starts_one_shared_tier(mocker):
    """Concurrent crawl workers should share one lazily-started VoidCrawl tier."""
    starts = 0

    class _SlowHeadless:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _SlowHeadless:
            nonlocal starts
            starts += 1
            await asyncio.sleep(0.01)
            return self

    fetcher = JSFetcher(console=_Console())
    mocker.patch('yosoi.core.fetcher.waterfall.HeadlessFetcher', _SlowHeadless)

    tiers = await asyncio.gather(
        fetcher._ensure_headless(),
        fetcher._ensure_headless(),
        fetcher._ensure_headless(),
    )

    assert starts == 1
    assert tiers[0] is tiers[1] is tiers[2]


@pytest.mark.asyncio
async def test_concurrent_headful_first_use_starts_one_shared_tier(mocker):
    """Headful fallback has the same lazy-start race guard as headless."""
    starts = 0

    class _SlowHeadful:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _SlowHeadful:
            nonlocal starts
            starts += 1
            await asyncio.sleep(0.01)
            return self

    fetcher = JSFetcher(console=_Console())
    mocker.patch('yosoi.core.fetcher.waterfall.HeadfulFetcher', _SlowHeadful)

    tiers = await asyncio.gather(
        fetcher._ensure_headful(),
        fetcher._ensure_headful(),
        fetcher._ensure_headful(),
    )

    assert starts == 1
    assert tiers[0] is tiers[1] is tiers[2]


# ---------------------------------------------------------------------------
# W2 — profile cascade wiring in the waterfall terminal tier
# ---------------------------------------------------------------------------


class _BlockedHeadless:
    """Headless tier stub that always reports a bot block."""

    async def _do_fetch(
        self,
        url: str,
        start_time: float,
        tier: str,
        action_scripts: dict[str, str] | None = None,
        download_specs: dict[str, Any] | None = None,
    ) -> FetchResult:
        from yosoi.utils.exceptions import BotDetectionError

        raise BotDetectionError(url, 200, ['blocked'])


async def test_waterfall_terminal_tier_uses_cascade_when_configured(mocker):
    """A configured IdentityCascade replaces the best-effort headful terminal tier."""
    from yosoi.core.fetcher.identity import BrowserIdentity, IdentityCascade

    cascade = IdentityCascade((BrowserIdentity(id='fresh'), BrowserIdentity(id='proxy_a', proxy='http://1.2.3.4:8080')))
    fetcher = JSFetcher(console=_Console(), identity_cascade=cascade)
    fetcher._strategy_storage = mocker.Mock()
    fetcher._strategy_storage.save = mocker.AsyncMock()
    fetcher._probe_requires_js = mocker.AsyncMock(return_value=True)
    fetcher._ensure_headless = mocker.AsyncMock(return_value=_BlockedHeadless())

    # Cascade: 'fresh' blocks, 'proxy_a' wins.
    from yosoi.utils.exceptions import BotDetectionError

    async def fake_start(identity: BrowserIdentity, base_kwargs: dict[str, Any]) -> object:
        class _Ident:
            async def _do_fetch(
                self,
                url: str,
                start_time: float,
                tier: str,
                action_scripts: dict[str, str] | None = None,
                download_specs: dict[str, Any] | None = None,
            ) -> FetchResult:
                if identity.id == 'fresh':
                    raise BotDetectionError(url, 200, ['recaptcha'], identity_id='fresh')
                return FetchResult(url=url, html='<html><body>serp results here</body></html>')

            async def close(self) -> None:
                pass

        return _Ident()

    mocker.patch.object(fetcher, '_start_identity_fetcher', fake_start)

    result = await fetcher._fetch_waterfall('https://google.com/search?q=x', 'google.com', 1.0)

    assert result.html == '<html><body>serp results here</body></html>'
    # Winning identity persisted per-domain.
    assert fetcher._strategy_cache['google.com'].identity_id == 'proxy_a'
    assert fetcher._strategy_cache['google.com'].fetcher == 'headful'


async def test_waterfall_cascade_exhaustion_raises(mocker):
    """All identities blocked -> the waterfall RAISES (fail-fast), not empty result."""
    from yosoi.core.fetcher.identity import BrowserIdentity, IdentityCascade
    from yosoi.utils.exceptions import BotDetectionError

    cascade = IdentityCascade((BrowserIdentity(id='a'), BrowserIdentity(id='b')))
    fetcher = JSFetcher(console=_Console(), identity_cascade=cascade)
    fetcher._strategy_storage = mocker.Mock()
    fetcher._strategy_storage.save = mocker.AsyncMock()
    fetcher._probe_requires_js = mocker.AsyncMock(return_value=True)
    fetcher._ensure_headless = mocker.AsyncMock(return_value=_BlockedHeadless())

    async def fake_start(identity: BrowserIdentity, base_kwargs: dict[str, Any]) -> object:
        class _Ident:
            async def _do_fetch(
                self,
                url: str,
                start_time: float,
                tier: str,
                action_scripts: dict[str, str] | None = None,
                download_specs: dict[str, Any] | None = None,
            ) -> FetchResult:
                raise BotDetectionError(url, 200, ['blocked'], identity_id=identity.id)

            async def close(self) -> None:
                pass

        return _Ident()

    mocker.patch.object(fetcher, '_start_identity_fetcher', fake_start)

    with pytest.raises(BotDetectionError) as exc_info:
        await fetcher._fetch_waterfall('https://x.com', 'x.com', 1.0)
    assert exc_info.value.identity_id == 'b'  # last attempted identity, attributed


def test_jsfetcher_without_cascade_keeps_legacy_terminal_tier():
    fetcher = JSFetcher()
    assert fetcher._identity_cascade is None
    assert fetcher._identity_pool is None


def test_jsfetcher_accepts_single_identity_as_cascade():
    from yosoi.core.fetcher.identity import BrowserIdentity

    fetcher = JSFetcher(identity=BrowserIdentity(id='geo-us', geo=(40.7, -74.0)))

    assert fetcher._identity_cascade is not None
    assert fetcher._identity_cascade.identities[0].id == 'geo-us'
