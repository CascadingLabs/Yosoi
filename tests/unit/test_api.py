"""Tests for the high-level programmatic API."""

from typing import ClassVar

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
