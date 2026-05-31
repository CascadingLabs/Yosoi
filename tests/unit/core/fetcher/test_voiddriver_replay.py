"""Tests for _VoidCrawlFetcher A3Node replay wiring — no browser required."""

from __future__ import annotations

from pytest_mock import MockerFixture

from yosoi.core.fetcher.dom.loader import LoadResult
from yosoi.core.fetcher.voiddriver import HeadlessFetcher
from yosoi.storage.a3node import A3Node, ActRecord


def _fetcher(mocker: MockerFixture) -> HeadlessFetcher:
    f = HeadlessFetcher(experimental_a3node=True, min_content_length=10)
    f._a3node_storage = mocker.MagicMock()
    f._a3node_storage.record_replay = mocker.AsyncMock()
    f._console = mocker.MagicMock()
    return f


def _node(acts: list[ActRecord]) -> A3Node:
    return A3Node(domain='x.com', acts=acts, discovered_at='2026-01-01', replay_count=0)


async def test_replay_success_records_replay(mocker: MockerFixture):
    f = _fetcher(mocker)
    good = LoadResult(success=True, content_start=0, content_final=5, elapsed_ms=1.0, html='<html>' + 'x' * 100)
    replay = mocker.patch('yosoi.core.fetcher.voiddriver.DOMLoader.replay', mocker.AsyncMock(return_value=good))
    probe = mocker.patch.object(f, '_fetch_with_probe', mocker.AsyncMock())

    html = await f._fetch_with_replay(object(), 'x.com', _node([ActRecord('load_more', 2)]))

    assert html == good.html
    replay.assert_awaited_once()
    f._a3node_storage.record_replay.assert_awaited_once_with('x.com')
    probe.assert_not_called()


async def test_replay_too_short_falls_back_to_probe(mocker: MockerFixture):
    f = _fetcher(mocker)
    short = LoadResult(success=False, content_start=0, content_final=0, elapsed_ms=1.0, html=None)
    mocker.patch('yosoi.core.fetcher.voiddriver.DOMLoader.replay', mocker.AsyncMock(return_value=short))
    probe = mocker.patch.object(f, '_fetch_with_probe', mocker.AsyncMock(return_value='probed-html'))

    html = await f._fetch_with_replay(object(), 'x.com', _node([ActRecord('load_more', 1)]))

    assert html == 'probed-html'
    probe.assert_awaited_once()  # replay fell short → full probe ran
    f._a3node_storage.record_replay.assert_not_awaited()


async def test_empty_recipe_captures_without_probe(mocker: MockerFixture):
    f = _fetcher(mocker)
    tab = mocker.MagicMock()
    tab.content = mocker.AsyncMock(return_value='<html>' + 'y' * 100 + '</html>')
    replay = mocker.patch('yosoi.core.fetcher.voiddriver.DOMLoader.replay', mocker.AsyncMock())

    html = await f._fetch_with_replay(tab, 'x.com', _node([]))  # empty recipe = no actions needed

    assert html is not None
    replay.assert_not_called()  # empty recipe never enters the act-replay path
    f._a3node_storage.record_replay.assert_awaited_once_with('x.com')
