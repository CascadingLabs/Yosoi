"""Tests for the SQLite cache metrics store."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot
from yosoi.storage.cache_metrics_sqlite import SQLiteCacheMetricsStore, route_signature_for_url


def _snapshot(selector: str) -> SelectorSnapshot:
    return SelectorSnapshot(primary=selector, discovered_at=datetime.now(timezone.utc))


def test_route_signature_uses_path_without_query() -> None:
    assert route_signature_for_url('https://example.com/l1/news/article/?postData=abc') == '/l1/news/article/'
    assert route_signature_for_url('https://example.com') == '/'


def test_default_db_path_is_metrics_file_under_yosoi_dir(tmp_path, mocker) -> None:
    selector_dir = tmp_path / '.yosoi' / 'selectors'
    selector_dir.mkdir(parents=True)
    mocker.patch('yosoi.storage.cache_metrics_sqlite.init_yosoi', return_value=selector_dir)

    store = SQLiteCacheMetricsStore()

    assert store.db_path == tmp_path / '.yosoi' / 'metrics.sqlite3'


async def test_upsert_snapshots_is_field_addressable_by_contract_domain_and_route(tmp_path) -> None:
    store = SQLiteCacheMetricsStore(tmp_path / 'metrics.sqlite3')
    fp = 'contract-fp'

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
    assert summary.routes == ['/l1/news/article/', '/l1/news/profile/']
    assert summary.fields == ['author', 'headline']
    assert {(row.field_name, row.route_signature) for row in summary.field_metrics} == {
        ('author', '/l1/news/article/'),
        ('headline', '/l1/news/article/'),
        ('headline', '/l1/news/profile/'),
    }


async def test_record_verdict_updates_field_health_and_records_event(tmp_path) -> None:
    db_path = tmp_path / 'metrics.sqlite3'
    store = SQLiteCacheMetricsStore(db_path)
    fp = 'contract-fp'
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

    with sqlite3.connect(db_path) as conn:
        events = conn.execute('SELECT event_type FROM cache_events ORDER BY id').fetchall()
    assert [event[0] for event in events] == ['write', 'fail']
