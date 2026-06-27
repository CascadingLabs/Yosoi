"""Async Peewee-backed metrics store for cache status and metrics."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from peewee import AutoField, CompositeKey, IntegerField, Model, SqliteDatabase, TextField

from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot
from yosoi.utils.files import init_yosoi

_DEFAULT_DB_NAME = 'metrics.sqlite3'
_DEFAULT_ROUTE = '/'
_DEFAULT_SELECTOR_LEVEL = 'all'
_CACHE_FIELD_TABLE = 'cache_field_metrics'
_CACHE_EVENT_TABLE = 'cache_events'
_CACHE_FIELD_KEY = ('contract_fingerprint', 'field_name', 'domain', 'route_signature', 'selector_level')
_CACHE_FIELD_UPDATE_COLUMNS = (
    'source_url',
    'status',
    'selector_json',
    'discovered_at',
    'last_verified_at',
    'last_failed_at',
    'failure_count',
    'updated_at',
)


@dataclass(frozen=True)
class CacheFieldMetric:
    """Field-addressable cache metrics record."""

    contract_fingerprint: str
    field_name: str
    domain: str
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
    routes: list[str]
    fields: list[str]
    field_metrics: list[CacheFieldMetric]


def route_signature_for_url(url: str) -> str:
    """Return the first route bucket for a URL: normalized path, query excluded."""
    parsed = urlparse(url)
    path = parsed.path or _DEFAULT_ROUTE
    return path if path.startswith('/') else f'/{path}'


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _snapshot_payload(snapshot: SelectorSnapshot) -> str:
    return json.dumps(snapshot.model_dump(mode='json'), sort_keys=True)


def _metric_from_model(row: Any) -> CacheFieldMetric:
    return CacheFieldMetric(
        contract_fingerprint=row.contract_fingerprint,
        field_name=row.field_name,
        domain=row.domain,
        route_signature=row.route_signature,
        selector_level=row.selector_level,
        source_url=row.source_url,
        status=row.status,
        discovered_at=row.discovered_at,
        last_verified_at=row.last_verified_at,
        last_failed_at=row.last_failed_at,
        failure_count=row.failure_count,
    )


class SQLiteCacheMetricsStore:
    """Small async SQLite metrics store for selector cache status and events."""

    def __init__(self, db_path: str | Path | None = None):
        """Create a metrics store handle; Peewee operations run off the event loop."""
        if db_path is None:
            db_path = init_yosoi().parent / _DEFAULT_DB_NAME
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = SqliteDatabase(self.db_path)
        self._field_model, self._event_model = self._build_models()
        self._migrated = False

    async def upsert_snapshots(
        self,
        *,
        url: str,
        domain: str,
        snapshots: dict[str, SelectorSnapshot],
        contract_fingerprint: str | None,
        route_signature: str | None = None,
        selector_level: str = _DEFAULT_SELECTOR_LEVEL,
    ) -> None:
        """Record a snapshot file as per-field cache metrics."""
        await asyncio.to_thread(
            self._upsert_snapshots_sync,
            url=url,
            domain=domain,
            snapshots=snapshots,
            contract_fingerprint=contract_fingerprint,
            route_signature=route_signature,
            selector_level=selector_level,
        )

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
        await asyncio.to_thread(
            self._record_verdict_sync,
            domain=domain,
            field_name=field_name,
            verdict=verdict,
            contract_fingerprint=contract_fingerprint,
            route_signature=route_signature,
            selector_level=selector_level,
        )

    async def summarize_contract(self, contract_fingerprint: str) -> ContractCacheMetrics:
        """Return all cache metrics for one contract fingerprint."""
        return await asyncio.to_thread(self._summarize_contract_sync, contract_fingerprint)

    async def list_domain_fields(self, domain: str, contract_fingerprint: str | None = None) -> list[CacheFieldMetric]:
        """Return field metrics for a domain, optionally scoped to one contract."""
        return await asyncio.to_thread(self._list_domain_fields_sync, domain, contract_fingerprint)

    async def record_event(
        self,
        event_type: str,
        *,
        contract_fingerprint: str | None = None,
        field_name: str | None = None,
        domain: str | None = None,
        route_signature: str | None = None,
        selector_level: str | None = None,
        url: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Append one cache event."""
        await asyncio.to_thread(
            self._record_event_sync,
            event_type,
            contract_fingerprint=contract_fingerprint,
            field_name=field_name,
            domain=domain,
            route_signature=route_signature,
            selector_level=selector_level,
            url=url,
            detail=detail,
        )

    def _build_models(self) -> tuple[type[Model], type[Model]]:
        class CacheFieldMetricModel(Model):
            contract_fingerprint = TextField()
            field_name = TextField()
            domain = TextField(index=True)
            route_signature = TextField()
            selector_level = TextField()
            source_url = TextField(null=True)
            status = TextField()
            selector_json = TextField()
            discovered_at = TextField(null=True)
            last_verified_at = TextField(null=True)
            last_failed_at = TextField(null=True)
            failure_count = IntegerField(default=0)
            updated_at = TextField()

            class Meta:
                table_name = _CACHE_FIELD_TABLE
                primary_key = CompositeKey(*_CACHE_FIELD_KEY)
                indexes = (
                    (('contract_fingerprint', 'domain', 'route_signature'), False),
                    (('domain', 'contract_fingerprint', 'route_signature'), False),
                )

        class CacheEventModel(Model):
            id = AutoField()
            event_type = TextField()
            contract_fingerprint = TextField(null=True)
            field_name = TextField(null=True)
            domain = TextField(null=True)
            route_signature = TextField(null=True)
            selector_level = TextField(null=True)
            url = TextField(null=True)
            occurred_at = TextField()
            detail_json = TextField(default='{}')

            class Meta:
                table_name = _CACHE_EVENT_TABLE
                indexes = ((('contract_fingerprint', 'domain', 'field_name', 'occurred_at'), False),)

        CacheFieldMetricModel.bind(self._db, bind_refs=False, bind_backrefs=False)
        CacheEventModel.bind(self._db, bind_refs=False, bind_backrefs=False)
        return CacheFieldMetricModel, CacheEventModel

    def _upsert_snapshots_sync(
        self,
        *,
        url: str,
        domain: str,
        snapshots: dict[str, SelectorSnapshot],
        contract_fingerprint: str | None,
        route_signature: str | None,
        selector_level: str,
    ) -> None:
        self._ensure_migrated_sync()
        contract_fp = contract_fingerprint or ''
        route = route_signature or route_signature_for_url(url)
        now = _iso(datetime.now(timezone.utc))

        with self._db.connection_context(), self._db.atomic():
            for field_name, snapshot in snapshots.items():
                metric = {
                    'contract_fingerprint': contract_fp,
                    'field_name': field_name,
                    'domain': domain,
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
                update = {getattr(self._field_model, column): metric[column] for column in _CACHE_FIELD_UPDATE_COLUMNS}
                self._field_model.insert(metric).on_conflict(
                    conflict_target=[getattr(self._field_model, column) for column in _CACHE_FIELD_KEY],
                    update=update,
                ).execute()
                self._record_event_sync(
                    'write',
                    contract_fingerprint=contract_fp,
                    field_name=field_name,
                    domain=domain,
                    route_signature=route,
                    selector_level=selector_level,
                    url=url,
                )

    def _record_verdict_sync(
        self,
        *,
        domain: str,
        field_name: str,
        verdict: CacheVerdict,
        contract_fingerprint: str | None,
        route_signature: str | None,
        selector_level: str | None,
    ) -> None:
        self._ensure_migrated_sync()
        contract_fp = contract_fingerprint or ''
        now = _iso(datetime.now(timezone.utc))
        event_type = 'verify' if verdict == CacheVerdict.FRESH else 'fail'
        conditions = [
            self._field_model.contract_fingerprint == contract_fp,
            self._field_model.domain == domain,
            self._field_model.field_name == field_name,
        ]
        if route_signature is not None:
            conditions.append(self._field_model.route_signature == route_signature)
        if selector_level is not None:
            conditions.append(self._field_model.selector_level == selector_level)

        if verdict == CacheVerdict.FRESH:
            update = {'last_verified_at': now, 'failure_count': 0, 'updated_at': now}
        else:
            update = {
                'last_failed_at': now,
                'failure_count': self._field_model.failure_count + 1,
                'updated_at': now,
            }

        with self._db.connection_context(), self._db.atomic():
            self._field_model.update(update).where(*conditions).execute()
            self._record_event_sync(
                event_type,
                contract_fingerprint=contract_fp,
                field_name=field_name,
                domain=domain,
                route_signature=route_signature,
                selector_level=selector_level,
                detail={'verdict': verdict.value},
            )

    def _summarize_contract_sync(self, contract_fingerprint: str) -> ContractCacheMetrics:
        self._ensure_migrated_sync()
        with self._db.connection_context():
            rows = [
                _metric_from_model(row)
                for row in self._field_model.select()
                .where(self._field_model.contract_fingerprint == contract_fingerprint)
                .order_by(self._field_model.domain, self._field_model.route_signature, self._field_model.field_name)
            ]
        return ContractCacheMetrics(
            contract_fingerprint=contract_fingerprint,
            domains=sorted({row.domain for row in rows}),
            routes=sorted({row.route_signature for row in rows}),
            fields=sorted({row.field_name for row in rows}),
            field_metrics=rows,
        )

    def _list_domain_fields_sync(self, domain: str, contract_fingerprint: str | None) -> list[CacheFieldMetric]:
        self._ensure_migrated_sync()
        conditions = [self._field_model.domain == domain]
        if contract_fingerprint is not None:
            conditions.append(self._field_model.contract_fingerprint == contract_fingerprint)
        with self._db.connection_context():
            return [
                _metric_from_model(row)
                for row in self._field_model.select()
                .where(*conditions)
                .order_by(
                    self._field_model.contract_fingerprint,
                    self._field_model.route_signature,
                    self._field_model.field_name,
                )
            ]

    def _record_event_sync(
        self,
        event_type: str,
        *,
        contract_fingerprint: str | None = None,
        field_name: str | None = None,
        domain: str | None = None,
        route_signature: str | None = None,
        selector_level: str | None = None,
        url: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_migrated_sync()
        self._event_model.create(
            event_type=event_type,
            contract_fingerprint=contract_fingerprint,
            field_name=field_name,
            domain=domain,
            route_signature=route_signature,
            selector_level=selector_level,
            url=url,
            occurred_at=_iso(datetime.now(timezone.utc)),
            detail_json=json.dumps(detail or {}, sort_keys=True),
        )

    def _ensure_migrated_sync(self) -> None:
        if self._migrated:
            return
        with self._db.connection_context():
            self._db.create_tables([self._field_model, self._event_model])
        self._migrated = True
