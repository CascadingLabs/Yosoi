"""SQLite-backed crawl stress run history."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from yosoi.storage.sqlite_store import YosoiSQLiteStore

_RUN_TABLE = 'crawl_runs'
_PAGE_TABLE = 'crawl_pages'
_EVENT_TABLE = 'crawl_frontier_events'


def crawl_run_status(summary: Any, *, failure_threshold: int = 0) -> str:
    """Return the coarse status for a completed crawl summary."""
    failures = int(getattr(summary, 'failures', 0) or 0)
    attempted = int(getattr(summary, 'attempted_urls', 0) or 0)
    if attempted <= 0:
        return 'error'
    if failures > failure_threshold:
        return 'partial'
    return 'ok'


def compact_crawl_summary(
    summary: Any,
    *,
    run_id: str | None = None,
    failure_threshold: int = 0,
    include_html: bool = False,
    include_fingerprints: bool = False,
) -> dict[str, Any]:
    """Return a stress-friendly summary without full page payloads by default."""
    result_rows: list[dict[str, Any]] = []
    for index, result in enumerate(getattr(summary, 'results', []), start=1):
        job = result.job
        row: dict[str, Any] = {
            'index': index,
            'url': job.url,
            'depth': job.depth,
            'source_url': job.source_url,
            'status': result.status,
            'links': len(result.discovered_links),
            'html_chars': result.html_chars,
            'fetch_time': round(float(result.fetch_time), 6),
            'status_code': result.status_code,
            'content_type': result.content_type,
            'error': result.error,
        }
        if include_html:
            row['html'] = result.html
        if include_fingerprints:
            row['fingerprint'] = _json_safe(result.fingerprint)
            row['observation'] = _json_safe(result.observation)
        result_rows.append(row)

    compact: dict[str, Any] = {
        'run_id': run_id,
        'status': crawl_run_status(summary, failure_threshold=failure_threshold),
        'pages_fetched': getattr(summary, 'pages_fetched', 0),
        'attempted_urls': getattr(summary, 'attempted_urls', 0),
        'unique_urls_seen': getattr(summary, 'unique_urls_seen', 0),
        'duplicates_blocked': getattr(summary, 'duplicates_blocked', 0),
        'policy_blocked': getattr(summary, 'policy_blocked', 0),
        'failures': getattr(summary, 'failures', 0),
        'batches': getattr(summary, 'batches', 0),
        'idle_worker_slots': getattr(summary, 'idle_worker_slots', 0),
        'worker_slots_total': getattr(summary, 'worker_slots_total', 0),
        'worker_slots_used': getattr(summary, 'worker_slots_used', 0),
        'average_batch_fill': round(float(getattr(summary, 'average_batch_fill', 0.0) or 0.0), 6),
        'dispatch_slot_idle_ratio': round(float(getattr(summary, 'dispatch_slot_idle_ratio', 0.0) or 0.0), 6),
        'wall_time': round(float(getattr(summary, 'wall_time', 0.0) or 0.0), 6),
        'path_prefix_counts': summary.path_prefix_counts(depth=2) if hasattr(summary, 'path_prefix_counts') else {},
        'content_type_counts': summary.content_type_counts() if hasattr(summary, 'content_type_counts') else {},
        'representative_urls': summary.representative_urls(limit=20) if hasattr(summary, 'representative_urls') else [],
        'scrape_target_urls': summary.scrape_target_urls(limit=20) if hasattr(summary, 'scrape_target_urls') else [],
        'outcome_lanes': getattr(summary, 'outcome_lanes', {}),
        'results': result_rows,
    }
    if run_id is None:
        compact.pop('run_id')
    return compact


class CrawlRunsStore(YosoiSQLiteStore):
    """Persist compact crawl run metrics in `.yosoi/yosoi.sqlite3`."""

    async def save_summary(
        self,
        *,
        run_id: str,
        summary: Any,
        seeds: Sequence[str],
        failure_threshold: int = 0,
        stress: bool = False,
    ) -> None:
        """Persist one crawl summary plus per-page/event rows."""
        await self._ensure_migrated()
        client = await self._connect()
        occurred_at = datetime.now(timezone.utc).isoformat()
        status = crawl_run_status(summary, failure_threshold=failure_threshold)

        tx = client.transaction()
        try:
            await tx.execute(
                f"""
                INSERT INTO {_RUN_TABLE} (
                    run_id, status, stress, seeds, seed_count, pages_fetched, attempted_urls,
                    unique_urls_seen, duplicates_blocked, policy_blocked, failures, batches,
                    idle_worker_slots, worker_slots_total, worker_slots_used, average_batch_fill,
                    dispatch_slot_idle_ratio, wall_time, occurred_at
                )
                VALUES (
                    :run_id, :status, :stress, json(:seeds), :seed_count, :pages_fetched, :attempted_urls,
                    :unique_urls_seen, :duplicates_blocked, :policy_blocked, :failures, :batches,
                    :idle_worker_slots, :worker_slots_total, :worker_slots_used, :average_batch_fill,
                    :dispatch_slot_idle_ratio, :wall_time, :occurred_at
                )
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    stress = excluded.stress,
                    seeds = excluded.seeds,
                    seed_count = excluded.seed_count,
                    pages_fetched = excluded.pages_fetched,
                    attempted_urls = excluded.attempted_urls,
                    unique_urls_seen = excluded.unique_urls_seen,
                    duplicates_blocked = excluded.duplicates_blocked,
                    policy_blocked = excluded.policy_blocked,
                    failures = excluded.failures,
                    batches = excluded.batches,
                    idle_worker_slots = excluded.idle_worker_slots,
                    worker_slots_total = excluded.worker_slots_total,
                    worker_slots_used = excluded.worker_slots_used,
                    average_batch_fill = excluded.average_batch_fill,
                    dispatch_slot_idle_ratio = excluded.dispatch_slot_idle_ratio,
                    wall_time = excluded.wall_time,
                    occurred_at = excluded.occurred_at
                """,
                {
                    'run_id': run_id,
                    'status': status,
                    'stress': int(stress),
                    'seeds': json.dumps(list(seeds)),
                    'seed_count': len(seeds),
                    'pages_fetched': int(getattr(summary, 'pages_fetched', 0) or 0),
                    'attempted_urls': int(getattr(summary, 'attempted_urls', 0) or 0),
                    'unique_urls_seen': int(getattr(summary, 'unique_urls_seen', 0) or 0),
                    'duplicates_blocked': int(getattr(summary, 'duplicates_blocked', 0) or 0),
                    'policy_blocked': int(getattr(summary, 'policy_blocked', 0) or 0),
                    'failures': int(getattr(summary, 'failures', 0) or 0),
                    'batches': int(getattr(summary, 'batches', 0) or 0),
                    'idle_worker_slots': int(getattr(summary, 'idle_worker_slots', 0) or 0),
                    'worker_slots_total': int(getattr(summary, 'worker_slots_total', 0) or 0),
                    'worker_slots_used': int(getattr(summary, 'worker_slots_used', 0) or 0),
                    'average_batch_fill': float(getattr(summary, 'average_batch_fill', 0.0) or 0.0),
                    'dispatch_slot_idle_ratio': float(getattr(summary, 'dispatch_slot_idle_ratio', 0.0) or 0.0),
                    'wall_time': float(getattr(summary, 'wall_time', 0.0) or 0.0),
                    'occurred_at': occurred_at,
                },
            )
            await tx.execute(f'DELETE FROM {_PAGE_TABLE} WHERE run_id = :run_id', {'run_id': run_id})
            await tx.execute(f'DELETE FROM {_EVENT_TABLE} WHERE run_id = :run_id', {'run_id': run_id})
            for index, result in enumerate(getattr(summary, 'results', []), start=1):
                await tx.execute(
                    f"""
                    INSERT INTO {_PAGE_TABLE} (
                        run_id, ordinal, url, depth, source_url, status, status_code, html_chars, fetch_time,
                        error, content_type, discovered_links_count
                    )
                    VALUES (
                        :run_id, :ordinal, :url, :depth, :source_url, :status, :status_code, :html_chars, :fetch_time,
                        :error, :content_type, :discovered_links_count
                    )
                    """,
                    _page_params(run_id, index, result),
                )
                await tx.execute(
                    f"""
                    INSERT INTO {_EVENT_TABLE} (
                        run_id, ordinal, event_type, url, depth, source_url, status, detail
                    )
                    VALUES (
                        :run_id, :ordinal, 'page_result', :url, :depth, :source_url, :status, json(:detail)
                    )
                    """,
                    _event_params(
                        run_id,
                        index,
                        result.job.url,
                        result.job.depth,
                        result.job.source_url,
                        result.status,
                        {
                            'html_chars': result.html_chars,
                            'fetch_time': result.fetch_time,
                            'status_code': result.status_code,
                            'error': result.error,
                            'content_type': result.content_type,
                            'links': len(result.discovered_links),
                        },
                    ),
                )
                link_offset = index * 10_000
                for link_index, link in enumerate(result.discovered_links, start=1):
                    await tx.execute(
                        f"""
                        INSERT INTO {_EVENT_TABLE} (
                            run_id, ordinal, event_type, url, depth, source_url, status, detail
                        )
                        VALUES (
                            :run_id, :ordinal, 'link_discovered', :url, :depth, :source_url, NULL, json(:detail)
                        )
                        """,
                        _event_params(
                            run_id,
                            link_offset + link_index,
                            link.url,
                            result.job.depth + 1,
                            result.job.url,
                            None,
                            {
                                'text': link.text,
                                'score': link.score,
                                'is_pagination': link.is_pagination,
                            },
                        ),
                    )
            await tx.commit()
        except Exception:
            await tx.rollback()
            raise

    async def load_run(self, run_id: str) -> dict[str, Any] | None:
        """Load one persisted crawl run row for tests and diagnostics."""
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(f'SELECT * FROM {_RUN_TABLE} WHERE run_id = :run_id', {'run_id': run_id})
        if not result.rows:
            return None
        return dict(zip(result.columns, result.rows[0], strict=False))

    async def _ensure_migrated(self) -> None:
        if self._migrated:
            await self._connect()
            return
        client = await self._connect()
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_RUN_TABLE} (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                stress INTEGER NOT NULL DEFAULT 0,
                seeds JSON NOT NULL,
                seed_count INTEGER NOT NULL,
                pages_fetched INTEGER NOT NULL,
                attempted_urls INTEGER NOT NULL,
                unique_urls_seen INTEGER NOT NULL,
                duplicates_blocked INTEGER NOT NULL,
                policy_blocked INTEGER NOT NULL,
                failures INTEGER NOT NULL,
                batches INTEGER NOT NULL,
                idle_worker_slots INTEGER NOT NULL,
                worker_slots_total INTEGER NOT NULL,
                worker_slots_used INTEGER NOT NULL,
                average_batch_fill REAL NOT NULL,
                dispatch_slot_idle_ratio REAL NOT NULL,
                wall_time REAL NOT NULL,
                occurred_at TEXT NOT NULL
            )
            """
        )
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_PAGE_TABLE} (
                run_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                url TEXT NOT NULL,
                depth INTEGER NOT NULL,
                source_url TEXT,
                status TEXT NOT NULL,
                status_code INTEGER,
                html_chars INTEGER NOT NULL,
                fetch_time REAL NOT NULL,
                error TEXT,
                content_type TEXT,
                discovered_links_count INTEGER NOT NULL,
                PRIMARY KEY(run_id, ordinal),
                FOREIGN KEY(run_id) REFERENCES {_RUN_TABLE}(run_id)
            )
            """
        )
        await client.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_crawl_pages_status
            ON {_PAGE_TABLE}(run_id, status, depth)
            """
        )
        await _add_column_if_missing(client, _PAGE_TABLE, 'status_code', 'INTEGER')
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_EVENT_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                url TEXT NOT NULL,
                depth INTEGER NOT NULL,
                source_url TEXT,
                status TEXT,
                detail JSON NOT NULL,
                FOREIGN KEY(run_id) REFERENCES {_RUN_TABLE}(run_id)
            )
            """
        )
        await client.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_crawl_events_run
            ON {_EVENT_TABLE}(run_id, event_type, ordinal)
            """
        )
        self._migrated = True


def _page_params(run_id: str, ordinal: int, result: Any) -> dict[str, Any]:
    return {
        'run_id': run_id,
        'ordinal': ordinal,
        'url': result.job.url,
        'depth': result.job.depth,
        'source_url': result.job.source_url,
        'status': result.status,
        'status_code': result.status_code,
        'html_chars': int(result.html_chars or 0),
        'fetch_time': float(result.fetch_time or 0.0),
        'error': result.error,
        'content_type': result.content_type,
        'discovered_links_count': len(result.discovered_links),
    }


def _event_params(
    run_id: str,
    ordinal: int,
    url: str,
    depth: int,
    source_url: str | None,
    status: str | None,
    detail: dict[str, Any],
) -> dict[str, Any]:
    return {
        'run_id': run_id,
        'ordinal': ordinal,
        'url': url,
        'depth': depth,
        'source_url': source_url,
        'status': status,
        'detail': json.dumps(detail, sort_keys=True),
    }


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, 'model_dump'):
        return value.model_dump()
    if hasattr(value, '__dataclass_fields__'):
        return asdict(value)
    return value


async def _add_column_if_missing(client: Any, table: str, column: str, definition: str) -> None:
    result = await client.execute(f'PRAGMA table_info({table})')
    existing = {str(row[1]) for row in result.rows}
    if column not in existing:
        await client.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


__all__ = ['CrawlRunsStore', 'compact_crawl_summary', 'crawl_run_status']
