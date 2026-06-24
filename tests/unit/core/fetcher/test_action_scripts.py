"""Tests for ys.js action script composition, merging, and L0 fetcher warning."""

from __future__ import annotations

import contextlib
import logging

import httpx2
import pytest

from yosoi.core.fetcher.simple import SimpleFetcher
from yosoi.core.fetcher.voiddriver import _VoidCrawlFetcher
from yosoi.core.pipeline import Pipeline

# ---------------------------------------------------------------------------
# _compose_action_scripts — pure string/JS composition
# ---------------------------------------------------------------------------


def test_compose_single_script():
    result = _VoidCrawlFetcher._compose_action_scripts({'title': 'document.title'})
    assert 'out["title"]' in result
    assert 'document.title' in result
    assert result.startswith('(()=>{')
    assert result.endswith('})()')


def test_compose_multiple_scripts_all_present():
    result = _VoidCrawlFetcher._compose_action_scripts(
        {
            'title': 'document.title',
            'count': 'document.querySelectorAll("p").length',
        }
    )
    assert 'out["title"]' in result
    assert 'out["count"]' in result


def test_compose_key_with_double_quote_is_escaped():
    """Field names containing " must appear JSON-encoded in the composed JS."""
    import json

    key = 'my"field'
    result = _VoidCrawlFetcher._compose_action_scripts({key: '1'})
    # json.dumps produces the properly escaped JS string literal
    assert json.dumps(key) in result


def test_compose_key_with_backslash_is_escaped():
    result = _VoidCrawlFetcher._compose_action_scripts({'a\\b': '2'})
    assert r'a\\b' in result


def test_compose_wraps_each_script_in_try_catch():
    result = _VoidCrawlFetcher._compose_action_scripts({'x': 'throw new Error("boom")'})
    assert 'try {' in result
    assert 'catch(e)' in result
    assert 'null' in result


def test_compose_empty_scripts_produces_valid_js():
    result = _VoidCrawlFetcher._compose_action_scripts({})
    # Should still be a valid IIFE returning an empty object
    assert result == '(()=>{ const out={}; ; return out; })()'


# ---------------------------------------------------------------------------
# Pipeline._merge_js_outputs — dict / list / None branches
# ---------------------------------------------------------------------------


def test_merge_into_none_returns_js_outputs_as_dict():
    result = Pipeline._merge_js_outputs(None, {'has_alita': True})
    assert result == {'has_alita': True}


def test_merge_into_single_dict():
    result = Pipeline._merge_js_outputs({'title': 'Hello'}, {'has_alita': False})
    assert result == {'title': 'Hello', 'has_alita': False}


def test_merge_into_list_broadcasts_to_every_item():
    extracted = [{'title': 'A'}, {'title': 'B'}]
    result = Pipeline._merge_js_outputs(extracted, {'flag': True})
    assert result == [{'title': 'A', 'flag': True}, {'title': 'B', 'flag': True}]


def test_merge_with_none_js_outputs_is_noop():
    extracted = {'title': 'Hello'}
    result = Pipeline._merge_js_outputs(extracted, None)
    assert result is extracted


def test_merge_with_empty_js_outputs_is_noop():
    extracted = {'title': 'Hello'}
    result = Pipeline._merge_js_outputs(extracted, {})
    assert result is extracted


def test_merge_js_outputs_overwrite_existing_key():
    """JS output takes precedence over CSS-extracted value for same key."""
    result = Pipeline._merge_js_outputs({'signals': 'old'}, {'signals': {'new': True}})
    assert result == {'signals': {'new': True}}


# ---------------------------------------------------------------------------
# SimpleFetcher — warning emitted when action_scripts provided
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simple_fetcher_warns_when_action_scripts_provided(caplog, mocker):
    fetcher = SimpleFetcher(use_session=False, min_delay=0)
    mocker.patch(
        'httpx2.AsyncClient.get',
        return_value=httpx2.Response(200, text='<html><body>' + ('content ' * 20) + '</body></html>'),
    )
    with caplog.at_level(logging.WARNING, logger='yosoi.core.fetcher.simple'), contextlib.suppress(Exception):
        await fetcher.fetch('https://example.com', action_scripts={'x': '1'})
    assert any('action_scripts ignored' in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_simple_fetcher_no_warning_without_action_scripts(caplog, mocker):
    fetcher = SimpleFetcher(use_session=False, min_delay=0)
    mocker.patch(
        'httpx2.AsyncClient.get',
        return_value=httpx2.Response(200, text='<html><body>' + ('content ' * 20) + '</body></html>'),
    )
    with caplog.at_level(logging.WARNING, logger='yosoi.core.fetcher.simple'), contextlib.suppress(Exception):
        await fetcher.fetch('https://example.com')
    assert not any('action_scripts ignored' in r.message for r in caplog.records)
