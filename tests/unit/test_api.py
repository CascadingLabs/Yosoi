"""Tests for the high-level programmatic API."""

from typing import ClassVar

import pytest

import yosoi as ys
from yosoi import api
from yosoi.models.contract import Contract


class ApiContract(Contract):
    title: str = ys.Title()


class FakePipeline:
    """Pipeline test double that captures constructor and scrape arguments."""

    instances: ClassVar[list['FakePipeline']] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.scrape_kwargs: dict[str, object] | None = None
        FakePipeline.instances.append(self)

    async def __aenter__(self) -> 'FakePipeline':
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None

    async def scrape(self, url: str, **kwargs: object):
        self.scrape_kwargs = {'url': url, **kwargs}
        yield {'title': 'Example'}


async def test_scrape_returns_native_items_without_default_file_output(monkeypatch):
    """scrape() collects pipeline output and disables file output by default."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = await api.scrape('https://example.com', ApiContract, model=ys.opencode())

    assert result == [{'title': 'Example'}]
    instance = FakePipeline.instances[0]
    assert instance.kwargs['contract'] is ApiContract
    assert instance.kwargs['output_format'] == []
    assert instance.kwargs['quiet'] is True
    assert instance.scrape_kwargs is not None
    assert instance.scrape_kwargs['output_format'] == []


async def test_scrape_resolves_contract_name(monkeypatch):
    """scrape() accepts built-in or registered contract names."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = await api.scrape('https://example.com', 'ApiContract', model=ys.claude_sdk())

    assert result == [{'title': 'Example'}]
    assert FakePipeline.instances[0].kwargs['contract'] is ApiContract


async def test_scrape_propagates_exception_and_logs_warning(monkeypatch):
    """scrape() re-raises pipeline exceptions after logging a warning (lines 65-67)."""

    class BrokenPipeline:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def scrape(self, url, **kwargs):
            raise ValueError('discovery failed')
            yield  # make it a generator

    monkeypatch.setattr(api, 'Pipeline', BrokenPipeline)

    with pytest.raises(ValueError, match='discovery failed'):
        await api.scrape('https://example.com', ApiContract, model=ys.opencode())


async def test_scrape_many_returns_dict_keyed_by_url(monkeypatch):
    """scrape_many() returns {url: items} for each URL (lines 83-106)."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = await api.scrape_many(['https://a.com', 'https://b.com'], ApiContract, model=ys.opencode())

    assert set(result.keys()) == {'https://a.com', 'https://b.com'}
    assert result['https://a.com'] == [{'title': 'Example'}]
    assert result['https://b.com'] == [{'title': 'Example'}]


async def test_scrape_many_propagates_url_exception(monkeypatch):
    """scrape_many() re-raises exceptions from individual URL scrapes (lines 103-105)."""

    class BrokenPipeline:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def scrape(self, url, **kwargs):
            raise RuntimeError('network error')
            yield

    monkeypatch.setattr(api, 'Pipeline', BrokenPipeline)

    with pytest.raises(RuntimeError, match='network error'):
        await api.scrape_many(['https://fail.com'], ApiContract, model=ys.opencode())


def test_scrape_sync_without_event_loop(monkeypatch):
    """scrape_sync() succeeds when there is no running event loop (lines 122-138)."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = api.scrape_sync('https://example.com', ApiContract, model=ys.opencode())

    assert result == [{'title': 'Example'}]


async def test_scrape_sync_raises_inside_event_loop(monkeypatch):
    """scrape_sync() raises RuntimeError when called from an active event loop (lines 139-141)."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    with pytest.raises(RuntimeError, match='active event loop'):
        api.scrape_sync('https://example.com', ApiContract, model=ys.opencode())


def test_resolve_model_none_calls_auto_config(monkeypatch):
    """_resolve_model(None) delegates to auto_config() with no arguments (line 146)."""
    sentinel = object()
    monkeypatch.setattr(api, 'auto_config', lambda **_kw: sentinel)

    result = api._resolve_model(None)

    assert result is sentinel


def test_resolve_model_string_passes_model_name(monkeypatch):
    """_resolve_model('name') delegates to auto_config(model='name') (line 148)."""
    captured: dict[str, object] = {}

    def fake_auto_config(**kw: object) -> object:
        captured.update(kw)
        return object()

    monkeypatch.setattr(api, 'auto_config', fake_auto_config)

    api._resolve_model('my-model')

    assert captured.get('model') == 'my-model'
