"""Tests for the libSQL cache metrics store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

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
    selector_dir = tmp_path / '.yosoi' / 'selectors'
    selector_dir.mkdir(parents=True)
    mocker.patch('yosoi.storage.cache_metrics_libsql.init_yosoi', return_value=selector_dir)

    store = LibSQLCacheMetricsStore()

    assert store.db_path == tmp_path / '.yosoi' / 'metrics.sqlite3'


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
    assert summary.event_counts == {'run': 2, 'write': 3}
    assert {(row.field_name, row.route_signature) for row in summary.field_metrics} == {
        ('author', '/l1/news/article/'),
        ('headline', '/l1/news/article/'),
        ('headline', '/l1/news/profile/'),
    }


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
    assert summary.run_count == 2
    assert summary.url_count == 1


async def test_backfill_existing_imports_selector_files_once(tmp_path, mocker) -> None:
    selector_dir = tmp_path / '.yosoi' / 'selectors'
    selector_dir.mkdir(parents=True)
    mocker.patch('yosoi.storage.cache_metrics_libsql.init_yosoi', return_value=selector_dir)
    fp = 'contract-fp'
    payload = {
        'url': 'https://example.com/l1/news/article/?x=1',
        'domain': 'example.com',
        'contract_sig': fp,
        'snapshots': {'headline': _snapshot('h1').model_dump(mode='json')},
    }
    (selector_dir / f'selectors_example_com_{fp}.json').write_text(json.dumps(payload))

    async with LibSQLCacheMetricsStore(tmp_path / 'metrics.sqlite3') as store:
        first = await store.backfill_existing(contract_fingerprint=fp)
        second = await store.backfill_existing(contract_fingerprint=fp)
        summary = await store.summarize_contract(fp)

    assert first.scanned_files == 1
    assert first.imported_files == 1
    assert first.imported_fields == 1
    assert second.scanned_files == 1
    assert second.imported_files == 0
    assert second.skipped_files == 1
    assert summary.event_counts == {'backfill': 1}
