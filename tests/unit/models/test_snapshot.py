"""Tests for SelectorSnapshot, CacheVerdict, SnapshotMap, and helper functions."""

from datetime import datetime, timezone

from yosoi.models.snapshot import (
    CacheVerdict,
    SelectorSnapshot,
    SnapshotMap,
    selector_dict_to_snapshot,
    snapshot_to_selector_dict,
)


class TestCacheVerdict:
    def test_enum_values(self):
        assert CacheVerdict.FRESH == 'fresh'
        assert CacheVerdict.STALE == 'stale'
        assert CacheVerdict.DEGRADED == 'degraded'

    def test_enum_from_string(self):
        assert CacheVerdict('fresh') is CacheVerdict.FRESH
        assert CacheVerdict('stale') is CacheVerdict.STALE


class TestSelectorSnapshot:
    def test_minimal_snapshot(self):
        snap = SelectorSnapshot(discovered_at=datetime.now(timezone.utc))
        assert snap.primary is None
        assert snap.failure_count == 0
        assert snap.source == 'discovered'

    def test_full_snapshot(self):
        now = datetime.now(timezone.utc)
        snap = SelectorSnapshot(
            primary={'type': 'css', 'value': 'h1.title'},
            fallback={'type': 'css', 'value': 'h1'},
            tertiary=None,
            discovered_at=now,
            last_verified_at=now,
            failure_count=0,
            source='pinned',
            parent_root='root',
        )
        assert snap.primary == {'type': 'css', 'value': 'h1.title'}
        assert snap.source == 'pinned'
        assert snap.parent_root == 'root'

    def test_serialization_round_trip(self):
        now = datetime.now(timezone.utc)
        snap = SelectorSnapshot(
            primary={'type': 'css', 'value': 'h1.title'},
            fallback={'type': 'xpath', 'value': '//h1'},
            discovered_at=now,
            last_verified_at=now,
            failure_count=2,
            source='override',
        )
        data = snap.model_dump(mode='json')
        restored = SelectorSnapshot.model_validate(data)
        assert restored.primary == snap.primary
        assert restored.fallback == snap.fallback
        assert restored.failure_count == 2
        assert restored.source == 'override'
        assert restored.discovered_at == snap.discovered_at


class TestSnapshotMap:
    def test_empty_snapshot_map(self):
        sm = SnapshotMap(url='https://example.com', domain='example.com')
        assert sm.snapshots == {}

    def test_snapshot_map_round_trip(self):
        now = datetime.now(timezone.utc)
        snap = SelectorSnapshot(
            primary={'type': 'css', 'value': '.price'},
            discovered_at=now,
        )
        sm = SnapshotMap(
            url='https://shop.com/item',
            domain='shop.com',
            snapshots={'price': snap},
        )
        data = sm.model_dump(mode='json')
        restored = SnapshotMap.model_validate(data)
        assert 'price' in restored.snapshots
        assert restored.snapshots['price'].primary == {'type': 'css', 'value': '.price'}


class TestSnapshotToSelectorDict:
    def test_extracts_all_levels(self):
        snap = SelectorSnapshot(
            primary={'type': 'css', 'value': 'h1.title'},
            fallback={'type': 'css', 'value': 'h1'},
            tertiary={'type': 'xpath', 'value': '//h1'},
            discovered_at=datetime.now(timezone.utc),
        )
        d = snapshot_to_selector_dict(snap)
        assert d == {
            'primary': {'type': 'css', 'value': 'h1.title'},
            'fallback': {'type': 'css', 'value': 'h1'},
            'tertiary': {'type': 'xpath', 'value': '//h1'},
        }

    def test_omits_none_levels(self):
        snap = SelectorSnapshot(
            primary={'type': 'css', 'value': '.price'},
            discovered_at=datetime.now(timezone.utc),
        )
        d = snapshot_to_selector_dict(snap)
        assert d == {'primary': {'type': 'css', 'value': '.price'}}
        assert 'fallback' not in d
        assert 'tertiary' not in d


class TestSelectorDictToSnapshot:
    def test_basic_migration(self):
        field_data = {
            'primary': 'h1.title',
            'fallback': 'h1',
            'tertiary': None,
        }
        snap = selector_dict_to_snapshot(field_data)
        assert snap.primary == 'h1.title'
        assert snap.fallback == 'h1'
        assert snap.tertiary is None
        assert snap.source == 'discovered'
        assert snap.discovered_at is not None

    def test_custom_timestamp_and_source(self):
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        snap = selector_dict_to_snapshot(
            {'primary': '.p'},
            discovered_at=ts,
            source='pinned',
            parent_root='root',
        )
        assert snap.discovered_at == ts
        assert snap.source == 'pinned'
        assert snap.parent_root == 'root'

    def test_defaults_timestamp_to_now(self):
        snap = selector_dict_to_snapshot({'primary': '.x'})
        assert snap.discovered_at is not None
        assert snap.discovered_at.tzinfo is not None

    def test_last_verified_at_defaults_to_none(self):
        snap = selector_dict_to_snapshot({'primary': '.x'})
        assert snap.last_verified_at is None

    def test_last_verified_at_passed_through(self):
        now = datetime.now(timezone.utc)
        snap = selector_dict_to_snapshot({'primary': '.x'}, last_verified_at=now)
        assert snap.last_verified_at == now
