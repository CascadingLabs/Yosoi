"""Tests for JsScriptStorage — save, load, merge, cache miss, description match."""

from __future__ import annotations

import pytest

from yosoi.storage.js_scripts import JsScriptEntry, JsScriptStorage


def _entry(
    script: str = '(() => true)()',
    verified: bool = True,
    description: str = 'test field',
) -> JsScriptEntry:
    return JsScriptEntry(
        script=script,
        description=description,
        discovered_at='2026-01-01T00:00:00+00:00',
        verified=verified,
        model='test',
        attempts=1,
    )


@pytest.mark.asyncio
async def test_load_returns_none_for_missing_domain(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    result = await storage.load('unknown.com')
    assert result is None


@pytest.mark.asyncio
async def test_default_dir_is_created_lazily(tmp_path, mocker):
    js_dir = tmp_path / 'js_scripts'
    mocker.patch('yosoi.storage.js_scripts.get_yosoi_storage_path', return_value=js_dir)
    mocker.patch('yosoi.storage.js_scripts.init_yosoi', return_value=js_dir)

    storage = JsScriptStorage()

    assert not js_dir.exists()
    assert await storage.load('example.com') is None
    assert not js_dir.exists()

    await storage.save_entries('example.com', {'signals': _entry()})
    assert js_dir.is_dir()


@pytest.mark.asyncio
async def test_save_and_load_round_trip(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    await storage.save_entries('example.com', {'signals': _entry('(() => ({x:1}))()')})

    record = await storage.load('example.com')
    assert record is not None
    assert 'signals' in record.fields
    assert record.fields['signals'].script == '(() => ({x:1}))()'
    assert record.fields['signals'].verified is True


@pytest.mark.asyncio
async def test_save_entries_merges_with_existing(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    await storage.save_entries('example.com', {'field_a': _entry('a')})
    await storage.save_entries('example.com', {'field_b': _entry('b')})

    record = await storage.load('example.com')
    assert record is not None
    assert 'field_a' in record.fields
    assert 'field_b' in record.fields


@pytest.mark.asyncio
async def test_get_scripts_returns_only_verified(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    await storage.save_entries(
        'example.com',
        {
            'good': _entry('good_script', verified=True),
            'bad': _entry('bad_script', verified=False),
        },
    )

    scripts = await storage.get_scripts('example.com')
    assert 'good' in scripts
    assert scripts['good'] == 'good_script'
    assert 'bad' not in scripts


@pytest.mark.asyncio
async def test_get_scripts_returns_empty_for_cache_miss(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    scripts = await storage.get_scripts('nope.com')
    assert scripts == {}


@pytest.mark.asyncio
async def test_save_overwrites_same_field(tmp_path):
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    await storage.save_entries('example.com', {'field': _entry('old')})
    await storage.save_entries('example.com', {'field': _entry('new')})

    scripts = await storage.get_scripts('example.com')
    assert scripts['field'] == 'new'


@pytest.mark.asyncio
async def test_get_scripts_matches_on_description(tmp_path):
    """A cached script is reused only when its stored description still matches."""
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    await storage.save_entries(
        'example.com',
        {'review_count': _entry('count_script', description='review count')},
    )

    # Same description ⇒ hit
    hit = await storage.get_scripts('example.com', {'review_count': 'review count'})
    assert hit == {'review_count': 'count_script'}

    # Changed description ⇒ stale ⇒ omitted (rediscover)
    stale = await storage.get_scripts('example.com', {'review_count': 'total ratings'})
    assert stale == {}

    # Field not requested ⇒ omitted
    unrequested = await storage.get_scripts('example.com', {'other': 'review count'})
    assert unrequested == {}


@pytest.mark.asyncio
async def test_get_scripts_survives_unrelated_field_changes(tmp_path):
    """One field's script survives a change to a *different* field's description."""
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    await storage.save_entries(
        'example.com',
        {
            'review_count': _entry('count_script', description='review count'),
            'signals': _entry('signals_script', description='tech signals'),
        },
    )

    # Only review_count requested with matching description; signals' churn is irrelevant
    scripts = await storage.get_scripts('example.com', {'review_count': 'review count'})
    assert scripts == {'review_count': 'count_script'}


async def test_load_returns_none_for_corrupt_json(tmp_path):
    """load() swallows JSON decode errors and returns None."""

    storage = JsScriptStorage(storage_dir=str(tmp_path))
    filepath = storage._filepath('corrupt.com')

    # Write a syntactically invalid JSON file
    with open(filepath, 'w') as f:
        f.write('{not valid json !!!}')

    result = await storage.load('corrupt.com')
    assert result is None


async def test_save_entries_logs_warning_on_ioerror(tmp_path, mocker):
    """save_entries() catches OSError from atomic write and logs a warning."""
    storage = JsScriptStorage(storage_dir=str(tmp_path))
    mocker.patch(
        'yosoi.storage.js_scripts.atomic_write_json_async',
        side_effect=OSError('disk full'),
    )

    # Must not raise — the OSError is caught and logged
    await storage.save_entries('example.com', {'field': _entry()})
