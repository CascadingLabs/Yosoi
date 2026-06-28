"""Tests for _VoidCrawlFetcher A3Node replay wiring — no browser required."""

from __future__ import annotations

from pytest_mock import MockerFixture

from yosoi.core.fetcher.dom.loader import LoadResult
from yosoi.core.fetcher.identity import BrowserIdentity
from yosoi.core.fetcher.voiddriver import HeadlessFetcher
from yosoi.models.download import DownloadSpec
from yosoi.models.selectors import SelectorEntry
from yosoi.storage.a3node import A3Fragment, A3Node, ActRecord


def _fetcher(mocker: MockerFixture) -> HeadlessFetcher:
    f = HeadlessFetcher(experimental_a3node=True, min_content_length=10)
    f._a3node_storage = mocker.MagicMock()
    f._a3node_storage.record_replay = mocker.AsyncMock()
    f._console = mocker.MagicMock()
    return f


def _node(acts: list[ActRecord]) -> A3Node:
    return A3Node(domain='x.com', acts=acts, discovered_at='2026-01-01', replay_count=0)


async def test_probe_tries_fragment_bank_before_full_domloader_and_mints_new_fragments(mocker: MockerFixture):
    f = _fetcher(mocker)
    target = SelectorEntry(type='role', value='button', name='Accept additional cookies', nth=0)
    fragment = A3Fragment(
        fragment_key='frag-cookie',
        kind='cookie',
        target=target,
        source_domain='learned.example',
    )
    fragment_act = ActRecord('cookie', 1, target=target)
    probe_act = ActRecord('load_more', 2)
    f._a3node_storage.load_fragments = mocker.AsyncMock(return_value=[fragment])
    f._a3node_storage.record_fragment_replay = mocker.AsyncMock()
    f._a3node_storage.save_fragments_from_acts = mocker.AsyncMock()
    f._a3node_storage.save = mocker.AsyncMock()
    f._a3node_storage.load = mocker.AsyncMock(return_value=_node([fragment_act, probe_act]))

    loader = mocker.MagicMock()
    loader.replay_fragments = mocker.AsyncMock(
        return_value=LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=1, acts=[fragment_act])
    )
    loader.run = mocker.AsyncMock(
        return_value=LoadResult(
            success=True,
            content_start=0,
            content_final=5,
            elapsed_ms=2,
            html='<html>' + 'x' * 100 + '</html>',
            acts=[probe_act],
        )
    )
    mocker.patch('yosoi.core.fetcher.voiddriver.DOMLoader', return_value=loader)
    tab = object()

    html = await f._fetch_with_probe(tab, 'fresh.example')

    assert html is not None
    f._a3node_storage.load_fragments.assert_awaited_once_with(kinds={'age_gate', 'cookie', 'popup'}, limit=8)
    loader.replay_fragments.assert_awaited_once_with(tab, [fragment])
    f._a3node_storage.record_fragment_replay.assert_awaited_once_with('frag-cookie')
    f._a3node_storage.save.assert_awaited_once_with('fresh.example', [fragment_act, probe_act])
    f._a3node_storage.save_fragments_from_acts.assert_awaited_once_with('fresh.example', [fragment_act, probe_act])


def test_a3node_scope_splits_paths_contract_intent_and_browser_profile():
    first = HeadlessFetcher(experimental_a3node=True, min_content_length=10, a3node_intent='sig:a')
    same_shape = first._a3node_scope('https://example.com/a?q=one', 'example.com', 'headless', None, None)
    same_shape_other_value = first._a3node_scope('https://example.com/a?q=two', 'example.com', 'headless', None, None)
    other_path = first._a3node_scope('https://example.com/b?q=one', 'example.com', 'headless', None, None)
    other_contract = HeadlessFetcher(experimental_a3node=True, min_content_length=10, a3node_intent='sig:b')
    other_contract_scope = other_contract._a3node_scope(
        'https://example.com/a?q=one', 'example.com', 'headless', None, None
    )
    headful = HeadlessFetcher(experimental_a3node=True, min_content_length=10, a3node_intent='sig:a')
    headful_scope = headful._a3node_scope('https://example.com/a?q=one', 'example.com', 'headful', None, None)

    assert same_shape.scope_key == same_shape_other_value.scope_key
    assert (
        len({same_shape.scope_key, other_path.scope_key, other_contract_scope.scope_key, headful_scope.scope_key}) == 4
    )


def test_a3node_scope_splits_action_and_download_intent():
    fetcher = HeadlessFetcher(experimental_a3node=True, min_content_length=10, a3node_intent='sig:a')
    url = 'https://example.com/a?q=one'

    base = fetcher._a3node_scope(url, 'example.com', 'headless', None, None)
    action_a = fetcher._a3node_scope(url, 'example.com', 'headless', {'field': 'window.a'}, None)
    action_b = fetcher._a3node_scope(url, 'example.com', 'headless', {'field': 'window.b'}, None)
    download_a = fetcher._a3node_scope(
        url,
        'example.com',
        'headless',
        None,
        {'file': DownloadSpec(field='file', url='https://example.com/a.pdf', allowed_types=('application/pdf',))},
    )
    download_b = fetcher._a3node_scope(
        url,
        'example.com',
        'headless',
        None,
        {'file': DownloadSpec(field='file', url='https://example.com/b.pdf', allowed_types=('application/pdf',))},
    )

    assert (
        len({base.scope_key, action_a.scope_key, action_b.scope_key, download_a.scope_key, download_b.scope_key}) == 5
    )


def test_a3node_browser_fingerprint_splits_custom_ua_proxy_and_geo():
    url = 'https://example.com/a?q=one'
    ua_a = HeadlessFetcher(experimental_a3node=True, min_content_length=10, user_agent='ua-a')
    ua_b = HeadlessFetcher(experimental_a3node=True, min_content_length=10, user_agent='ua-b')
    proxy_a = HeadlessFetcher(
        experimental_a3node=True,
        min_content_length=10,
        identity=BrowserIdentity(id='same', proxy='http://proxy-a'),
    )
    proxy_b = HeadlessFetcher(
        experimental_a3node=True,
        min_content_length=10,
        identity=BrowserIdentity(id='same', proxy='http://proxy-b'),
    )
    geo_a = HeadlessFetcher(
        experimental_a3node=True,
        min_content_length=10,
        identity=BrowserIdentity(id='same', geo=(38.2527, -85.7585)),
    )
    geo_b = HeadlessFetcher(
        experimental_a3node=True,
        min_content_length=10,
        identity=BrowserIdentity(id='same', geo=(40.7128, -74.0060)),
    )

    scopes = {
        ua_a._a3node_scope(url, 'example.com', 'headless', None, None).scope_key,
        ua_b._a3node_scope(url, 'example.com', 'headless', None, None).scope_key,
        proxy_a._a3node_scope(url, 'example.com', 'headless', None, None).scope_key,
        proxy_b._a3node_scope(url, 'example.com', 'headless', None, None).scope_key,
        geo_a._a3node_scope(url, 'example.com', 'headless', None, None).scope_key,
        geo_b._a3node_scope(url, 'example.com', 'headless', None, None).scope_key,
    }
    assert len(scopes) == 6


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
