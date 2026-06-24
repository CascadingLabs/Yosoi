"""Tests for VoidCrawl UA policy wiring."""

import asyncio
import os
import sys
import types
from typing import Any, ClassVar

from yosoi.core.fetcher.voiddriver import HeadlessFetcher, _import_voidcrawl


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


def test_headless_fetcher_uses_policy_chrome_ws_urls(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeBrowserPool:
        def __init__(self, config: Any) -> None:
            captured['config'] = config

        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeBrowserConfig:
        model_fields: ClassVar[dict[str, object]] = BrowserConfigWithoutUa.model_fields

        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class FakePoolConfig:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(
        'yosoi.core.fetcher.voiddriver._import_voidcrawl',
        lambda: (FakeBrowserPool, FakeBrowserConfig, FakePoolConfig),
    )
    fetcher = HeadlessFetcher(chrome_ws_urls=('http://127.0.0.1:9222',))

    async def run() -> None:
        async with fetcher:
            pass

    asyncio.run(run())

    assert captured['config'].kwargs['chrome_ws_urls'] == ['http://127.0.0.1:9222']


def test_browser_config_skips_identity_for_older_voidcrawl() -> None:
    user_agent = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36'
    )
    fetcher = HeadlessFetcher(user_agent=user_agent, accept_language='en-US,en;q=0.9')

    kwargs = fetcher._browser_config_kwargs(BrowserConfigWithoutUa)

    assert 'user_agent' not in kwargs
    assert 'locale' not in kwargs


def test_import_voidcrawl_sets_default_rust_log_filter(monkeypatch) -> None:
    module = types.SimpleNamespace(BrowserConfig=object, BrowserPool=object, PoolConfig=object)
    monkeypatch.setitem(sys.modules, 'voidcrawl', module)
    monkeypatch.delenv('RUST_LOG', raising=False)

    _import_voidcrawl()

    assert 'chromiumoxide::handler=error' in os.environ['RUST_LOG']


def test_import_voidcrawl_preserves_explicit_rust_log(monkeypatch) -> None:
    module = types.SimpleNamespace(BrowserConfig=object, BrowserPool=object, PoolConfig=object)
    monkeypatch.setitem(sys.modules, 'voidcrawl', module)
    monkeypatch.setenv('RUST_LOG', 'debug')

    _import_voidcrawl()

    assert os.environ['RUST_LOG'] == 'debug'
