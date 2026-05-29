"""Tests for snapshot-based persistence: save/load snapshots, record_verdict."""

from datetime import datetime, timezone

import pytest

from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot, SnapshotStatus
from yosoi.storage.persistence import SelectorStorage


@pytest.fixture
def storage(tmp_path, mocker):
    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir()
    content_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    return SelectorStorage()


class TestSaveLoadSnapshots:
    async def test_round_trip(self, storage):
        now = datetime.now(timezone.utc)
        snapshots = {
            'title': SelectorSnapshot(
                primary={'type': 'css', 'value': 'h1.title'},
                fallback={'type': 'css', 'value': 'h1'},
                discovered_at=now,
            ),
            'price': SelectorSnapshot(
                primary={'type': 'css', 'value': '.price'},
                discovered_at=now,
                failure_count=1,
            ),
        }

        await storage.save_snapshots('https://example.com/item', snapshots)
        loaded = await storage.load_snapshots('example.com')

        assert loaded is not None
        assert 'title' in loaded
        assert 'price' in loaded
        assert loaded['title'].primary == {'type': 'css', 'value': 'h1.title'}
        assert loaded['price'].failure_count == 1

    async def test_load_nonexistent_returns_none(self, storage):
        assert await storage.load_snapshots('nonexistent.com') is None

    async def test_legacy_na_primary_loads_as_absent_snapshot(self, storage):
        now = datetime.now(timezone.utc)
        snapshots = {
            'author': SelectorSnapshot(
                primary='NA',
                discovered_at=now,
            ),
        }

        await storage.save_snapshots('https://example.com/item', snapshots)
        loaded = await storage.load_snapshots('example.com')

        assert loaded is not None
        assert loaded['author'].status == SnapshotStatus.ABSENT
        assert loaded['author'].primary is None
        assert await storage.load_selectors('example.com') == {}


class TestSaveLoadSelectors:
    async def test_save_selectors_writes_snapshot_format(self, storage):
        selectors = {
            'title': {'primary': 'h1.title', 'fallback': 'h1', 'tertiary': None},
        }
        await storage.save_selectors('https://example.com/article', selectors)

        # Should be readable as snapshots
        snapshots = await storage.load_snapshots('example.com')
        assert snapshots is not None
        assert 'title' in snapshots
        assert snapshots['title'].primary == 'h1.title'

    async def test_save_selectors_migrates_legacy_absent_sentinel(self, storage):
        await storage.save_selectors('https://example.com/article', {'author': {'primary': 'NA'}})

        snapshots = await storage.load_snapshots('example.com')

        assert snapshots is not None
        assert snapshots['author'].status == SnapshotStatus.ABSENT
        assert snapshots['author'].primary is None

    async def test_load_selectors_strips_audit_metadata(self, storage):
        now = datetime.now(timezone.utc)
        snapshots = {
            'title': SelectorSnapshot(
                primary={'type': 'css', 'value': 'h1.title'},
                discovered_at=now,
            ),
        }
        await storage.save_snapshots('https://example.com/page', snapshots)

        loaded = await storage.load_selectors('example.com')
        assert loaded is not None
        assert 'title' in loaded
        assert loaded['title'] == {'primary': {'type': 'css', 'value': 'h1.title'}}
        assert 'discovered_at' not in loaded['title']

    async def test_load_selectors_omits_explicit_absent_snapshots(self, storage):
        now = datetime.now(timezone.utc)
        snapshots = {
            'title': SelectorSnapshot(primary='h1', discovered_at=now),
            'author': SelectorSnapshot(discovered_at=now, status=SnapshotStatus.ABSENT),
        }

        await storage.save_snapshots('https://example.com/page', snapshots)

        assert await storage.load_selectors('example.com') == {'title': {'primary': 'h1'}}

    async def test_load_selectors_nonexistent_returns_none(self, storage):
        assert await storage.load_selectors('nothing.com') is None


class TestRecordVerdict:
    async def test_fresh_resets_failure_count(self, storage):
        now = datetime.now(timezone.utc)
        snapshots = {
            'title': SelectorSnapshot(
                primary={'type': 'css', 'value': 'h1'},
                discovered_at=now,
                failure_count=3,
                last_failed_at=now,
            ),
        }
        await storage.save_snapshots('https://example.com', snapshots)

        await storage.record_verdict('example.com', 'title', CacheVerdict.FRESH)

        reloaded = await storage.load_snapshots('example.com')
        assert reloaded is not None
        assert reloaded['title'].failure_count == 0
        assert reloaded['title'].last_verified_at is not None

    async def test_stale_increments_failure_count(self, storage):
        now = datetime.now(timezone.utc)
        snapshots = {
            'price': SelectorSnapshot(
                primary={'type': 'css', 'value': '.price'},
                discovered_at=now,
                failure_count=1,
            ),
        }
        await storage.save_snapshots('https://shop.com', snapshots)

        await storage.record_verdict('shop.com', 'price', CacheVerdict.STALE)

        reloaded = await storage.load_snapshots('shop.com')
        assert reloaded is not None
        assert reloaded['price'].failure_count == 2
        assert reloaded['price'].last_failed_at is not None

    async def test_noop_for_missing_domain(self, storage):
        await storage.record_verdict('nonexistent.com', 'title', CacheVerdict.FRESH)

    async def test_noop_for_missing_field(self, storage):
        now = datetime.now(timezone.utc)
        snapshots = {'title': SelectorSnapshot(primary={'type': 'css', 'value': 'h1'}, discovered_at=now)}
        await storage.save_snapshots('https://example.com', snapshots)
        await storage.record_verdict('example.com', 'nonexistent', CacheVerdict.STALE)


class TestSaveSelectorsVerified:
    async def test_verified_stamps_last_verified_at(self, storage):
        selectors = {
            'title': {'primary': 'h1.title', 'fallback': 'h1', 'tertiary': None},
            'price': {'primary': '.price', 'fallback': None, 'tertiary': None},
        }
        await storage.save_selectors('https://example.com/item', selectors, verified=True)

        snapshots = await storage.load_snapshots('example.com')
        assert snapshots is not None
        for name in ('title', 'price'):
            snap = snapshots[name]
            assert snap.last_verified_at is not None
            assert snap.last_verified_at == snap.discovered_at

    async def test_unverified_leaves_last_verified_at_none(self, storage):
        selectors = {'title': {'primary': 'h1', 'fallback': None, 'tertiary': None}}
        await storage.save_selectors('https://example.com/page', selectors)

        snapshots = await storage.load_snapshots('example.com')
        assert snapshots is not None
        assert snapshots['title'].last_verified_at is None
