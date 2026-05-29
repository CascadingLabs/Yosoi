"""The narrow, append-only :class:`ContentSink` interface.

A sink is the seam between Yosoi's extraction output and wherever a downstream
consumer wants to read it from. The interface is intentionally tiny — append a
record, read records back by url, read records back by time — and carries no
entity- or consumer-specific concepts. Backends (SQLite, Postgres, Mongo) are a
choice, not a commitment.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from yosoi.sinks.record import ContentRecord


@runtime_checkable
class ContentSink(Protocol):
    """Append-only store for extracted :class:`ContentRecord` documents.

    Implementations are async and own their own connection lifecycle. They may
    be used as async context managers; :meth:`close` releases the underlying
    driver resources.

    Semantics are append-only: :meth:`write` always inserts a new row/document
    and never updates an existing one. Reads return every matching version,
    newest-first, so callers can pick the latest or inspect history.
    """

    async def write(self, doc: ContentRecord) -> None:
        """Append ``doc`` to the store. Never overwrites a prior record."""
        ...

    async def read_by_url(self, url: str) -> list[ContentRecord]:
        """Return every record for ``url``, ordered newest-first by ``scraped_at``."""
        ...

    async def read_by_time(self, start: datetime, end: datetime | None = None) -> list[ContentRecord]:
        """Return records with ``start <= scraped_at <= end``, newest-first.

        Args:
            start: Inclusive lower bound on ``scraped_at``.
            end: Inclusive upper bound. ``None`` means open-ended (up to now).

        """
        ...

    async def close(self) -> None:
        """Release any driver/connection resources held by the sink."""
        ...
