"""Tests for JsScriptStorage — save, load, merge, cache miss."""

from __future__ import annotations

import pytest

from yosoi.storage.js_scripts import JsScriptEntry, JsScriptStorage


def _entry(script: str = '(() => true)()', verified: bool = True) -> JsScriptEntry:
    return JsScriptEntry(
        script=script,
        description='test field',
        discovered_at='2026-01-01T00:00:00+00:00',
        verified=verified,
        model='test',
        attempts=1,
    )


@pytest.mark.asyncio
async def test_load_returns_none_for_missing_domain(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    result = await storage.load('unknown.com', 'sig')
    assert result is None


@pytest.mark.asyncio
async def test_save_and_load_round_trip(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    await storage.save_entries('example.com', 'sig1', {'signals': _entry('(() => ({x:1}))()')})

    record = await storage.load('example.com', 'sig1')
    assert record is not None
    assert 'signals' in record.fields
    assert record.fields['signals'].script == '(() => ({x:1}))()'
    assert record.fields['signals'].verified is True


@pytest.mark.asyncio
async def test_save_entries_merges_with_existing(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    await storage.save_entries('example.com', 'sig', {'field_a': _entry('a')})
    await storage.save_entries('example.com', 'sig', {'field_b': _entry('b')})

    record = await storage.load('example.com', 'sig')
    assert record is not None
    assert 'field_a' in record.fields
    assert 'field_b' in record.fields


@pytest.mark.asyncio
async def test_get_scripts_returns_only_verified(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    await storage.save_entries(
        'example.com',
        'sig',
        {
            'good': _entry('good_script', verified=True),
            'bad': _entry('bad_script', verified=False),
        },
    )

    scripts = await storage.get_scripts('example.com', 'sig')
    assert 'good' in scripts
    assert scripts['good'] == 'good_script'
    assert 'bad' not in scripts


@pytest.mark.asyncio
async def test_get_scripts_returns_empty_for_cache_miss(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    scripts = await storage.get_scripts('nope.com', 'sig')
    assert scripts == {}


@pytest.mark.asyncio
async def test_save_overwrites_same_field(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    await storage.save_entries('example.com', 'sig', {'field': _entry('old')})
    await storage.save_entries('example.com', 'sig', {'field': _entry('new')})

    scripts = await storage.get_scripts('example.com', 'sig')
    assert scripts['field'] == 'new'
