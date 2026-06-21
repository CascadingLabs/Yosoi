"""Tests for yosoi.core.fetcher.waterfall."""

from __future__ import annotations

import asyncio

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
        self,
        url: str,
        start_time: float,
        tier: str,
        action_scripts: dict | None = None,
        download_specs: dict | None = None,
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
        def __init__(self, **_kwargs):  # type: ignore[no-untyped-def]
            pass

        async def __aenter__(self):  # type: ignore[no-untyped-def]
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
        def __init__(self, **_kwargs):  # type: ignore[no-untyped-def]
            pass

        async def __aenter__(self):  # type: ignore[no-untyped-def]
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

    async def _do_fetch(self, url, start_time, tier, action_scripts=None, download_specs=None):  # type: ignore[no-untyped-def]
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

    async def fake_start(identity, base_kwargs):  # type: ignore[no-untyped-def]
        class _Ident:
            async def _do_fetch(self, url, start_time, tier, action_scripts=None, download_specs=None):  # type: ignore[no-untyped-def]
                if identity.id == 'fresh':
                    raise BotDetectionError(url, 200, ['recaptcha'], identity_id='fresh')
                return FetchResult(url=url, html='<html><body>serp results here</body></html>')

            async def close(self):  # type: ignore[no-untyped-def]
                pass

        return _Ident()

    fetcher._start_identity_fetcher = fake_start  # type: ignore[assignment,method-assign]

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

    async def fake_start(identity, base_kwargs):  # type: ignore[no-untyped-def]
        class _Ident:
            async def _do_fetch(self, url, start_time, tier, action_scripts=None, download_specs=None):  # type: ignore[no-untyped-def]
                raise BotDetectionError(url, 200, ['blocked'], identity_id=identity.id)

            async def close(self):  # type: ignore[no-untyped-def]
                pass

        return _Ident()

    fetcher._start_identity_fetcher = fake_start  # type: ignore[assignment,method-assign]

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
