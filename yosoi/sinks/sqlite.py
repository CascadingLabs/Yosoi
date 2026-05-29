"""SQLite content sink.

Uses the stdlib :mod:`sqlite3` driver — no optional extra required. Each
operation is run in a worker thread via :func:`asyncio.to_thread` so the
synchronous driver does not block the event loop. Connections are opened
per-operation (cheap for SQLite) which keeps the sink safe to share across
tasks without juggling sqlite3's thread affinity.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from yosoi.sinks._internal import to_utc
from yosoi.sinks.record import ContentRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    content TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_content_url ON content (url);
CREATE INDEX IF NOT EXISTS idx_content_scraped_at ON content (scraped_at);
"""


class SqliteSink:
    """Append-only :class:`~yosoi.sinks.base.ContentSink` backed by a SQLite file.

    Args:
        db_path: Path to the SQLite database file. Parent directories are
            created on first write. Use ``':memory:'`` for an ephemeral store
            (note: a fresh in-memory DB is created per connection, so this is
            only useful within a single short-lived sink instance kept open).

    """

    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        """Create the sink (see class docstring for ``db_path`` semantics)."""
        self._db_path = str(db_path)

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _write_sync(self, url: str, content: str, scraped_at: str, source: str) -> None:
        if self._db_path != ':memory:':
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._open()
        try:
            conn.executescript(_SCHEMA)
            conn.execute(
                'INSERT INTO content (url, content, scraped_at, source) VALUES (?, ?, ?, ?)',
                (url, content, scraped_at, source),
            )
            conn.commit()
        finally:
            conn.close()

    def _query_sync(self, where: str, params: tuple[str, ...]) -> list[sqlite3.Row]:
        conn = self._open()
        try:
            conn.executescript(_SCHEMA)
            cursor = conn.execute(
                f'SELECT url, content, scraped_at, source FROM content WHERE {where} ORDER BY scraped_at DESC',
                params,
            )
            return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def _to_record(row: sqlite3.Row) -> ContentRecord:
        return ContentRecord(
            url=row['url'],
            content=json.loads(row['content']),
            scraped_at=datetime.fromisoformat(row['scraped_at']),
            source=row['source'],
        )

    async def write(self, doc: ContentRecord) -> None:
        """Append ``doc`` as a new row. Never overwrites."""
        await asyncio.to_thread(
            self._write_sync,
            doc.url,
            json.dumps(doc.content),
            to_utc(doc.scraped_at).isoformat(),
            doc.source,
        )

    async def read_by_url(self, url: str) -> list[ContentRecord]:
        """Return every record for ``url``, newest-first."""
        rows = await asyncio.to_thread(self._query_sync, 'url = ?', (url,))
        return [self._to_record(row) for row in rows]

    async def read_by_time(self, start: datetime, end: datetime | None = None) -> list[ContentRecord]:
        """Return records with ``start <= scraped_at <= end``, newest-first."""
        start_iso = to_utc(start).isoformat()
        if end is None:
            rows = await asyncio.to_thread(self._query_sync, 'scraped_at >= ?', (start_iso,))
        else:
            rows = await asyncio.to_thread(
                self._query_sync, 'scraped_at >= ? AND scraped_at <= ?', (start_iso, to_utc(end).isoformat())
            )
        return [self._to_record(row) for row in rows]

    async def close(self) -> None:
        """No-op: connections are opened per-operation and closed immediately."""

    async def __aenter__(self) -> SqliteSink:
        """Enter the async context, returning the sink."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context (no-op close)."""
        await self.close()
