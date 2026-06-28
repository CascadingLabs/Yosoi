"""Tests for SQLite-backed A3Node storage."""

from __future__ import annotations

import asyncio
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

    async def test_scoped_recipes_same_host_different_paths_do_not_share(self, real_storage):
        from yosoi.storage.a3node import A3NodeScope

        news = A3NodeScope.for_url(
            'https://example.com/news?page=1',
            domain='example.com',
            intent='contract:news',
            browser_fingerprint='headless',
        )
        products = A3NodeScope.for_url(
            'https://example.com/products?page=1',
            domain='example.com',
            intent='contract:news',
            browser_fingerprint='headless',
        )

        await real_storage.save(news, _acts('load_more'))
        await real_storage.save(products, _acts('cookie'))

        news_node = await real_storage.load(news)
        product_node = await real_storage.load(products)
        assert news_node is not None
        assert product_node is not None
        assert news_node.acts[0].kind == 'load_more'
        assert product_node.acts[0].kind == 'cookie'
        assert set(await real_storage.list_scope_keys()) == {news.scope_key, products.scope_key}

    async def test_scope_fingerprint_uses_query_shape_not_query_values(self, real_storage):
        from yosoi.storage.a3node import A3NodeScope

        first = A3NodeScope.for_url('https://example.com/search?q=alpha&page=1', domain='example.com')
        second = A3NodeScope.for_url('https://example.com/search?q=beta&page=2', domain='example.com')
        different_shape = A3NodeScope.for_url('https://example.com/search?q=alpha', domain='example.com')

        assert first.scope_key == second.scope_key
        assert first.scope_key != different_shape.scope_key

    async def test_scope_fingerprint_splits_contract_intent_and_browser_profile(self, real_storage):
        from yosoi.storage.a3node import A3NodeScope

        base = A3NodeScope.for_url(
            'https://example.com/search?q=alpha', domain='example.com', intent='sig:a', browser_fingerprint='headless'
        )
        other_contract = A3NodeScope.for_url(
            'https://example.com/search?q=alpha', domain='example.com', intent='sig:b', browser_fingerprint='headless'
        )
        other_profile = A3NodeScope.for_url(
            'https://example.com/search?q=alpha', domain='example.com', intent='sig:a', browser_fingerprint='headful'
        )

        assert len({base.scope_key, other_contract.scope_key, other_profile.scope_key}) == 3

    async def test_concurrent_unrelated_scoped_saves_do_not_overwrite(self, real_storage):
        from yosoi.storage.a3node import A3NodeScope

        left = A3NodeScope.for_url('https://example.com/a', domain='example.com', intent='sig:a')
        right = A3NodeScope.for_url('https://example.com/b', domain='example.com', intent='sig:a')

        await asyncio.gather(real_storage.save(left, _acts('load_more')), real_storage.save(right, _acts('cookie')))

        left_node = await real_storage.load(left)
        right_node = await real_storage.load(right)
        assert left_node is not None
        assert right_node is not None
        assert left_node.acts[0].kind == 'load_more'
        assert right_node.acts[0].kind == 'cookie'

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

    async def test_old_a3node_table_migrates_to_inert_legacy_scope(self, tmp_path):
        from yosoi.storage.a3node import A3NodeStorage

        db_path = tmp_path / 'yosoi.sqlite3'
        with sqlite3.connect(db_path) as conn:
            conn.execute('CREATE TABLE a3nodes (domain TEXT PRIMARY KEY, acts TEXT)')
            conn.execute('INSERT INTO a3nodes VALUES (?, ?)', ('legacy.com', '[]'))

        storage = A3NodeStorage(database_url=db_path)
        assert await storage.list_domains() == ['legacy.com']
        node = await storage.load('legacy.com')
        assert node is not None
        assert node.scope_key == 'legacy.com'
        assert node.page_profile == 'legacy-domain'

        with sqlite3.connect(db_path) as conn:
            columns = {row[1]: row[2].upper() for row in conn.execute('PRAGMA table_info(a3nodes)')}
        assert columns['scope_key'] == 'TEXT'
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

    async def test_fragments_mint_from_targeted_acts_and_reuse_across_domains(self, real_storage):
        from yosoi.models.selectors import SelectorEntry
        from yosoi.storage.a3node import A3NodeScope, ActRecord

        target = SelectorEntry(type='role', value='button', name='Accept additional cookies', nth=0)
        first = A3NodeScope.for_url('https://a.example/page', domain='a.example')
        second = A3NodeScope.for_url('https://b.example/other', domain='b.example')

        minted = await real_storage.save_fragments_from_acts(first, [ActRecord('cookie', 1, target=target)])
        refreshed = await real_storage.save_fragments_from_acts(second, [ActRecord('cookie', 1, target=target)])
        fragments = await real_storage.load_fragments(kinds={'cookie'})

        assert minted[0].fragment_key == refreshed[0].fragment_key
        assert len(fragments) == 1
        assert fragments[0].target == target
        assert fragments[0].evidence_count == 2
        assert fragments[0].to_act() == ActRecord('cookie', 1, target=target)

    async def test_record_fragment_replay_increments_count(self, real_storage):
        from yosoi.models.selectors import SelectorEntry
        from yosoi.storage.a3node import A3NodeScope, ActRecord

        target = SelectorEntry(type='role', value='button', name='Accept additional cookies', nth=0)
        scope = A3NodeScope.for_url('https://a.example/page', domain='a.example')
        minted = await real_storage.save_fragments_from_acts(scope, [ActRecord('cookie', 1, target=target)])
        await real_storage.record_fragment_replay(minted[0].fragment_key)

        fragments = await real_storage.load_fragments(kinds={'cookie'})
        assert fragments[0].replay_count == 1
        assert fragments[0].last_replayed_at is not None

    async def test_non_obstacle_acts_do_not_mint_fragments(self, real_storage):
        from yosoi.models.selectors import SelectorEntry
        from yosoi.storage.a3node import A3NodeScope, ActRecord

        target = SelectorEntry(type='role', value='button', name='Load more', nth=0)
        scope = A3NodeScope.for_url('https://a.example/page', domain='a.example')

        assert await real_storage.save_fragments_from_acts(scope, [ActRecord('load_more', 1, target=target)]) == []
        assert await real_storage.load_fragments(kinds={'load_more'}) == []

    async def test_fragment_kind_filter_is_applied_before_limit(self, real_storage):
        from yosoi.models.selectors import SelectorEntry
        from yosoi.storage.a3node import A3NodeScope, ActRecord

        target = SelectorEntry(type='role', value='button', name='Accept additional cookies', nth=0)
        scope = A3NodeScope.for_url('https://a.example/page', domain='a.example')
        await real_storage.save_fragments_from_acts(scope, [ActRecord('cookie', 1, target=target)])
        with sqlite3.connect(real_storage.db_path) as conn:
            conn.execute(
                """
                INSERT INTO a3fragments (
                    fragment_key, kind, target_signature, target, source_domain,
                    evidence_count, replay_count, created_at, updated_at
                ) VALUES (?, ?, ?, json(?), ?, ?, ?, ?, ?)
                """,
                (
                    'disallowed-load-more',
                    'load_more',
                    'disallowed-load-more',
                    '{"type":"role","value":"button","name":"Load more","nth":0}',
                    'x.example',
                    99,
                    99,
                    '2026-01-01',
                    '2026-01-01',
                ),
            )

        fragments = await real_storage.load_fragments(limit=1)
        assert len(fragments) == 1
        assert fragments[0].kind == 'cookie'

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
