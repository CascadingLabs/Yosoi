"""SQLite-backed tracker for LLM calls and URL counts per domain."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from yosoi.storage.sqlite_store import YosoiSQLiteStore
from yosoi.utils.files import get_tracking_path
from yosoi.utils.urls import extract_domain

_TRACKING_TABLE = 'tracking_stats'


class DomainStats(BaseModel):
    """Per-domain tracking statistics."""

    llm_calls: int = 0
    url_count: int = 0
    level_distribution: dict[str, int] = Field(default_factory=dict)
    total_elapsed: float = 0.0
    partial_rediscovery_count: int = 0


class LLMTracker(YosoiSQLiteStore):
    """Tracks LLM calls and URL counts per domain in `.yosoi/yosoi.sqlite3`."""

    def __init__(self, database_url: str | None = None, tracking_file: str | None = None):
        """Initialize the tracker.

        `tracking_file` is a deprecated compatibility shim. If it points at a
        legacy JSON file, that file is imported into a sibling SQLite database
        and removed.
        """
        resolved_url = database_url
        if resolved_url is None and tracking_file is not None:
            db_path = self._migrate_legacy_tracking_file(Path(tracking_file))
            resolved_url = str(db_path)
            self.tracking_file = str(db_path)
        else:
            self.tracking_file = str(database_url or get_tracking_path())
        super().__init__(database_url=resolved_url)
        self._lock: asyncio.Lock = asyncio.Lock()

    @staticmethod
    def _migrate_legacy_tracking_file(path: Path) -> Path:
        """Return the SQLite path for a deprecated JSON tracking file, importing if present."""
        db_path = path.with_suffix('.sqlite3') if path.suffix == '.json' else path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path == db_path:
            LLMTracker._ensure_sqlite_file(db_path)
            return db_path
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            LLMTracker._ensure_sqlite_file(db_path)
            return db_path
        if not isinstance(raw, dict):
            path.unlink(missing_ok=True)
            LLMTracker._ensure_sqlite_file(db_path)
            return db_path
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TRACKING_TABLE} (
                    domain TEXT PRIMARY KEY,
                    llm_calls INTEGER NOT NULL DEFAULT 0,
                    url_count INTEGER NOT NULL DEFAULT 0,
                    level_distribution TEXT NOT NULL DEFAULT '{{}}',
                    total_elapsed REAL NOT NULL DEFAULT 0,
                    partial_rediscovery_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for domain, entry in raw.items():
                if not isinstance(entry, dict):
                    continue
                dist = entry.get('level_distribution') if isinstance(entry.get('level_distribution'), dict) else {}
                db.execute(
                    f"""
                    INSERT OR REPLACE INTO {_TRACKING_TABLE} (
                        domain, llm_calls, url_count, level_distribution,
                        total_elapsed, partial_rediscovery_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        str(domain),
                        int(entry.get('llm_calls') or 0),
                        int(entry.get('url_count') or 0),
                        json.dumps(dist, separators=(',', ':')),
                        float(entry.get('total_elapsed') or 0.0),
                        int(entry.get('partial_rediscovery_count') or 0),
                    ),
                )
        path.unlink(missing_ok=True)
        return db_path

    @staticmethod
    def _ensure_sqlite_file(db_path: Path) -> None:
        """Create an empty tracking SQLite database."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TRACKING_TABLE} (
                    domain TEXT PRIMARY KEY,
                    llm_calls INTEGER NOT NULL DEFAULT 0,
                    url_count INTEGER NOT NULL DEFAULT 0,
                    level_distribution TEXT NOT NULL DEFAULT '{{}}',
                    total_elapsed REAL NOT NULL DEFAULT 0,
                    partial_rediscovery_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @staticmethod
    def _normalize_stats(entry: DomainStats | dict[str, Any]) -> DomainStats:
        """Normalize a persisted entry into a DomainStats with safe defaults."""
        if isinstance(entry, DomainStats):
            return entry
        return DomainStats.model_validate(entry)

    def extract_domain(self, url: str) -> str:
        """Extract the normalized domain from a URL (single source of truth)."""
        return extract_domain(url)

    async def _ensure_migrated(self) -> None:
        if self._migrated:
            return
        client = await self._connect()
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TRACKING_TABLE} (
                domain TEXT PRIMARY KEY,
                llm_calls INTEGER NOT NULL DEFAULT 0,
                url_count INTEGER NOT NULL DEFAULT 0,
                level_distribution TEXT NOT NULL DEFAULT '{{}}',
                total_elapsed REAL NOT NULL DEFAULT 0,
                partial_rediscovery_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._migrated = True

    @staticmethod
    def _stats_from_row(row: tuple[Any, ...], columns: tuple[str, ...]) -> DomainStats:
        values = dict(zip(columns, row, strict=False))
        raw_dist = values.get('level_distribution') or '{}'
        try:
            dist = json.loads(str(raw_dist))
        except json.JSONDecodeError:
            dist = {}
        return DomainStats(
            llm_calls=int(values.get('llm_calls') or 0),
            url_count=int(values.get('url_count') or 0),
            level_distribution={str(k): int(v) for k, v in dict(dist).items()},
            total_elapsed=float(values.get('total_elapsed') or 0.0),
            partial_rediscovery_count=int(values.get('partial_rediscovery_count') or 0),
        )

    async def _load_data(self) -> dict[str, Any]:
        """Load tracking data as the legacy `{domain: stats}` shape."""
        return {domain: stats.model_dump() for domain, stats in (await self.get_all_stats()).items()}

    async def _save_data(self, data: dict[str, Any]) -> None:
        """Replace all tracking data from the legacy `{domain: stats}` shape."""
        await self._ensure_migrated()
        client = await self._connect()
        tx = client.transaction()
        try:
            await tx.execute(f'DELETE FROM {_TRACKING_TABLE}')
            for domain, raw in data.items():
                stats = self._normalize_stats(raw)
                await tx.execute(
                    f"""
                    INSERT INTO {_TRACKING_TABLE} (
                        domain, llm_calls, url_count, level_distribution,
                        total_elapsed, partial_rediscovery_count, updated_at
                    ) VALUES (
                        :domain, :llm_calls, :url_count, :level_distribution,
                        :total_elapsed, :partial_rediscovery_count, CURRENT_TIMESTAMP
                    )
                    """,
                    {
                        'domain': domain,
                        'llm_calls': stats.llm_calls,
                        'url_count': stats.url_count,
                        'level_distribution': json.dumps(stats.level_distribution, separators=(',', ':')),
                        'total_elapsed': stats.total_elapsed,
                        'partial_rediscovery_count': stats.partial_rediscovery_count,
                    },
                )
            await tx.commit()
        except BaseException:
            await tx.rollback()
            raise

    async def record_url(
        self,
        url: str,
        used_llm: bool = False,
        level_distribution: dict[str, int] | None = None,
        elapsed: float | None = None,
        partial_discovery: bool = False,
    ) -> DomainStats:
        """Record that a URL was processed."""
        async with self._lock:
            return await self._record_url_locked(url, used_llm, level_distribution, elapsed, partial_discovery)

    async def _record_url_locked(
        self,
        url: str,
        used_llm: bool = False,
        level_distribution: dict[str, int] | None = None,
        elapsed: float | None = None,
        partial_discovery: bool = False,
    ) -> DomainStats:
        """Execute read-modify-write under the caller's lock."""
        domain = self.extract_domain(url)
        current = await self.get_stats(domain)
        current.url_count += 1
        if used_llm:
            current.llm_calls += 1
        if elapsed is not None:
            current.total_elapsed += elapsed
        if level_distribution:
            for level, count in level_distribution.items():
                current.level_distribution[level] = current.level_distribution.get(level, 0) + count
        if partial_discovery:
            current.partial_rediscovery_count += 1

        await self._ensure_migrated()
        client = await self._connect()
        await client.execute(
            f"""
            INSERT INTO {_TRACKING_TABLE} (
                domain, llm_calls, url_count, level_distribution,
                total_elapsed, partial_rediscovery_count, updated_at
            ) VALUES (
                :domain, :llm_calls, :url_count, :level_distribution,
                :total_elapsed, :partial_rediscovery_count, CURRENT_TIMESTAMP
            )
            ON CONFLICT(domain) DO UPDATE SET
                llm_calls = excluded.llm_calls,
                url_count = excluded.url_count,
                level_distribution = excluded.level_distribution,
                total_elapsed = excluded.total_elapsed,
                partial_rediscovery_count = excluded.partial_rediscovery_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            {
                'domain': domain,
                'llm_calls': current.llm_calls,
                'url_count': current.url_count,
                'level_distribution': json.dumps(current.level_distribution, separators=(',', ':')),
                'total_elapsed': current.total_elapsed,
                'partial_rediscovery_count': current.partial_rediscovery_count,
            },
        )
        return current

    async def get_llm_calls(self, url_or_domain: str) -> int:
        """Get LLM call count for a URL or domain."""
        return (await self.get_stats(url_or_domain)).llm_calls

    async def get_url_count(self, url_or_domain: str) -> int:
        """Get URL count for a URL or domain."""
        return (await self.get_stats(url_or_domain)).url_count

    async def get_stats(self, url_or_domain: str) -> DomainStats:
        """Get all stats for a URL or domain."""
        domain = self.extract_domain(url_or_domain) if '://' in url_or_domain else url_or_domain
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT llm_calls, url_count, level_distribution, total_elapsed, partial_rediscovery_count
            FROM {_TRACKING_TABLE}
            WHERE domain = :domain
            """,
            {'domain': domain},
        )
        if not result.rows:
            return DomainStats()
        return self._stats_from_row(result.rows[0], tuple(result.columns))

    async def get_all_stats(self) -> dict[str, DomainStats]:
        """Get all tracking data."""
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT domain, llm_calls, url_count, level_distribution, total_elapsed, partial_rediscovery_count
            FROM {_TRACKING_TABLE}
            ORDER BY domain
            """
        )
        return {str(row[0]): self._stats_from_row(row, tuple(result.columns)) for row in result.rows}

    async def print_stats(self) -> None:
        """Print statistics in a readable format."""
        all_stats = await self.get_all_stats()

        if not all_stats:
            print('\nNo tracking data yet.\n')
            return

        print('\n' + '=' * 70)
        print('LLM CALL TRACKING')
        print('=' * 70)

        total_llm_calls = sum(s.llm_calls for s in all_stats.values())
        total_urls = sum(s.url_count for s in all_stats.values())
        total_elapsed = sum(s.total_elapsed for s in all_stats.values())

        print(f'\nTotal LLM Calls: {total_llm_calls}')
        print(f'Total URLs Processed: {total_urls}')
        print(f'Total Elapsed: {total_elapsed:.1f}s')
        print(f'Total Domains: {len(all_stats)}')

        print('\n' + '-' * 70)
        print('PER-DOMAIN BREAKDOWN:')
        print('-' * 70)

        sorted_domains = sorted(all_stats.items(), key=lambda x: x[1].llm_calls, reverse=True)
        for domain, stats in sorted_domains:
            if stats.url_count > 0:
                efficiency = (stats.url_count / stats.llm_calls) if stats.llm_calls > 0 else stats.url_count
                print(f'\n{domain}')
                print(f'  LLM Calls: {stats.llm_calls}')
                print(f'  URLs Processed: {stats.url_count}')
                print(f'  URLs per LLM Call: {efficiency:.1f}')

        print('\n' + '=' * 70 + '\n')

    async def reset(self, domain: str | None = None) -> None:
        """Reset tracking data."""
        await self._ensure_migrated()
        client = await self._connect()
        if domain:
            stats = await self.get_stats(domain)
            if stats == DomainStats():
                print(f'No tracking data for {domain}')
                return
            await client.execute(f'DELETE FROM {_TRACKING_TABLE} WHERE domain = :domain', {'domain': domain})
            print(f'✓ Reset tracking for {domain}')
        else:
            await client.execute(f'DELETE FROM {_TRACKING_TABLE}')
            print('✓ Reset all tracking data')


async def _example_main() -> None:  # pragma: no cover
    tracker = LLMTracker()
    print('Simulating scraping workflow...\n')
    await tracker.record_url('https://finance.yahoo.com/article-1', used_llm=True)
    print(f'LLM calls: {await tracker.get_llm_calls("finance.yahoo.com")}')
    await tracker.print_stats()


if __name__ == '__main__':
    asyncio.run(_example_main())
