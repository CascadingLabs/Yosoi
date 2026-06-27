"""Shared SQLite/libSQL state-store primitives for Yosoi local runtime state."""

from __future__ import annotations

import os
import sqlite3
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from yosoi.utils.files import init_yosoi

_DEFAULT_DB_NAME = 'yosoi.sqlite3'
_DB_URL_ENV = 'YOSOI_METRICS_DATABASE_URL'
_DB_TOKEN_ENV = 'YOSOI_METRICS_AUTH_TOKEN'
_StoreT = TypeVar('_StoreT', bound='YosoiSQLiteStore')


@dataclass(frozen=True)
class SQLiteResult:
    """Small result wrapper matching the rows/columns surface storage modules use."""

    rows: list[tuple[Any, ...]]
    columns: tuple[str, ...]


class SQLiteClient:
    """Async wrapper around the stdlib SQLite connection used by Yosoi stores."""

    def __init__(self, database_url: str) -> None:
        """Open a local SQLite database from a file: URL."""
        if not database_url.startswith('file:'):
            raise ValueError('Only local file: SQLite URLs are supported by the built-in Yosoi store')
        self.db_path = Path(database_url.removeprefix('file:'))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> SQLiteResult:
        """Execute one statement and return fetched rows when present."""
        return self._execute_sync(sql, params or {})

    def transaction(self) -> SQLiteTransaction:
        """Create a transaction object with the same async execute/commit API."""
        return SQLiteTransaction(self)

    async def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __del__(self) -> None:
        """Close the connection if callers did not explicitly close the store."""
        with suppress(Exception):
            self._conn.close()

    def _execute_sync(self, sql: str, params: dict[str, Any]) -> SQLiteResult:
        cursor = self._conn.execute(sql, params)
        if cursor.description is None:
            return SQLiteResult(rows=[], columns=())
        columns = tuple(str(column[0]) for column in cursor.description)
        rows = [tuple(row) for row in cursor.fetchall()]
        return SQLiteResult(rows=rows, columns=columns)


class SQLiteTransaction:
    """Async transaction wrapper for the local SQLite client."""

    def __init__(self, client: SQLiteClient) -> None:
        """Prepare a transaction on the provided SQLite client."""
        self._client = client
        self._begun = False
        self._closed = False

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> SQLiteResult:
        """Execute one statement inside the transaction."""
        if not self._begun:
            self._client._conn.execute('BEGIN')
            self._begun = True
        return self._client._execute_sync(sql, params or {})

    async def commit(self) -> None:
        """Commit the transaction if it started."""
        if self._begun and not self._closed:
            self._client._conn.commit()
        self._closed = True

    async def rollback(self) -> None:
        """Rollback the transaction if it started."""
        if self._begun and not self._closed:
            self._client._conn.rollback()
        self._closed = True


def default_sqlite_database_url() -> str:
    """Return the default local SQLite/libSQL database URL under `.yosoi`."""
    return f'file:{init_yosoi() / _DEFAULT_DB_NAME}'


def normalize_database_url(raw_url: str | Path) -> str:
    """Normalize filesystem paths to libSQL file URLs."""
    raw = str(raw_url)
    if '://' not in raw and not raw.startswith('file:'):
        return f'file:{Path(raw)}'
    return raw


class YosoiSQLiteStore(ABC):
    """Base class for modular Yosoi state stores sharing `.yosoi/yosoi.sqlite3`."""

    def __init__(self, database_url: str | Path | None = None, auth_token: str | None = None) -> None:
        """Create a store handle for a local SQLite file or remote libSQL URL."""
        raw_url = (
            str(database_url) if database_url is not None else os.getenv(_DB_URL_ENV) or default_sqlite_database_url()
        )
        self.database_url = normalize_database_url(raw_url)
        self.auth_token = auth_token if auth_token is not None else os.getenv(_DB_TOKEN_ENV)
        self.db_path = Path(self.database_url.removeprefix('file:')) if self.database_url.startswith('file:') else None
        if self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._client: SQLiteClient | None = None
        self._migrated = False

    async def __aenter__(self: _StoreT) -> _StoreT:
        """Return this store for async context-manager usage."""
        await self._connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Close the libSQL client when leaving a context."""
        await self.close()

    async def close(self) -> None:
        """Close the libSQL client."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def _connect(self) -> SQLiteClient:
        if self._client is None:
            if self.auth_token is not None:
                raise ValueError('YOSOI_METRICS_AUTH_TOKEN requires an external libSQL client, which is not bundled')
            self._client = SQLiteClient(self.database_url)
        return self._client

    @abstractmethod
    async def _ensure_migrated(self) -> None:
        """Create/reset this module's schema before reads or writes."""
        raise NotImplementedError
