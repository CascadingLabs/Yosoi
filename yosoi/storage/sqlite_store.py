"""Shared SQLite/libSQL state-store primitives for Yosoi local runtime state."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypeVar

from libsql_client import Client, create_client

from yosoi.utils.files import init_yosoi

_DEFAULT_DB_NAME = 'yosoi.sqlite3'
_DB_URL_ENV = 'YOSOI_METRICS_DATABASE_URL'
_DB_TOKEN_ENV = 'YOSOI_METRICS_AUTH_TOKEN'
_StoreT = TypeVar('_StoreT', bound='YosoiSQLiteStore')


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
        self._client: Client | None = None
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

    async def _connect(self) -> Client:
        if self._client is None:
            self._client = create_client(self.database_url, auth_token=self.auth_token)
        return self._client

    @abstractmethod
    async def _ensure_migrated(self) -> None:
        """Create/reset this module's schema before reads or writes."""
        raise NotImplementedError
