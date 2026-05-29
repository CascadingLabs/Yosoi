"""MongoDB content sink (requires the ``mongo`` extra).

Backed by PyMongo's async ``AsyncMongoClient``. The driver is imported lazily so
that a bare ``yosoi`` install does not depend on it; a missing driver fails with
a helpful ``uv add 'yosoi[pymongo]'`` message rather than a raw ImportError.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yosoi.sinks._internal import missing_dependency, to_utc
from yosoi.sinks.record import ContentRecord


def _import_async_client() -> Any:
    try:
        from pymongo import AsyncMongoClient

        return AsyncMongoClient
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise missing_dependency('pymongo', 'pymongo') from exc


class MongoSink:
    """Append-only :class:`~yosoi.sinks.base.ContentSink` backed by MongoDB.

    Each record is stored as a document ``{url, content, scraped_at, source}``.
    Indexes on ``url`` and ``scraped_at`` are ensured on first write.

    Args:
        uri: MongoDB connection string (e.g. ``'mongodb://localhost:27017'``).
        database: Database name. Defaults to ``'yosoi'``.
        collection: Collection name. Defaults to ``'content'``.

    """

    def __init__(self, uri: str, *, database: str = 'yosoi', collection: str = 'content') -> None:
        """Create the sink. Imports the pymongo driver eagerly (see class docstring)."""
        client_cls = _import_async_client()
        self._client: Any = client_cls(uri)
        self._collection: Any = self._client[database][collection]
        self._indexes_ready = False

    async def _ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        await self._collection.create_index('url')
        await self._collection.create_index('scraped_at')
        self._indexes_ready = True

    @staticmethod
    def _to_record(doc: dict[str, Any]) -> ContentRecord:
        return ContentRecord(url=doc['url'], content=doc['content'], scraped_at=doc['scraped_at'], source=doc['source'])

    async def write(self, doc: ContentRecord) -> None:
        """Append ``doc`` as a new document. Never overwrites."""
        await self._ensure_indexes()
        await self._collection.insert_one(
            {
                'url': doc.url,
                'content': doc.content,
                'scraped_at': to_utc(doc.scraped_at),
                'source': doc.source,
            }
        )

    async def _find(self, query: dict[str, Any]) -> list[ContentRecord]:
        cursor = self._collection.find(query, projection={'_id': False}).sort('scraped_at', -1)
        return [self._to_record(doc) async for doc in cursor]

    async def read_by_url(self, url: str) -> list[ContentRecord]:
        """Return every record for ``url``, newest-first."""
        return await self._find({'url': url})

    async def read_by_time(self, start: datetime, end: datetime | None = None) -> list[ContentRecord]:
        """Return records with ``start <= scraped_at <= end``, newest-first."""
        bounds: dict[str, Any] = {'$gte': to_utc(start)}
        if end is not None:
            bounds['$lte'] = to_utc(end)
        return await self._find({'scraped_at': bounds})

    async def close(self) -> None:
        """Close the underlying client."""
        await self._client.close()

    async def __aenter__(self) -> MongoSink:
        """Enter the async context, returning the sink."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context, closing the client."""
        await self.close()
