"""Async libSQL/Turso metrics store for cache status and metrics."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from libsql_client import Client, LibsqlError, create_client
from pydantic import ValidationError

from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot, SnapshotMap
from yosoi.utils.files import init_yosoi

_DEFAULT_DB_NAME = 'metrics.sqlite3'
_DEFAULT_ROUTE = '/'
_DEFAULT_SELECTOR_LEVEL = 'all'
_CACHE_FIELD_TABLE = 'cache_field_metrics'
_CACHE_EVENT_TABLE = 'cache_events'
_CACHE_FIELD_KEY = ('contract_fingerprint', 'field_name', 'domain', 'route_signature', 'selector_level')
_CACHE_FIELD_UPDATE_COLUMNS = (
    'source_url',
    'top_level_domain',
    'status',
    'selector_json',
    'discovered_at',
    'last_verified_at',
    'last_failed_at',
    'failure_count',
    'updated_at',
)
_DB_URL_ENV = 'YOSOI_METRICS_DATABASE_URL'
_DB_TOKEN_ENV = 'YOSOI_METRICS_AUTH_TOKEN'


@dataclass(frozen=True)
class CacheFieldMetric:
    """Field-addressable cache metrics record."""

    contract_fingerprint: str
    field_name: str
    domain: str
    top_level_domain: str
    route_signature: str
    selector_level: str
    source_url: str | None
    status: str
    discovered_at: str | None
    last_verified_at: str | None
    last_failed_at: str | None
    failure_count: int


@dataclass(frozen=True)
class ContractCacheMetrics:
    """Contract-centered cache metrics summary."""

    contract_fingerprint: str
    domains: list[str]
    top_level_domains: list[str]
    routes: list[str]
    fields: list[str]
    field_metrics: list[CacheFieldMetric]
    event_counts: dict[str, int] = field(default_factory=dict)
    run_count: int = 0
    url_count: int = 0


@dataclass(frozen=True)
class DomainCacheMetrics:
    """Domain-centered cache metrics summary."""

    domain: str
    contract_fingerprints: list[str]
    top_level_domains: list[str]
    routes: list[str]
    fields: list[str]
    field_metrics: list[CacheFieldMetric]
    event_counts: dict[str, int] = field(default_factory=dict)
    run_count: int = 0
    url_count: int = 0


@dataclass(frozen=True)
class CacheBackfillResult:
    """Result of importing existing selector JSON files into metrics."""

    scanned_files: int = 0
    imported_files: int = 0
    skipped_files: int = 0
    imported_fields: int = 0
    domains: list[str] = field(default_factory=list)
    contract_fingerprints: list[str] = field(default_factory=list)


def default_metrics_database_url() -> str:
    """Return the default local libSQL metrics URL under `.yosoi`."""
    return f'file:{init_yosoi().parent / _DEFAULT_DB_NAME}'


def route_signature_for_url(url: str) -> str:
    """Return the first route bucket for a URL: normalized path, query excluded."""
    parsed = urlparse(url)
    path = parsed.path or _DEFAULT_ROUTE
    return path if path.startswith('/') else f'/{path}'


def top_level_domain_for_domain(domain: str) -> str:
    """Return a coarse top-level/registered-domain bucket without PSL dependency."""
    parts = [part for part in domain.lower().split('.') if part]
    if len(parts) <= 2:
        return domain.lower()
    return '.'.join(parts[-2:])


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _snapshot_payload(snapshot: SelectorSnapshot) -> str:
    return json.dumps(snapshot.model_dump(mode='json'), sort_keys=True)


def _row_dict(columns: tuple[str, ...], row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(columns, row, strict=True))


def _metric_from_row(columns: tuple[str, ...], row: tuple[Any, ...]) -> CacheFieldMetric:
    values = _row_dict(columns, row)
    return CacheFieldMetric(
        contract_fingerprint=values['contract_fingerprint'],
        field_name=values['field_name'],
        domain=values['domain'],
        top_level_domain=values['top_level_domain'],
        route_signature=values['route_signature'],
        selector_level=values['selector_level'],
        source_url=values['source_url'],
        status=values['status'],
        discovered_at=values['discovered_at'],
        last_verified_at=values['last_verified_at'],
        last_failed_at=values['last_failed_at'],
        failure_count=values['failure_count'],
    )


def _upsert_field_sql() -> str:
    columns = (*_CACHE_FIELD_KEY, *_CACHE_FIELD_UPDATE_COLUMNS)
    column_sql = ', '.join(columns)
    value_sql = ', '.join(f':{column}' for column in columns)
    key_sql = ', '.join(_CACHE_FIELD_KEY)
    update_sql = ', '.join(f'{column}=excluded.{column}' for column in _CACHE_FIELD_UPDATE_COLUMNS)
    return f"""
        INSERT INTO {_CACHE_FIELD_TABLE} ({column_sql})
        VALUES ({value_sql})
        ON CONFLICT({key_sql}) DO UPDATE SET {update_sql}
    """


class LibSQLCacheMetricsStore:
    """Async libSQL/Turso metrics store for selector cache status and events."""

    def __init__(self, database_url: str | Path | None = None, auth_token: str | None = None):
        """Create a metrics store handle.

        Args:
            database_url: libSQL URL. Defaults to `YOSOI_METRICS_DATABASE_URL` or local `.yosoi/metrics.sqlite3`.
            auth_token: Turso/libSQL auth token. Defaults to `YOSOI_METRICS_AUTH_TOKEN`.
        """
        raw_url = (
            str(database_url) if database_url is not None else os.getenv(_DB_URL_ENV) or default_metrics_database_url()
        )
        if '://' not in raw_url and not raw_url.startswith('file:'):
            raw_url = f'file:{Path(raw_url)}'
        self.database_url = raw_url
        self.auth_token = auth_token if auth_token is not None else os.getenv(_DB_TOKEN_ENV)
        self.db_path = Path(self.database_url.removeprefix('file:')) if self.database_url.startswith('file:') else None
        if self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._client: Client | None = None
        self._migrated = False

    async def __aenter__(self) -> LibSQLCacheMetricsStore:
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

    async def upsert_snapshots(
        self,
        *,
        url: str,
        domain: str,
        snapshots: dict[str, SelectorSnapshot],
        contract_fingerprint: str | None,
        route_signature: str | None = None,
        selector_level: str = _DEFAULT_SELECTOR_LEVEL,
        event_type: str = 'write',
    ) -> None:
        """Record a snapshot file as per-field cache metrics."""
        await self._ensure_migrated()
        client = await self._connect()
        contract_fp = contract_fingerprint or ''
        route = route_signature or route_signature_for_url(url)
        tld = top_level_domain_for_domain(domain)
        now = _iso(datetime.now(timezone.utc))
        tx = client.transaction()
        try:
            if event_type == 'write':
                await self._record_event_on_executor(
                    tx,
                    'run',
                    contract_fingerprint=contract_fp,
                    domain=domain,
                    top_level_domain=tld,
                    route_signature=route,
                    selector_level=selector_level,
                    url=url,
                    detail={'mode': 'write'},
                )
            for field_name, snapshot in snapshots.items():
                metric = {
                    'contract_fingerprint': contract_fp,
                    'field_name': field_name,
                    'domain': domain,
                    'top_level_domain': tld,
                    'route_signature': route,
                    'selector_level': selector_level,
                    'source_url': url,
                    'status': snapshot.status.value,
                    'selector_json': _snapshot_payload(snapshot),
                    'discovered_at': _iso(snapshot.discovered_at),
                    'last_verified_at': _iso(snapshot.last_verified_at),
                    'last_failed_at': _iso(snapshot.last_failed_at),
                    'failure_count': snapshot.failure_count,
                    'updated_at': now,
                }
                await tx.execute(_upsert_field_sql(), metric)
                await self._record_event_on_executor(
                    tx,
                    event_type,
                    contract_fingerprint=contract_fp,
                    field_name=field_name,
                    domain=domain,
                    top_level_domain=tld,
                    route_signature=route,
                    selector_level=selector_level,
                    url=url,
                )
            await tx.commit()
        except BaseException:
            await tx.rollback()
            raise

    async def record_cache_hit(
        self,
        *,
        url: str,
        domain: str,
        contract_fingerprint: str | None,
        field_names: set[str] | list[str],
        route_signature: str | None = None,
        selector_level: str = _DEFAULT_SELECTOR_LEVEL,
    ) -> None:
        """Record a cached replay/use without counting it as a selector write."""
        await self._ensure_migrated()
        client = await self._connect()
        contract_fp = contract_fingerprint or ''
        route = route_signature or route_signature_for_url(url)
        tld = top_level_domain_for_domain(domain)
        tx = client.transaction()
        try:
            await self._record_event_on_executor(
                tx,
                'run',
                contract_fingerprint=contract_fp,
                domain=domain,
                top_level_domain=tld,
                route_signature=route,
                selector_level=selector_level,
                url=url,
                detail={'mode': 'cache'},
            )
            for field_name in sorted(field_names):
                await self._record_event_on_executor(
                    tx,
                    'hit',
                    contract_fingerprint=contract_fp,
                    field_name=field_name,
                    domain=domain,
                    top_level_domain=tld,
                    route_signature=route,
                    selector_level=selector_level,
                    url=url,
                )
            await tx.commit()
        except BaseException:
            await tx.rollback()
            raise

    async def record_verdict(
        self,
        *,
        domain: str,
        field_name: str,
        verdict: CacheVerdict,
        contract_fingerprint: str | None,
        route_signature: str | None = None,
        selector_level: str | None = None,
    ) -> None:
        """Record a per-field verification result in the metrics store."""
        await self._ensure_migrated()
        client = await self._connect()
        contract_fp = contract_fingerprint or ''
        now = _iso(datetime.now(timezone.utc))
        event_type = 'verify' if verdict == CacheVerdict.FRESH else 'fail'
        conditions = ['contract_fingerprint = :contract_fingerprint', 'domain = :domain', 'field_name = :field_name']
        params: dict[str, Any] = {'contract_fingerprint': contract_fp, 'domain': domain, 'field_name': field_name}
        if route_signature is not None:
            conditions.append('route_signature = :route_signature')
            params['route_signature'] = route_signature
        if selector_level is not None:
            conditions.append('selector_level = :selector_level')
            params['selector_level'] = selector_level

        if verdict == CacheVerdict.FRESH:
            update_sql = 'last_verified_at = :now, failure_count = 0, updated_at = :now'
        else:
            update_sql = 'last_failed_at = :now, failure_count = failure_count + 1, updated_at = :now'
        params['now'] = now

        tx = client.transaction()
        try:
            await tx.execute(
                f"""
                UPDATE {_CACHE_FIELD_TABLE}
                SET {update_sql}
                WHERE {' AND '.join(conditions)}
                """,
                params,
            )
            await self._record_event_on_executor(
                tx,
                event_type,
                contract_fingerprint=contract_fp,
                field_name=field_name,
                domain=domain,
                top_level_domain=top_level_domain_for_domain(domain),
                route_signature=route_signature,
                selector_level=selector_level,
                detail={'verdict': verdict.value},
            )
            await tx.commit()
        except BaseException:
            await tx.rollback()
            raise

    async def summarize_contract(self, contract_fingerprint: str) -> ContractCacheMetrics:
        """Return all cache metrics for one contract fingerprint."""
        await self._ensure_migrated()
        await self._backfill_contract(contract_fingerprint)
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT *
            FROM {_CACHE_FIELD_TABLE}
            WHERE contract_fingerprint = :contract_fingerprint
            ORDER BY domain, route_signature, field_name
            """,
            {'contract_fingerprint': contract_fingerprint},
        )
        rows = [_metric_from_row(result.columns, row) for row in result.rows]
        event_counts, event_urls = await self._contract_event_summary(contract_fingerprint)
        field_urls = {row.source_url for row in rows if row.source_url}
        return ContractCacheMetrics(
            contract_fingerprint=contract_fingerprint,
            domains=sorted({row.domain for row in rows}),
            top_level_domains=sorted({row.top_level_domain for row in rows}),
            routes=sorted({row.route_signature for row in rows}),
            fields=sorted({row.field_name for row in rows}),
            field_metrics=rows,
            event_counts=event_counts,
            run_count=event_counts.get('run', 0),
            url_count=len(field_urls | event_urls),
        )

    async def summarize_domain(self, domain: str, contract_fingerprint: str | None = None) -> DomainCacheMetrics:
        """Return all cache metrics for one domain, optionally scoped to one contract."""
        await self._ensure_migrated()
        await self.backfill_existing(contract_fingerprint=contract_fingerprint, domain=domain)
        rows = await self.list_domain_fields(domain, contract_fingerprint, backfill=False)
        event_counts, event_urls = await self._event_summary(domain=domain, contract_fingerprint=contract_fingerprint)
        field_urls = {row.source_url for row in rows if row.source_url}
        return DomainCacheMetrics(
            domain=domain,
            contract_fingerprints=sorted({row.contract_fingerprint for row in rows}),
            top_level_domains=sorted({row.top_level_domain for row in rows}),
            routes=sorted({row.route_signature for row in rows}),
            fields=sorted({row.field_name for row in rows}),
            field_metrics=rows,
            event_counts=event_counts,
            run_count=event_counts.get('run', 0),
            url_count=len(field_urls | event_urls),
        )

    async def list_domain_fields(
        self, domain: str, contract_fingerprint: str | None = None, *, backfill: bool = True
    ) -> list[CacheFieldMetric]:
        """Return field metrics for a domain, optionally scoped to one contract."""
        await self._ensure_migrated()
        if backfill:
            await self.backfill_existing(contract_fingerprint=contract_fingerprint, domain=domain)
        conditions = ['domain = :domain']
        params: dict[str, Any] = {'domain': domain}
        if contract_fingerprint is not None:
            conditions.append('contract_fingerprint = :contract_fingerprint')
            params['contract_fingerprint'] = contract_fingerprint
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT *
            FROM {_CACHE_FIELD_TABLE}
            WHERE {' AND '.join(conditions)}
            ORDER BY contract_fingerprint, route_signature, field_name
            """,
            params,
        )
        return [_metric_from_row(result.columns, row) for row in result.rows]

    async def _contract_event_summary(self, contract_fingerprint: str) -> tuple[dict[str, int], set[str]]:
        client = await self._connect()
        count_result = await client.execute(
            f"""
            SELECT event_type, COUNT(*) AS count
            FROM {_CACHE_EVENT_TABLE}
            WHERE contract_fingerprint = :contract_fingerprint
            GROUP BY event_type
            """,
            {'contract_fingerprint': contract_fingerprint},
        )
        counts = {row[0]: int(row[1]) for row in count_result.rows}
        url_result = await client.execute(
            f"""
            SELECT DISTINCT url
            FROM {_CACHE_EVENT_TABLE}
            WHERE contract_fingerprint = :contract_fingerprint AND url IS NOT NULL
            """,
            {'contract_fingerprint': contract_fingerprint},
        )
        return counts, {str(row[0]) for row in url_result.rows if row[0]}

    async def _event_summary(
        self, *, domain: str | None = None, contract_fingerprint: str | None = None
    ) -> tuple[dict[str, int], set[str]]:
        conditions: list[str] = []
        params: dict[str, Any] = {}
        if domain is not None:
            conditions.append('domain = :domain')
            params['domain'] = domain
        if contract_fingerprint is not None:
            conditions.append('contract_fingerprint = :contract_fingerprint')
            params['contract_fingerprint'] = contract_fingerprint
        where = f'WHERE {" AND ".join(conditions)}' if conditions else ''
        client = await self._connect()
        count_result = await client.execute(
            f"""
            SELECT event_type, COUNT(*) AS count
            FROM {_CACHE_EVENT_TABLE}
            {where}
            GROUP BY event_type
            """,
            params,
        )
        counts = {row[0]: int(row[1]) for row in count_result.rows}
        url_result = await client.execute(
            f"""
            SELECT DISTINCT url
            FROM {_CACHE_EVENT_TABLE}
            {where + ' AND' if where else 'WHERE'} url IS NOT NULL
            """,
            params,
        )
        return counts, {str(row[0]) for row in url_result.rows if row[0]}

    async def record_event(
        self,
        event_type: str,
        *,
        contract_fingerprint: str | None = None,
        field_name: str | None = None,
        domain: str | None = None,
        top_level_domain: str | None = None,
        route_signature: str | None = None,
        selector_level: str | None = None,
        url: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Append one cache event."""
        await self._ensure_migrated()
        client = await self._connect()
        await self._record_event_on_executor(
            client,
            event_type,
            contract_fingerprint=contract_fingerprint,
            field_name=field_name,
            domain=domain,
            top_level_domain=top_level_domain,
            route_signature=route_signature,
            selector_level=selector_level,
            url=url,
            detail=detail,
        )

    async def backfill_existing(
        self, *, contract_fingerprint: str | None = None, domain: str | None = None
    ) -> CacheBackfillResult:
        """Import existing selector JSON files as backfill metrics without counting them as writes."""
        await self._ensure_migrated()
        selector_dir = init_yosoi('selectors')
        scanned = imported = skipped = fields = 0
        domains: set[str] = set()
        contracts: set[str] = set()
        for path in selector_dir.glob('selectors_*.json'):
            try:
                raw = json.loads(path.read_text(encoding='utf-8'))
                snap_map = SnapshotMap.model_validate(raw)
            except (OSError, ValueError, ValidationError, TypeError):
                continue
            file_contract = str(raw.get('contract_sig') or '')
            if contract_fingerprint is not None and file_contract != contract_fingerprint:
                continue
            if domain is not None and snap_map.domain != domain:
                continue
            scanned += 1
            domains.add(snap_map.domain)
            contracts.add(file_contract)
            if await self._has_file_metrics(file_contract, snap_map.domain):
                skipped += 1
                continue
            snapshots = dict(snap_map.snapshots)
            await self.upsert_snapshots(
                url=snap_map.url,
                domain=snap_map.domain,
                snapshots=snapshots,
                contract_fingerprint=file_contract,
                route_signature=None,
                selector_level=_DEFAULT_SELECTOR_LEVEL,
                event_type='backfill',
            )
            imported += 1
            fields += len(snapshots)
        return CacheBackfillResult(
            scanned_files=scanned,
            imported_files=imported,
            skipped_files=skipped,
            imported_fields=fields,
            domains=sorted(domains),
            contract_fingerprints=sorted(contracts),
        )

    async def _backfill_contract(self, contract_fingerprint: str) -> None:
        await self.backfill_existing(contract_fingerprint=contract_fingerprint)

    async def _has_field_metrics(self, contract_fingerprint: str) -> bool:
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT 1
            FROM {_CACHE_FIELD_TABLE}
            WHERE contract_fingerprint = :contract_fingerprint
            LIMIT 1
            """,
            {'contract_fingerprint': contract_fingerprint},
        )
        return bool(result.rows)

    async def _has_file_metrics(self, contract_fingerprint: str, domain: str) -> bool:
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT 1
            FROM {_CACHE_FIELD_TABLE}
            WHERE contract_fingerprint = :contract_fingerprint AND domain = :domain
            LIMIT 1
            """,
            {'contract_fingerprint': contract_fingerprint, 'domain': domain},
        )
        return bool(result.rows)

    async def _connect(self) -> Client:
        if self._client is None:
            self._client = create_client(self.database_url, auth_token=self.auth_token)
        return self._client

    async def _record_event_on_executor(
        self,
        executor: Any,
        event_type: str,
        *,
        contract_fingerprint: str | None = None,
        field_name: str | None = None,
        domain: str | None = None,
        top_level_domain: str | None = None,
        route_signature: str | None = None,
        selector_level: str | None = None,
        url: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await executor.execute(
            f"""
            INSERT INTO {_CACHE_EVENT_TABLE} (
                event_type,
                contract_fingerprint,
                field_name,
                domain,
                top_level_domain,
                route_signature,
                selector_level,
                url,
                occurred_at,
                detail_json
            )
            VALUES (
                :event_type,
                :contract_fingerprint,
                :field_name,
                :domain,
                :top_level_domain,
                :route_signature,
                :selector_level,
                :url,
                :occurred_at,
                :detail_json
            )
            """,
            {
                'event_type': event_type,
                'contract_fingerprint': contract_fingerprint,
                'field_name': field_name,
                'domain': domain,
                'top_level_domain': top_level_domain,
                'route_signature': route_signature,
                'selector_level': selector_level,
                'url': url,
                'occurred_at': _iso(datetime.now(timezone.utc)),
                'detail_json': json.dumps(detail or {}, sort_keys=True),
            },
        )

    async def _ensure_migrated(self) -> None:
        if self._migrated:
            await self._connect()
            return
        client = await self._connect()
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_CACHE_FIELD_TABLE} (
                contract_fingerprint TEXT NOT NULL,
                field_name TEXT NOT NULL,
                domain TEXT NOT NULL,
                top_level_domain TEXT NOT NULL DEFAULT '',
                route_signature TEXT NOT NULL,
                selector_level TEXT NOT NULL,
                source_url TEXT,
                status TEXT NOT NULL,
                selector_json TEXT NOT NULL,
                discovered_at TEXT,
                last_verified_at TEXT,
                last_failed_at TEXT,
                failure_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(contract_fingerprint, field_name, domain, route_signature, selector_level)
            )
            """
        )
        await self._ensure_column(client, _CACHE_FIELD_TABLE, 'top_level_domain', "TEXT NOT NULL DEFAULT ''")
        await client.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_cache_field_metrics_contract
            ON {_CACHE_FIELD_TABLE}(contract_fingerprint, domain, route_signature)
            """
        )
        await client.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_cache_field_metrics_tld
            ON {_CACHE_FIELD_TABLE}(top_level_domain, contract_fingerprint, route_signature)
            """
        )
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_CACHE_EVENT_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                contract_fingerprint TEXT,
                field_name TEXT,
                domain TEXT,
                top_level_domain TEXT,
                route_signature TEXT,
                selector_level TEXT,
                url TEXT,
                occurred_at TEXT NOT NULL,
                detail_json TEXT NOT NULL DEFAULT '{{}}'
            )
            """
        )
        await client.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_cache_events_lookup
            ON {_CACHE_EVENT_TABLE}(contract_fingerprint, domain, field_name, occurred_at)
            """
        )
        await self._ensure_column(client, _CACHE_EVENT_TABLE, 'top_level_domain', 'TEXT')
        self._migrated = True

    async def _ensure_column(self, client: Client, table_name: str, column_name: str, definition: str) -> None:
        result = await client.execute(f'PRAGMA table_info({table_name})')
        columns = {row[1] for row in result.rows}
        if column_name not in columns:
            try:
                await client.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}')
            except LibsqlError as exc:
                if 'duplicate column' not in str(exc).lower():
                    raise
