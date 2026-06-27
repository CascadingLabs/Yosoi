"""ScrapePolicy.cross_origin_dom opt-in → site-isolation flag on browser fetchers (VoidCrawl >= 0.3.5)."""

from typing import ClassVar

from yosoi.core.fetcher.voiddriver import HeadlessFetcher

ISOLATION_ARG = 'disable-site-isolation-trials'


class BrowserConfigWithExtraArgs:
    model_fields: ClassVar[dict[str, object]] = {
        'headless': object(),
        'stealth': object(),
        'no_sandbox': object(),
        'chrome_executable': object(),
        'extra_args': object(),
    }


class BrowserConfigWithoutExtraArgs:
    model_fields: ClassVar[dict[str, object]] = {
        'headless': object(),
        'stealth': object(),
        'no_sandbox': object(),
        'chrome_executable': object(),
    }


class BrowserConfigWithUserDataDir(BrowserConfigWithExtraArgs):
    model_fields: ClassVar[dict[str, object]] = {
        **BrowserConfigWithExtraArgs.model_fields,
        'user_data_dir': object(),
    }


def test_isolation_stays_intact_by_default() -> None:
    kwargs = HeadlessFetcher()._browser_config_kwargs(BrowserConfigWithExtraArgs)

    assert ISOLATION_ARG not in kwargs.get('extra_args', [])


def test_opt_in_appends_isolation_flag() -> None:
    fetcher = HeadlessFetcher(cross_origin_dom=True)

    kwargs = fetcher._browser_config_kwargs(BrowserConfigWithExtraArgs)

    assert kwargs['extra_args'] == [ISOLATION_ARG]


def test_opt_in_skipped_for_older_voidcrawl_without_extra_args() -> None:
    fetcher = HeadlessFetcher(cross_origin_dom=True)

    kwargs = fetcher._browser_config_kwargs(BrowserConfigWithoutExtraArgs)

    assert 'extra_args' not in kwargs


def test_opt_in_composes_with_identity_profile_args() -> None:
    from yosoi.core.fetcher.identity import BrowserIdentity

    fetcher = HeadlessFetcher(
        cross_origin_dom=True,
        identity=BrowserIdentity(id='warm', profile_dir='/tmp/profile'),
    )

    kwargs = fetcher._browser_config_kwargs(BrowserConfigWithExtraArgs)

    assert kwargs['extra_args'][-1] == ISOLATION_ARG
    assert any('--user-data-dir=/tmp/profile' in arg for arg in kwargs['extra_args'])


def test_identity_profile_uses_native_voidcrawl_user_data_dir_when_available() -> None:
    from yosoi.core.fetcher.identity import BrowserIdentity

    fetcher = HeadlessFetcher(identity=BrowserIdentity(id='warm', profile_dir='/tmp/profile'))

    kwargs = fetcher._browser_config_kwargs(BrowserConfigWithUserDataDir)

    assert kwargs['user_data_dir'] == '/tmp/profile'
    assert '--user-data-dir=/tmp/profile' not in kwargs.get('extra_args', [])


def test_jsfetcher_threads_flag_to_chrome_tiers() -> None:
    from yosoi.core.fetcher.waterfall import JSFetcher

    fetcher = JSFetcher(cross_origin_dom=True)

    assert fetcher._chrome_kwargs['cross_origin_dom'] is True
