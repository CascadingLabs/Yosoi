"""PostgreSQL content sink (requires the ``psycopg`` extra).

Backed by psycopg 3's async API. The driver is imported lazily so that a bare
``yosoi`` install does not depend on it; a missing driver fails with a helpful
``uv add 'yosoi[psycopg]'`` message rather than a raw ImportError.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yosoi.sinks._internal import missing_dependency, to_utc
from yosoi.sinks.record import ContentRecord


def _import_psycopg() -> Any:
    try:
        import psycopg
        import psycopg.rows
        import psycopg.sql
        import psycopg.types.json

        return psycopg
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise missing_dependency('psycopg', 'psycopg') from exc


class PostgresSink:
    """Append-only :class:`~yosoi.sinks.base.ContentSink` backed by PostgreSQL.

    Content is stored in a ``JSONB`` column; ``scraped_at`` in ``TIMESTAMPTZ``.
    The table and its indexes are created on first use if absent.

    Args:
        conninfo: A libpq connection string or URL
            (e.g. ``'postgresql://user:pw@host:5432/db'``).
        table: Destination table name. Defaults to ``'content'``.

    """

    def __init__(self, conninfo: str, *, table: str = 'content') -> None:
        """Create the sink. Imports the psycopg driver eagerly (see class docstring)."""
        self._psycopg = _import_psycopg()
        self._conninfo = conninfo
        self._table = table
        self._conn: Any = None
        self._ready = False

    @property
    def _table_ident(self) -> Any:
        return self._psycopg.sql.Identifier(self._table)

    async def _connection(self) -> Any:
        if self._conn is None or self._conn.closed:
            self._conn = await self._psycopg.AsyncConnection.connect(self._conninfo, autocommit=True)
            self._ready = False
        if not self._ready:
            await self._ensure_schema(self._conn)
            self._ready = True
        return self._conn

    async def _ensure_schema(self, conn: Any) -> None:
        sql = self._psycopg.sql
        await conn.execute(
            sql.SQL(
                'CREATE TABLE IF NOT EXISTS {table} ('
                'id BIGSERIAL PRIMARY KEY, '
                'url TEXT NOT NULL, '
                'content JSONB NOT NULL, '
                'scraped_at TIMESTAMPTZ NOT NULL, '
                'source TEXT NOT NULL)'
            ).format(table=self._table_ident)
        )
        await conn.execute(
            sql.SQL('CREATE INDEX IF NOT EXISTS {idx} ON {table} (url)').format(
                idx=sql.Identifier(f'idx_{self._table}_url'), table=self._table_ident
            )
        )
        await conn.execute(
            sql.SQL('CREATE INDEX IF NOT EXISTS {idx} ON {table} (scraped_at)').format(
                idx=sql.Identifier(f'idx_{self._table}_scraped_at'), table=self._table_ident
            )
        )

    def _to_record(self, row: dict[str, Any]) -> ContentRecord:
        return ContentRecord(url=row['url'], content=row['content'], scraped_at=row['scraped_at'], source=row['source'])

    async def write(self, doc: ContentRecord) -> None:
        """Append ``doc`` as a new row. Never overwrites."""
        conn = await self._connection()
        jsonb = self._psycopg.types.json.Jsonb
        sql = self._psycopg.sql
        await conn.execute(
            sql.SQL('INSERT INTO {table} (url, content, scraped_at, source) VALUES (%s, %s, %s, %s)').format(
                table=self._table_ident
            ),
            (doc.url, jsonb(doc.content), to_utc(doc.scraped_at), doc.source),
        )

    async def _fetch(self, where_sql: Any, params: tuple[Any, ...]) -> list[ContentRecord]:
        conn = await self._connection()
        sql = self._psycopg.sql
        dict_row = self._psycopg.rows.dict_row
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                sql.SQL('SELECT url, content, scraped_at, source FROM {table} WHERE ').format(table=self._table_ident)
                + where_sql
                + sql.SQL(' ORDER BY scraped_at DESC'),
                params,
            )
            rows = await cur.fetchall()
        return [self._to_record(row) for row in rows]

    async def read_by_url(self, url: str) -> list[ContentRecord]:
        """Return every record for ``url``, newest-first."""
        return await self._fetch(self._psycopg.sql.SQL('url = %s'), (url,))

    async def read_by_time(self, start: datetime, end: datetime | None = None) -> list[ContentRecord]:
        """Return records with ``start <= scraped_at <= end``, newest-first."""
        sql = self._psycopg.sql
        if end is None:
            return await self._fetch(sql.SQL('scraped_at >= %s'), (to_utc(start),))
        return await self._fetch(sql.SQL('scraped_at >= %s AND scraped_at <= %s'), (to_utc(start), to_utc(end)))

    async def close(self) -> None:
        """Close the underlying connection if open."""
        if self._conn is not None and not self._conn.closed:
            await self._conn.close()
        self._conn = None
        self._ready = False

    async def __aenter__(self) -> PostgresSink:
        """Enter the async context, returning the sink."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context, closing the connection."""
        await self.close()
