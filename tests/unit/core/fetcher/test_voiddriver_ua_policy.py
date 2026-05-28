"""Tests for VoidCrawl UA policy wiring."""

from typing import ClassVar

from yosoi.core.fetcher.voiddriver import HeadlessFetcher


class BrowserConfigWithUa:
    model_fields: ClassVar[dict[str, object]] = {
        'headless': object(),
        'stealth': object(),
        'no_sandbox': object(),
        'chrome_executable': object(),
        'user_agent': object(),
        'locale': object(),
    }


class BrowserConfigWithoutUa:
    model_fields: ClassVar[dict[str, object]] = {
        'headless': object(),
        'stealth': object(),
        'no_sandbox': object(),
        'chrome_executable': object(),
    }


def test_browser_config_leaves_voidcrawl_identity_alone_by_default() -> None:
    fetcher = HeadlessFetcher()

    kwargs = fetcher._browser_config_kwargs(BrowserConfigWithUa)

    assert 'user_agent' not in kwargs
    assert 'locale' not in kwargs
    assert kwargs['headless'] is True


def test_browser_config_receives_explicit_yosoi_override_when_supported() -> None:
    user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36'
    fetcher = HeadlessFetcher(user_agent=user_agent, accept_language='en-US,en;q=0.9')

    kwargs = fetcher._browser_config_kwargs(BrowserConfigWithUa)

    assert kwargs['user_agent'] == user_agent
    assert kwargs['locale'] == 'en-US,en;q=0.9'
    assert kwargs['headless'] is True


def test_browser_config_skips_identity_for_older_voidcrawl() -> None:
    user_agent = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36'
    )
    fetcher = HeadlessFetcher(user_agent=user_agent, accept_language='en-US,en;q=0.9')

    kwargs = fetcher._browser_config_kwargs(BrowserConfigWithoutUa)

    assert 'user_agent' not in kwargs
    assert 'locale' not in kwargs
