"""Tests for SQLite-backed crawl run history."""

from __future__ import annotations

import sqlite3

from yosoi.core.crawler.coordinator import CrawlJob, CrawlResult, CrawlRunSummary
from yosoi.core.crawler.links import CrawlLink
from yosoi.storage.crawl_runs import CrawlRunsStore, compact_crawl_summary, crawl_run_status


def _summary(*, failed: bool = False) -> CrawlRunSummary:
    status = 'failed' if failed else 'succeeded'
    result = CrawlResult(
        job=CrawlJob(url='https://example.com/', depth=0, source_url=None, batch_index=0),
        status=status,
        discovered_links=(CrawlLink(url='https://example.com/a', text='A', score=0.5),),
        html_chars=123,
        html='<html>large debug payload</html>',
        fetch_time=0.2,
        error='boom' if failed else None,
        content_type='text/html',
        status_code=500 if failed else 200,
    )
    summary = CrawlRunSummary(results=[result], failures=1 if failed else 0, pages_fetched=0 if failed else 1)
    summary.attempted_urls = 1
    summary.unique_urls_seen = 2
    summary.wall_time = 0.25
    return summary


def test_compact_crawl_summary_omits_html_and_fingerprint_by_default() -> None:
    compact = compact_crawl_summary(_summary(), run_id='run-1')

    assert compact['run_id'] == 'run-1'
    assert compact['status'] == 'ok'
    assert compact['results'][0]['url'] == 'https://example.com/'
    assert compact['results'][0]['status_code'] == 200
    assert 'html' not in compact['results'][0]
    assert 'fingerprint' not in compact['results'][0]


def test_crawl_run_status_reports_partial_when_failures_exceed_threshold() -> None:
    assert crawl_run_status(_summary(failed=True)) == 'partial'
    assert crawl_run_status(_summary(failed=True), failure_threshold=1) == 'ok'


async def test_crawl_runs_store_persists_run_pages_and_events(tmp_path) -> None:
    db_path = tmp_path / 'yosoi.sqlite3'
    async with CrawlRunsStore(database_url=db_path) as store:
        await store.save_summary(run_id='run-1', summary=_summary(), seeds=('https://example.com/',), stress=True)
        row = await store.load_run('run-1')

    assert row is not None
    assert row['status'] == 'ok'
    assert row['stress'] == 1

    with sqlite3.connect(db_path) as conn:
        page = conn.execute('SELECT url, status, status_code, discovered_links_count FROM crawl_pages').fetchone()
        events = conn.execute('SELECT event_type, count(*) FROM crawl_frontier_events GROUP BY event_type').fetchall()

    assert page == ('https://example.com/', 'succeeded', 200, 1)
    assert dict(events) == {'link_discovered': 1, 'page_result': 1}
