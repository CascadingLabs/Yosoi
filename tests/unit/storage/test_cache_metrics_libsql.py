"""Tests for the libSQL cache metrics store."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from pydantic import Field

from yosoi.models.contract import Contract
from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot
from yosoi.storage.cache_metrics_libsql import (
    LibSQLCacheMetricsStore,
    route_signature_for_url,
    top_level_domain_for_domain,
)


def _snapshot(selector: str) -> SelectorSnapshot:
    return SelectorSnapshot(primary=selector, discovered_at=datetime.now(timezone.utc))


def test_route_signature_uses_path_without_query() -> None:
    assert route_signature_for_url('https://example.com/l1/news/article/?postData=abc') == '/l1/news/article/'
    assert route_signature_for_url('https://example.com') == '/'


def test_top_level_domain_bucket_is_precomputed() -> None:
    assert top_level_domain_for_domain('qscrape.dev') == 'qscrape.dev'
    assert top_level_domain_for_domain('news.qscrape.dev') == 'qscrape.dev'


def test_default_db_path_is_metrics_file_under_yosoi_dir(tmp_path, mocker) -> None:
    yosoi_dir = tmp_path / '.yosoi'
    yosoi_dir.mkdir(parents=True)
    mocker.patch('yosoi.storage.sqlite_store.init_yosoi', return_value=yosoi_dir)

    store = LibSQLCacheMetricsStore()

    assert store.db_path == tmp_path / '.yosoi' / 'yosoi.sqlite3'


async def test_upsert_snapshots_normalizes_contract_and_field_entities(tmp_path) -> None:
    class Article(Contract):
        """Article extraction contract."""

        headline: str = Field(description='Article headline')

    from yosoi.utils.signatures import contract_signature

    db_path = tmp_path / 'metrics.sqlite3'
    fp = contract_signature(Article)
    async with LibSQLCacheMetricsStore(db_path) as store:
        await store.upsert_snapshots(
            url='https://example.com/story',
            domain='example.com',
            snapshots={'headline': _snapshot('h1')},
            contract_fingerprint=fp,
            contract=Article,
        )

    with sqlite3.connect(db_path) as conn:
        contract_row = conn.execute(
            'SELECT name, docstring FROM contracts WHERE contract_fingerprint = ?', (fp,)
        ).fetchone()
        field_row = conn.execute('SELECT field_name, description FROM field_entities').fetchone()
        join_row = conn.execute('SELECT contract_fingerprint, field_path FROM contract_fields').fetchone()
        contract_columns = {row[1]: row[2].upper() for row in conn.execute('PRAGMA table_info(contracts)')}
        field_columns = {row[1]: row[2].upper() for row in conn.execute('PRAGMA table_info(field_entities)')}
        snapshot_columns = {row[1]: row[2].upper() for row in conn.execute('PRAGMA table_info(selector_snapshots)')}
        event_columns = {row[1]: row[2].upper() for row in conn.execute('PRAGMA table_info(cache_events)')}
        json_storage_types = conn.execute(
            """
            SELECT
                (SELECT typeof(spec) FROM contracts),
                (SELECT typeof(config) FROM field_entities),
                (SELECT typeof(selector) FROM selector_snapshots),
                (SELECT typeof(detail) FROM cache_events LIMIT 1)
            """
        ).fetchone()

    assert contract_row == ('Article', 'Article extraction contract.')
    assert field_row == ('headline', 'Article headline')
    assert join_row == (fp, 'headline')
    assert 'schema_version' not in contract_columns
    assert contract_columns['spec'] == 'JSON'
    assert field_columns['config'] == 'JSON'
    assert snapshot_columns['selector'] == 'JSON'
    assert 'domain' not in snapshot_columns
    assert 'top_level_domain' not in snapshot_columns
    assert 'domain' not in event_columns
    assert 'top_level_domain' not in event_columns
    assert event_columns['detail'] == 'JSON'
    assert json_storage_types == ('text', 'text', 'text', 'text')


async def test_old_text_json_schema_is_destructively_reset(tmp_path) -> None:
    db_path = tmp_path / 'metrics.sqlite3'
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            'CREATE TABLE contracts ('
            'contract_fingerprint TEXT PRIMARY KEY, schema_version INTEGER, spec_json TEXT, '
            'created_at TEXT, updated_at TEXT)'
        )

    async with LibSQLCacheMetricsStore(db_path) as store:
        await store.backfill_existing()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1]: row[2].upper() for row in conn.execute('PRAGMA table_info(contracts)')}

    assert 'schema_version' not in columns
    assert 'spec_json' not in columns
    assert columns['spec'] == 'JSON'


async def test_upsert_snapshots_is_field_addressable_by_contract_domain_and_route(tmp_path) -> None:
    fp = 'contract-fp'

    async with LibSQLCacheMetricsStore(tmp_path / 'metrics.sqlite3') as store:
        await store.upsert_snapshots(
            url='https://example.com/l1/news/article/?x=1',
            domain='example.com',
            snapshots={'headline': _snapshot('h1'), 'author': _snapshot('.author')},
            contract_fingerprint=fp,
        )
        await store.upsert_snapshots(
            url='https://example.com/l1/news/profile/?x=1',
            domain='example.com',
            snapshots={'headline': _snapshot('h2')},
            contract_fingerprint=fp,
        )

        summary = await store.summarize_contract(fp)

    assert summary.domains == ['example.com']
    assert summary.top_level_domains == ['example.com']
    assert summary.routes == ['/l1/news/article/', '/l1/news/profile/']
    assert summary.fields == ['author', 'headline']
    assert summary.run_count == 2
    assert summary.url_count == 2
    assert summary.urls == ['https://example.com/l1/news/article/?x=1', 'https://example.com/l1/news/profile/?x=1']
    assert summary.event_counts == {'run': 2, 'write': 3}
    assert {(row.field_name, row.route_signature) for row in summary.field_metrics} == {
        ('author', '/l1/news/article/'),
        ('headline', '/l1/news/article/'),
        ('headline', '/l1/news/profile/'),
    }


async def test_upsert_snapshots_replaces_selector_level_instead_of_duplicating_field(tmp_path) -> None:
    fp = 'contract-fp'
    db_path = tmp_path / 'metrics.sqlite3'

    async with LibSQLCacheMetricsStore(db_path) as store:
        await store.upsert_snapshots(
            url='https://example.com/l1/news/article/',
            domain='example.com',
            snapshots={'headline': _snapshot('h1')},
            contract_fingerprint=fp,
            selector_level='css',
        )
        await store.upsert_snapshots(
            url='https://example.com/l1/news/article/',
            domain='example.com',
            snapshots={'headline': _snapshot('h2')},
            contract_fingerprint=fp,
            selector_level='all',
        )

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            'SELECT field_path, selector_level, json_extract(selector, "$.primary") FROM selector_snapshots'
        ).fetchall()

    assert rows == [('headline', 'all', 'h2')]


async def test_record_verdict_updates_field_health_and_records_event(tmp_path) -> None:
    db_path = tmp_path / 'metrics.sqlite3'
    fp = 'contract-fp'
    async with LibSQLCacheMetricsStore(db_path) as store:
        await store.upsert_snapshots(
            url='https://example.com/l1/news/article/',
            domain='example.com',
            snapshots={'headline': _snapshot('h1')},
            contract_fingerprint=fp,
        )

        await store.record_verdict(
            domain='example.com',
            field_name='headline',
            verdict=CacheVerdict.STALE,
            contract_fingerprint=fp,
        )

        row = (await store.list_domain_fields('example.com', fp))[0]
        assert row.failure_count == 1
        assert row.last_failed_at is not None

        await store.record_cache_hit(
            url='https://example.com/l1/news/article/',
            domain='example.com',
            contract_fingerprint=fp,
            field_names=['headline'],
        )

    with sqlite3.connect(db_path) as conn:
        events = conn.execute('SELECT event_type FROM cache_events ORDER BY id').fetchall()
    assert [event[0] for event in events] == ['run', 'write', 'fail', 'run', 'hit']


async def test_summarize_domain_returns_domain_centered_counts(tmp_path) -> None:
    db_path = tmp_path / 'metrics.sqlite3'
    fp = 'contract-fp'
    async with LibSQLCacheMetricsStore(db_path) as store:
        await store.upsert_snapshots(
            url='https://news.example.com/article/1',
            domain='news.example.com',
            snapshots={'headline': _snapshot('h1')},
            contract_fingerprint=fp,
        )
        await store.record_cache_hit(
            url='https://news.example.com/article/1',
            domain='news.example.com',
            contract_fingerprint=fp,
            field_names=['headline'],
        )

        summary = await store.summarize_domain('news.example.com', fp)

    assert summary.domain == 'news.example.com'
    assert summary.top_level_domains == ['example.com']
    assert summary.contract_fingerprints == [fp]
    assert summary.routes == ['/article/1']
    assert summary.event_counts == {'hit': 1, 'run': 2, 'write': 1}
    assert summary.urls == ['https://news.example.com/article/1']
    assert summary.run_count == 2
    assert summary.url_count == 1


async def test_backfill_existing_is_noop_after_sqlite_becomes_source_of_truth(tmp_path) -> None:
    fp = 'contract-fp'

    async with LibSQLCacheMetricsStore(tmp_path / 'metrics.sqlite3') as store:
        result = await store.backfill_existing(contract_fingerprint=fp)
        summary = await store.summarize_contract(fp)

    assert result.scanned_files == 0
    assert result.imported_files == 0
    assert result.imported_fields == 0
    assert result.contract_fingerprints == [fp]
    assert summary.event_counts == {}
