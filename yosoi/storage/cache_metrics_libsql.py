"""Async libSQL/SQLite local state store for selectors, fields, contracts, and cache events."""

from __future__ import annotations

import json
import types
import typing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from libsql_client import Client

from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot
from yosoi.storage.sqlite_store import YosoiSQLiteStore, default_sqlite_database_url, normalize_database_url
from yosoi.utils.signatures import contract_signature, field_signature

if TYPE_CHECKING:
    from yosoi.models.contract import Contract

_DEFAULT_ROUTE = '/'
_DEFAULT_SELECTOR_LEVEL = 'all'
_FIELD_TABLE = 'field_entities'
_CONTRACT_TABLE = 'contracts'
_CONTRACT_FIELD_TABLE = 'contract_fields'
_SELECTOR_SNAPSHOT_TABLE = 'selector_snapshots'
_CACHE_EVENT_TABLE = 'cache_events'
_SELECTOR_KEY = ('contract_fingerprint', 'field_fingerprint', 'domain', 'selector_level')
_SELECTOR_UPDATE_COLUMNS = (
    'field_path',
    'top_level_domain',
    'route_signature',
    'source_url',
    'status',
    'selector',
    'discovered_at',
    'last_verified_at',
    'last_failed_at',
    'failure_count',
    'updated_at',
)


@dataclass(frozen=True)
class CacheFieldMetric:
    """Current selector-cache row for one contract field on one domain."""

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
    field_fingerprint: str = ''
    field_description: str | None = None


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
    contract_name: str | None = None
    contract_docstring: str | None = None


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
    """No-op compatibility result for the removed JSON-to-SQL backfill path."""

    scanned_files: int = 0
    imported_files: int = 0
    skipped_files: int = 0
    imported_fields: int = 0
    domains: list[str] = field(default_factory=list)
    contract_fingerprints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _FieldEntity:
    fingerprint: str
    field_path: str
    field_name: str
    description: str | None
    yosoi_type: str | None
    python_type: str
    config: dict[str, Any]


def default_metrics_database_url() -> str:
    """Return the default local SQLite/libSQL database URL under `.yosoi`."""
    return default_sqlite_database_url()


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


def _snapshot_from_row(values: dict[str, Any]) -> SelectorSnapshot:
    payload = json.loads(str(values['selector']))
    payload.update(
        {
            'status': values['status'],
            'discovered_at': values['discovered_at'],
            'last_verified_at': values['last_verified_at'],
            'last_failed_at': values['last_failed_at'],
            'failure_count': values['failure_count'],
        }
    )
    return SelectorSnapshot.model_validate(payload)


def _row_dict(columns: tuple[str, ...], row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(columns, row, strict=True))


def _metric_from_row(columns: tuple[str, ...], row: tuple[Any, ...]) -> CacheFieldMetric:
    values = _row_dict(columns, row)
    return CacheFieldMetric(
        contract_fingerprint=values['contract_fingerprint'],
        field_fingerprint=values['field_fingerprint'],
        field_name=values['field_path'],
        field_description=values.get('description'),
        domain=values['domain'],
        top_level_domain=values['top_level_domain'],
        route_signature=values['route_signature'],
        selector_level=values['selector_level'],
        source_url=values['source_url'],
        status=values['status'],
        discovered_at=values['discovered_at'],
        last_verified_at=values['last_verified_at'],
        last_failed_at=values['last_failed_at'],
        failure_count=int(values['failure_count']),
    )


def _upsert_selector_sql() -> str:
    columns = (*_SELECTOR_KEY, *_SELECTOR_UPDATE_COLUMNS)
    column_sql = ', '.join(columns)
    value_sql = ', '.join(f'json(:{column})' if column == 'selector' else f':{column}' for column in columns)
    key_sql = ', '.join(_SELECTOR_KEY)
    update_sql = ', '.join(f'{column}=excluded.{column}' for column in _SELECTOR_UPDATE_COLUMNS)
    return f"""
        INSERT INTO {_SELECTOR_SNAPSHOT_TABLE} ({column_sql})
        VALUES ({value_sql})
        ON CONFLICT({key_sql}) DO UPDATE SET {update_sql}
    """


def _normalize_database_url(raw_url: str | Path) -> str:
    return normalize_database_url(raw_url)


def _annotation_name(annotation: object) -> str:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        union_args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return _annotation_name(union_args[0]) if union_args else 'str'
    if origin is list:
        list_args = typing.get_args(annotation)
        inner = _annotation_name(list_args[0]) if list_args else 'Any'
        return f'list[{inner}]'
    name = getattr(annotation, '__name__', None)
    return str(name or annotation or 'str')


def _jsonable_config(extra: dict[str, Any]) -> dict[str, Any]:
    return cast('dict[str, Any]', json.loads(json.dumps(extra, default=repr)))


def _iter_contract_fields(
    contract: type[Contract], prefix: str = '', descriptions: dict[str, str] | None = None
) -> dict[str, _FieldEntity]:
    from yosoi.models.contract import Contract as _Contract

    if descriptions is None:
        descriptions = contract.field_descriptions()
    result: dict[str, _FieldEntity] = {}
    action_names = set(contract.action_fields())
    for name, field_info in contract.model_fields.items():
        if name in action_names:
            continue
        annotation = field_info.annotation
        field_path = f'{prefix}{name}' if not prefix else f'{prefix}_{name}'
        if isinstance(annotation, type) and issubclass(annotation, _Contract):
            result.update(_iter_contract_fields(annotation, field_path, descriptions))
            continue
        extra = field_info.json_schema_extra if isinstance(field_info.json_schema_extra, dict) else {}
        yosoi_type = extra.get('yosoi_type')
        description = descriptions.get(field_path) or field_info.description or None
        fingerprint = field_signature(field_path, description or '', str(yosoi_type) if yosoi_type else None)
        result[field_path] = _FieldEntity(
            fingerprint=fingerprint,
            field_path=field_path,
            field_name=field_path,
            description=description,
            yosoi_type=str(yosoi_type) if yosoi_type is not None else None,
            python_type=_annotation_name(annotation),
            config=_jsonable_config(extra),
        )
    return result


def _fallback_field(field_path: str) -> _FieldEntity:
    description = 'Selector for the repeating wrapper element' if field_path == 'root' else None
    fingerprint = field_signature(field_path, description or '', None)
    return _FieldEntity(
        fingerprint=fingerprint,
        field_path=field_path,
        field_name=field_path,
        description=description,
        yosoi_type=None,
        python_type='str',
        config={},
    )


class LibSQLCacheMetricsStore(YosoiSQLiteStore):
    """Async SQLite/libSQL store for Yosoi's local selector state and cache events."""

    def __init__(self, database_url: str | Path | None = None, auth_token: str | None = None):
        """Create a store handle.

        Args:
            database_url: libSQL URL. Defaults to `YOSOI_METRICS_DATABASE_URL` or local `.yosoi/yosoi.sqlite3`.
            auth_token: Turso/libSQL auth token. Defaults to `YOSOI_METRICS_AUTH_TOKEN`.
        """
        super().__init__(database_url=database_url, auth_token=auth_token)

    async def upsert_snapshots(
        self,
        *,
        url: str,
        domain: str,
        snapshots: dict[str, SelectorSnapshot],
        contract_fingerprint: str | None,
        contract: type[Contract] | None = None,
        route_signature: str | None = None,
        selector_level: str = _DEFAULT_SELECTOR_LEVEL,
        event_type: str = 'write',
    ) -> None:
        """Record current per-field selector snapshots and append cache events."""
        await self._ensure_migrated()
        client = await self._connect()
        contract_fp = contract_fingerprint or (contract_signature(contract) if contract is not None else '')
        route = route_signature or route_signature_for_url(url)
        tld = top_level_domain_for_domain(domain)
        now = _iso(datetime.now(timezone.utc))
        fields = _iter_contract_fields(contract) if contract is not None else {}
        for field_path in snapshots:
            fields.setdefault(field_path, _fallback_field(field_path))

        tx = client.transaction()
        try:
            await self._upsert_contract_on_executor(tx, contract_fp, contract, now)
            for ordinal, field_entity in enumerate(fields.values()):
                await self._upsert_field_on_executor(tx, field_entity, now)
                await self._upsert_contract_field_on_executor(tx, contract_fp, field_entity, ordinal)

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
            for field_path, snapshot in snapshots.items():
                field_entity = fields[field_path]
                metric = {
                    'contract_fingerprint': contract_fp,
                    'field_path': field_path,
                    'field_fingerprint': field_entity.fingerprint,
                    'domain': domain,
                    'top_level_domain': tld,
                    'route_signature': route,
                    'selector_level': selector_level,
                    'source_url': url,
                    'status': snapshot.status.value,
                    'selector': _snapshot_payload(snapshot),
                    'discovered_at': _iso(snapshot.discovered_at),
                    'last_verified_at': _iso(snapshot.last_verified_at),
                    'last_failed_at': _iso(snapshot.last_failed_at),
                    'failure_count': snapshot.failure_count,
                    'updated_at': now,
                }
                await tx.execute(_upsert_selector_sql(), metric)
                await self._record_event_on_executor(
                    tx,
                    event_type,
                    contract_fingerprint=contract_fp,
                    field_fingerprint=field_entity.fingerprint,
                    field_name=field_path,
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

    async def load_snapshots(
        self, domain: str, contract_fingerprint: str | None = None, selector_level: str = _DEFAULT_SELECTOR_LEVEL
    ) -> dict[str, SelectorSnapshot] | None:
        """Load current selector snapshots for a domain and contract fingerprint."""
        await self._ensure_migrated()
        contract_fp = contract_fingerprint or ''
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT field_path, json(selector) AS selector, status, discovered_at, last_verified_at, last_failed_at, failure_count
            FROM {_SELECTOR_SNAPSHOT_TABLE}
            WHERE domain = :domain
              AND contract_fingerprint = :contract_fingerprint
              AND selector_level = :selector_level
            ORDER BY field_path
            """,
            {'domain': domain, 'contract_fingerprint': contract_fp, 'selector_level': selector_level},
        )
        if not result.rows:
            return None
        snapshots: dict[str, SelectorSnapshot] = {}
        for row in result.rows:
            values = _row_dict(result.columns, row)
            snapshots[str(values['field_path'])] = _snapshot_from_row(values)
        return snapshots

    async def selector_exists(self, domain: str, contract_fingerprint: str | None = None) -> bool:
        """Return whether current selector snapshots exist for a domain/contract."""
        await self._ensure_migrated()
        contract_fp = contract_fingerprint or ''
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT 1
            FROM {_SELECTOR_SNAPSHOT_TABLE}
            WHERE domain = :domain AND contract_fingerprint = :contract_fingerprint
            LIMIT 1
            """,
            {'domain': domain, 'contract_fingerprint': contract_fp},
        )
        return bool(result.rows)

    async def list_domains(self) -> list[str]:
        """List domains with current selector snapshots."""
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT DISTINCT domain
            FROM {_SELECTOR_SNAPSHOT_TABLE}
            ORDER BY domain
            """
        )
        return [str(row[0]) for row in result.rows]

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
                field_fp = await self._field_fingerprint_for_path(tx, contract_fp, field_name)
                await self._record_event_on_executor(
                    tx,
                    'hit',
                    contract_fingerprint=contract_fp,
                    field_fingerprint=field_fp,
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
        """Record a per-field verification result in the local state store."""
        await self._ensure_migrated()
        client = await self._connect()
        contract_fp = contract_fingerprint or ''
        now = _iso(datetime.now(timezone.utc))
        event_type = 'verify' if verdict == CacheVerdict.FRESH else 'fail'
        level_condition = 'AND selector_level = :selector_level' if selector_level is not None else ''
        params: dict[str, Any] = {
            'contract_fingerprint': contract_fp,
            'domain': domain,
            'field_path': field_name,
            'field_fingerprint': await self._field_fingerprint_for_path(client, contract_fp, field_name),
        }
        if selector_level is not None:
            params['selector_level'] = selector_level

        tx = client.transaction()
        try:
            result = await tx.execute(
                f"""
                SELECT field_fingerprint, selector_level, json(selector) AS selector, status, discovered_at,
                       last_verified_at, last_failed_at, failure_count
                FROM {_SELECTOR_SNAPSHOT_TABLE}
                WHERE contract_fingerprint = :contract_fingerprint
                  AND domain = :domain
                  AND field_fingerprint = :field_fingerprint
                  {level_condition}
                """,
                params,
            )
            for row in result.rows:
                values = _row_dict(result.columns, row)
                snap = _snapshot_from_row(values)
                if verdict == CacheVerdict.FRESH:
                    snap.last_verified_at = datetime.now(timezone.utc)
                    snap.failure_count = 0
                else:
                    snap.last_failed_at = datetime.now(timezone.utc)
                    snap.failure_count += 1
                await tx.execute(
                    f"""
                    UPDATE {_SELECTOR_SNAPSHOT_TABLE}
                    SET selector = json(:selector),
                        last_verified_at = :last_verified_at,
                        last_failed_at = :last_failed_at,
                        failure_count = :failure_count,
                        updated_at = :updated_at,
                        route_signature = COALESCE(:route_signature, route_signature)
                    WHERE contract_fingerprint = :contract_fingerprint
                      AND domain = :domain
                      AND field_fingerprint = :field_fingerprint
                      AND selector_level = :selector_level
                    """,
                    {
                        'selector': _snapshot_payload(snap),
                        'last_verified_at': _iso(snap.last_verified_at),
                        'last_failed_at': _iso(snap.last_failed_at),
                        'failure_count': snap.failure_count,
                        'updated_at': now,
                        'route_signature': route_signature,
                        'contract_fingerprint': contract_fp,
                        'domain': domain,
                        'field_path': field_name,
                        'field_fingerprint': values['field_fingerprint'],
                        'selector_level': values['selector_level'],
                    },
                )
                await self._record_event_on_executor(
                    tx,
                    event_type,
                    contract_fingerprint=contract_fp,
                    field_fingerprint=values['field_fingerprint'],
                    field_name=field_name,
                    domain=domain,
                    top_level_domain=top_level_domain_for_domain(domain),
                    route_signature=route_signature,
                    selector_level=values['selector_level'],
                    detail={'verdict': verdict.value},
                )
            await tx.commit()
        except BaseException:
            await tx.rollback()
            raise

    async def summarize_contract(self, contract_fingerprint: str) -> ContractCacheMetrics:
        """Return all current cache metrics for one contract fingerprint."""
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(
            self._metric_select_sql('WHERE s.contract_fingerprint = :contract_fingerprint', 's.domain, s.field_path'),
            {'contract_fingerprint': contract_fingerprint},
        )
        rows = [_metric_from_row(result.columns, row) for row in result.rows]
        event_counts, event_urls, event_routes = await self._event_summary(contract_fingerprint=contract_fingerprint)
        field_urls = {row.source_url for row in rows if row.source_url}
        contract_row = await self._contract_row(contract_fingerprint)
        return ContractCacheMetrics(
            contract_fingerprint=contract_fingerprint,
            contract_name=contract_row.get('name') if contract_row else None,
            contract_docstring=contract_row.get('docstring') if contract_row else None,
            domains=sorted({row.domain for row in rows}),
            top_level_domains=sorted({row.top_level_domain for row in rows}),
            routes=sorted(({row.route_signature for row in rows if row.route_signature}) | event_routes),
            fields=sorted({row.field_name for row in rows}),
            field_metrics=rows,
            event_counts=event_counts,
            run_count=event_counts.get('run', 0),
            url_count=len(field_urls | event_urls),
        )

    async def summarize_domain(self, domain: str, contract_fingerprint: str | None = None) -> DomainCacheMetrics:
        """Return all current cache metrics for one domain, optionally scoped to one contract."""
        await self._ensure_migrated()
        rows = await self.list_domain_fields(domain, contract_fingerprint)
        event_counts, event_urls, event_routes = await self._event_summary(
            domain=domain, contract_fingerprint=contract_fingerprint
        )
        field_urls = {row.source_url for row in rows if row.source_url}
        return DomainCacheMetrics(
            domain=domain,
            contract_fingerprints=sorted({row.contract_fingerprint for row in rows}),
            top_level_domains=sorted({row.top_level_domain for row in rows}),
            routes=sorted(({row.route_signature for row in rows if row.route_signature}) | event_routes),
            fields=sorted({row.field_name for row in rows}),
            field_metrics=rows,
            event_counts=event_counts,
            run_count=event_counts.get('run', 0),
            url_count=len(field_urls | event_urls),
        )

    async def list_domain_fields(
        self, domain: str, contract_fingerprint: str | None = None, *, backfill: bool = False
    ) -> list[CacheFieldMetric]:
        """Return current field metrics for a domain, optionally scoped to one contract."""
        del backfill  # JSON backfill has intentionally been removed.
        await self._ensure_migrated()
        conditions = ['s.domain = :domain']
        params: dict[str, Any] = {'domain': domain}
        if contract_fingerprint is not None:
            conditions.append('s.contract_fingerprint = :contract_fingerprint')
            params['contract_fingerprint'] = contract_fingerprint
        client = await self._connect()
        result = await client.execute(
            self._metric_select_sql(f'WHERE {" AND ".join(conditions)}', 's.contract_fingerprint, s.field_path'),
            params,
        )
        return [_metric_from_row(result.columns, row) for row in result.rows]

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
        field_fp = None
        if contract_fingerprint is not None and field_name is not None:
            field_fp = await self._field_fingerprint_for_path(client, contract_fingerprint, field_name)
        await self._record_event_on_executor(
            client,
            event_type,
            contract_fingerprint=contract_fingerprint,
            field_fingerprint=field_fp,
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
        """Return a no-op result; JSON selector-cache backfill was intentionally removed."""
        await self._ensure_migrated()
        return CacheBackfillResult(
            domains=[domain] if domain else [],
            contract_fingerprints=[contract_fingerprint] if contract_fingerprint else [],
        )

    async def _upsert_contract_on_executor(
        self, executor: Any, contract_fp: str, contract: type[Contract] | None, now: str | None
    ) -> None:
        name = contract.__name__ if contract is not None else None
        docstring = contract.__doc__ if contract is not None else None
        spec = contract.to_spec().model_dump_json() if contract is not None else None
        await executor.execute(
            f"""
            INSERT INTO {_CONTRACT_TABLE} (
                contract_fingerprint, name, docstring, spec, created_at, updated_at
            )
            VALUES (:contract_fingerprint, :name, :docstring, json(:spec), :created_at, :updated_at)
            ON CONFLICT(contract_fingerprint) DO UPDATE SET
                name = COALESCE(excluded.name, name),
                docstring = COALESCE(excluded.docstring, docstring),
                spec = COALESCE(excluded.spec, spec),
                updated_at = excluded.updated_at
            """,
            {
                'contract_fingerprint': contract_fp,
                'name': name,
                'docstring': docstring,
                'spec': spec,
                'created_at': now,
                'updated_at': now,
            },
        )

    async def _upsert_field_on_executor(self, executor: Any, entity: _FieldEntity, now: str | None) -> None:
        await executor.execute(
            f"""
            INSERT INTO {_FIELD_TABLE} (
                field_fingerprint, field_name, description, yosoi_type, python_type, config, created_at, updated_at
            )
            VALUES (
                :field_fingerprint, :field_name, :description, :yosoi_type, :python_type,
                json(:config), :created_at, :updated_at
            )
            ON CONFLICT(field_fingerprint) DO UPDATE SET
                field_name = excluded.field_name,
                description = excluded.description,
                yosoi_type = excluded.yosoi_type,
                python_type = excluded.python_type,
                config = excluded.config,
                updated_at = excluded.updated_at
            """,
            {
                'field_fingerprint': entity.fingerprint,
                'field_name': entity.field_name,
                'description': entity.description,
                'yosoi_type': entity.yosoi_type,
                'python_type': entity.python_type,
                'config': json.dumps(entity.config, sort_keys=True),
                'created_at': now,
                'updated_at': now,
            },
        )

    async def _upsert_contract_field_on_executor(
        self, executor: Any, contract_fp: str, entity: _FieldEntity, ordinal: int
    ) -> None:
        await executor.execute(
            f"""
            INSERT INTO {_CONTRACT_FIELD_TABLE} (
                contract_fingerprint, field_fingerprint, field_path, ordinal
            )
            VALUES (:contract_fingerprint, :field_fingerprint, :field_path, :ordinal)
            ON CONFLICT(contract_fingerprint, field_path) DO UPDATE SET
                field_fingerprint = excluded.field_fingerprint,
                ordinal = excluded.ordinal
            """,
            {
                'contract_fingerprint': contract_fp,
                'field_fingerprint': entity.fingerprint,
                'field_path': entity.field_path,
                'ordinal': ordinal,
            },
        )

    async def _field_fingerprint_for_path(self, executor: Any, contract_fp: str, field_path: str) -> str:
        result = await executor.execute(
            f"""
            SELECT field_fingerprint
            FROM {_CONTRACT_FIELD_TABLE}
            WHERE contract_fingerprint = :contract_fingerprint AND field_path = :field_path
            LIMIT 1
            """,
            {'contract_fingerprint': contract_fp, 'field_path': field_path},
        )
        if result.rows:
            return str(result.rows[0][0])
        return field_signature(field_path, '', None)

    def _metric_select_sql(self, where_sql: str, order_sql: str) -> str:
        return f"""
            SELECT
                s.contract_fingerprint,
                s.field_fingerprint,
                s.field_path,
                f.description,
                s.domain,
                s.top_level_domain,
                s.route_signature,
                s.selector_level,
                s.source_url,
                s.status,
                s.discovered_at,
                s.last_verified_at,
                s.last_failed_at,
                s.failure_count
            FROM {_SELECTOR_SNAPSHOT_TABLE} AS s
            LEFT JOIN {_FIELD_TABLE} AS f ON f.field_fingerprint = s.field_fingerprint
            {where_sql}
            ORDER BY {order_sql}
        """

    async def _contract_row(self, contract_fingerprint: str) -> dict[str, Any] | None:
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT contract_fingerprint, name, docstring, json(spec) AS spec
            FROM {_CONTRACT_TABLE}
            WHERE contract_fingerprint = :contract_fingerprint
            LIMIT 1
            """,
            {'contract_fingerprint': contract_fingerprint},
        )
        if not result.rows:
            return None
        return _row_dict(result.columns, result.rows[0])

    async def _event_summary(
        self, *, domain: str | None = None, contract_fingerprint: str | None = None
    ) -> tuple[dict[str, int], set[str], set[str]]:
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
        route_result = await client.execute(
            f"""
            SELECT DISTINCT route_signature
            FROM {_CACHE_EVENT_TABLE}
            {where + ' AND' if where else 'WHERE'} route_signature IS NOT NULL
            """,
            params,
        )
        return (
            counts,
            {str(row[0]) for row in url_result.rows if row[0]},
            {str(row[0]) for row in route_result.rows if row[0]},
        )

    async def _record_event_on_executor(
        self,
        executor: Any,
        event_type: str,
        *,
        contract_fingerprint: str | None = None,
        field_fingerprint: str | None = None,
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
                field_fingerprint,
                field_name,
                domain,
                top_level_domain,
                route_signature,
                selector_level,
                url,
                occurred_at,
                detail
            )
            VALUES (
                :event_type,
                :contract_fingerprint,
                :field_fingerprint,
                :field_name,
                :domain,
                :top_level_domain,
                :route_signature,
                :selector_level,
                :url,
                :occurred_at,
                json(:detail)
            )
            """,
            {
                'event_type': event_type,
                'contract_fingerprint': contract_fingerprint,
                'field_fingerprint': field_fingerprint,
                'field_name': field_name,
                'domain': domain,
                'top_level_domain': top_level_domain,
                'route_signature': route_signature,
                'selector_level': selector_level,
                'url': url,
                'occurred_at': _iso(datetime.now(timezone.utc)),
                'detail': json.dumps(detail or {}, sort_keys=True),
            },
        )

    async def _ensure_migrated(self) -> None:
        if self._migrated:
            await self._connect()
            return
        client = await self._connect()
        await self._reset_incompatible_schema(client)
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_FIELD_TABLE} (
                field_fingerprint TEXT PRIMARY KEY,
                field_name TEXT NOT NULL,
                description TEXT,
                yosoi_type TEXT,
                python_type TEXT NOT NULL DEFAULT 'str',
                config JSON NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_CONTRACT_TABLE} (
                contract_fingerprint TEXT PRIMARY KEY,
                name TEXT,
                docstring TEXT,
                spec JSON,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_CONTRACT_FIELD_TABLE} (
                contract_fingerprint TEXT NOT NULL,
                field_fingerprint TEXT NOT NULL,
                field_path TEXT NOT NULL,
                ordinal INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(contract_fingerprint, field_path),
                FOREIGN KEY(contract_fingerprint) REFERENCES {_CONTRACT_TABLE}(contract_fingerprint),
                FOREIGN KEY(field_fingerprint) REFERENCES {_FIELD_TABLE}(field_fingerprint)
            )
            """
        )
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_SELECTOR_SNAPSHOT_TABLE} (
                contract_fingerprint TEXT NOT NULL,
                field_fingerprint TEXT NOT NULL,
                field_path TEXT NOT NULL,
                domain TEXT NOT NULL,
                top_level_domain TEXT NOT NULL DEFAULT '',
                route_signature TEXT NOT NULL,
                selector_level TEXT NOT NULL,
                source_url TEXT,
                status TEXT NOT NULL,
                selector JSON NOT NULL,
                discovered_at TEXT,
                last_verified_at TEXT,
                last_failed_at TEXT,
                failure_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(contract_fingerprint, field_fingerprint, domain, selector_level),
                FOREIGN KEY(contract_fingerprint) REFERENCES {_CONTRACT_TABLE}(contract_fingerprint),
                FOREIGN KEY(field_fingerprint) REFERENCES {_FIELD_TABLE}(field_fingerprint)
            )
            """
        )
        await client.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_selector_snapshots_contract
            ON {_SELECTOR_SNAPSHOT_TABLE}(contract_fingerprint, domain)
            """
        )
        await client.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_selector_snapshots_tld
            ON {_SELECTOR_SNAPSHOT_TABLE}(top_level_domain, contract_fingerprint)
            """
        )
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_CACHE_EVENT_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                contract_fingerprint TEXT,
                field_fingerprint TEXT,
                field_name TEXT,
                domain TEXT,
                top_level_domain TEXT,
                route_signature TEXT,
                selector_level TEXT,
                url TEXT,
                occurred_at TEXT NOT NULL,
                detail JSON NOT NULL
            )
            """
        )
        await client.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_cache_events_lookup
            ON {_CACHE_EVENT_TABLE}(contract_fingerprint, domain, field_name, occurred_at)
            """
        )
        self._migrated = True

    async def _reset_incompatible_schema(self, client: Client) -> None:
        """Destructively reset old alpha schemas; no migration/backfill is attempted."""
        if not await self._schema_needs_reset(client):
            return
        for table_name in (
            _CACHE_EVENT_TABLE,
            _SELECTOR_SNAPSHOT_TABLE,
            _CONTRACT_FIELD_TABLE,
            _CONTRACT_TABLE,
            _FIELD_TABLE,
        ):
            await client.execute(f'DROP TABLE IF EXISTS {table_name}')

    async def _schema_needs_reset(self, client: Client) -> bool:
        expected_json = {
            _FIELD_TABLE: ('config',),
            _CONTRACT_TABLE: ('spec',),
            _SELECTOR_SNAPSHOT_TABLE: ('selector',),
            _CACHE_EVENT_TABLE: ('detail',),
        }
        removed_columns = {
            _FIELD_TABLE: {'config_json'},
            _CONTRACT_TABLE: {'schema_version', 'spec_json'},
            _SELECTOR_SNAPSHOT_TABLE: {'selector_json'},
            _CACHE_EVENT_TABLE: {'detail_json'},
        }
        for table_name, json_columns in expected_json.items():
            result = await client.execute(f'PRAGMA table_info({table_name})')
            if not result.rows:
                continue
            columns = {str(row[1]): str(row[2]).upper() for row in result.rows}
            if removed_columns.get(table_name, set()) & columns.keys():
                return True
            if any(columns.get(column_name) != 'JSON' for column_name in json_columns):
                return True
            if table_name == _SELECTOR_SNAPSHOT_TABLE:
                pk = [
                    str(row[1])
                    for row in sorted((row for row in result.rows if int(row[5] or 0) > 0), key=lambda r: r[5])
                ]
                if pk != ['contract_fingerprint', 'field_fingerprint', 'domain', 'selector_level']:
                    return True
        return False
