"""Tests for SQLite-backed A3Node storage."""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def real_storage(tmp_path):
    from yosoi.storage.a3node import A3NodeStorage

    return A3NodeStorage(database_url=tmp_path / 'yosoi.sqlite3')


def _acts(*kinds):
    from yosoi.storage.a3node import ActRecord

    return [ActRecord(kind=k, cycles=3) for k in kinds]


class TestRealA3NodeStorage:
    async def test_storage_dir_is_ignored_and_db_is_created_lazily(self, tmp_path):
        from yosoi.storage.a3node import A3NodeStorage

        storage = A3NodeStorage(storage_dir=tmp_path / 'a3nodes', database_url=tmp_path / 'yosoi.sqlite3')

        assert not (tmp_path / 'a3nodes').exists()
        assert await storage.load('example.com') is None
        assert not (tmp_path / 'a3nodes').exists()

        await storage.save('example.com', _acts('load_more'))
        assert storage.db_path == tmp_path / 'yosoi.sqlite3'
        assert storage.db_path.exists()
        assert not (tmp_path / 'a3nodes').exists()

    async def test_save_and_load_round_trip(self, real_storage):
        await real_storage.save('example.com', _acts('load_more'))
        node = await real_storage.load('example.com')
        assert node is not None
        assert node.domain == 'example.com'
        assert node.acts[0].kind == 'load_more'

    async def test_load_returns_none_for_unknown_domain(self, real_storage):
        assert await real_storage.load('unknown.com') is None

    async def test_sqlite_schema_uses_readable_json(self, real_storage):
        await real_storage.save('example.com', _acts('load_more'))

        with sqlite3.connect(real_storage.db_path) as conn:
            columns = {row[1]: row[2].upper() for row in conn.execute('PRAGMA table_info(a3nodes)')}
            row = conn.execute(
                'SELECT format, typeof(acts), acts FROM a3nodes WHERE domain = ?', ('example.com',)
            ).fetchone()

        assert columns['acts'] == 'JSON'
        assert row[0] == 2
        assert row[1] == 'text'
        assert 'load_more' in row[2]

    async def test_old_a3node_table_is_destructively_reset(self, tmp_path):
        from yosoi.storage.a3node import A3NodeStorage

        db_path = tmp_path / 'yosoi.sqlite3'
        with sqlite3.connect(db_path) as conn:
            conn.execute('CREATE TABLE a3nodes (domain TEXT PRIMARY KEY, acts TEXT)')
            conn.execute('INSERT INTO a3nodes VALUES (?, ?)', ('legacy.com', '[]'))

        storage = A3NodeStorage(database_url=db_path)
        assert await storage.list_domains() == []

        with sqlite3.connect(db_path) as conn:
            columns = {row[1]: row[2].upper() for row in conn.execute('PRAGMA table_info(a3nodes)')}
        assert columns['acts'] == 'JSON'
        assert columns['format'] == 'INTEGER'

    async def test_save_preserves_replay_count_when_acts_unchanged(self, real_storage):
        acts = _acts('load_more')
        await real_storage.save('example.com', acts)
        await real_storage.record_replay('example.com')
        await real_storage.record_replay('example.com')
        await real_storage.save('example.com', acts)
        node = await real_storage.load('example.com')
        assert node is not None
        assert node.replay_count == 2

    async def test_save_resets_replay_count_when_acts_change(self, real_storage):
        await real_storage.save('example.com', _acts('load_more'))
        await real_storage.record_replay('example.com')
        await real_storage.save('example.com', _acts('cookie'))
        node = await real_storage.load('example.com')
        assert node is not None
        assert node.replay_count == 0

    async def test_act_target_round_trips(self, real_storage):
        from yosoi.models.selectors import SelectorEntry
        from yosoi.storage.a3node import ActRecord

        target = SelectorEntry(type='role', value='button', name='Load more', nth=0)
        await real_storage.save('example.com', [ActRecord('load_more', 3, target=target)])
        node = await real_storage.load('example.com')
        assert node is not None
        assert node.acts[0].target == target

    async def test_adding_target_preserves_replay_count(self, real_storage):
        from yosoi.models.selectors import SelectorEntry
        from yosoi.storage.a3node import ActRecord

        await real_storage.save('example.com', [ActRecord('load_more', 3)])
        await real_storage.record_replay('example.com')
        await real_storage.record_replay('example.com')
        target = SelectorEntry(type='role', value='button', name='Load more', nth=0)
        await real_storage.save('example.com', [ActRecord('load_more', 3, target=target)])
        node = await real_storage.load('example.com')
        assert node is not None
        assert node.replay_count == 2

    async def test_record_replay_increments_count_and_timestamp(self, real_storage):
        await real_storage.save('example.com', _acts('load_more'))
        await real_storage.record_replay('example.com')
        node = await real_storage.load('example.com')
        assert node is not None
        assert node.replay_count == 1
        assert node.last_replayed_at is not None

    async def test_record_replay_noop_for_unknown_domain(self, real_storage):
        await real_storage.record_replay('nonexistent.com')
        assert await real_storage.load('nonexistent.com') is None

    async def test_delete_returns_true_and_removes_row(self, real_storage):
        await real_storage.save('example.com', _acts('load_more'))
        assert await real_storage.delete('example.com') is True
        assert await real_storage.load('example.com') is None

    async def test_delete_returns_false_for_nonexistent(self, real_storage):
        assert await real_storage.delete('nonexistent.com') is False

    async def test_list_domains_returns_saved_sorted(self, real_storage):
        await real_storage.save('beta.com', _acts('load_more'))
        await real_storage.save('alpha.com', _acts('load_more'))
        assert await real_storage.list_domains() == ['alpha.com', 'beta.com']

    async def test_load_all_returns_all_nodes(self, real_storage):
        await real_storage.save('a.com', _acts('load_more'))
        await real_storage.save('b.com', _acts('cookie'))
        result = await real_storage.load_all()
        assert set(result) == {'a.com', 'b.com'}

    async def test_load_all_empty_when_no_rows(self, real_storage):
        assert await real_storage.load_all() == {}

    async def test_load_raw_returns_none_for_missing(self, real_storage):
        assert await real_storage._load_raw('nonexistent.com') is None

    def test_a3node_is_empty_true(self):
        from yosoi.storage.a3node import A3Node

        node = A3Node(domain='x.com', acts=[], discovered_at='2024')
        assert node.is_empty is True

    def test_a3node_is_empty_false(self):
        from yosoi.storage.a3node import A3Node, ActRecord

        node = A3Node(domain='x.com', acts=[ActRecord('load_more', 3)], discovered_at='2024')
        assert node.is_empty is False

    def test_a3node_battle_tested_at_3(self):
        from yosoi.storage.a3node import A3Node

        node = A3Node(domain='x.com', acts=[], discovered_at='2024', replay_count=3)
        assert node.battle_tested is True

    def test_a3node_not_battle_tested_below_3(self):
        from yosoi.storage.a3node import A3Node

        node = A3Node(domain='x.com', acts=[], discovered_at='2024', replay_count=2)
        assert node.battle_tested is False
