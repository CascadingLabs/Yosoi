"""Scoped A3Node storage — DOM stability recipes in Yosoi SQLite.

After DOMLoader finishes driving a page to a fully-loaded state, the sequence
of actions that succeeded is persisted as a "stability recipe". On the next
visit to the same *scope* the recipe is replayed directly, skipping probe work.

A scope is stricter than a bare domain. The replay key is a deterministic
fingerprint of the domain, URL page profile (path + query-key shape), browser
profile/tier, and replay intent. DOM/page fingerprints are only available after
navigation, but A3Node must choose whether to replay before capture; this module
therefore stores a pre-navigation scope fingerprint for SQLite identity.

Storage location: `.yosoi/yosoi.sqlite3`, table `a3nodes`.

Schema shape::

    scope_key TEXT PRIMARY KEY
    domain TEXT
    page_profile TEXT
    intent TEXT
    browser_fingerprint TEXT
    route_signature TEXT
    query_signature TEXT
    format INTEGER
    acts JSON
    discovered_at TEXT
    replay_count INTEGER
    last_replayed_at TEXT
    updated_at TEXT

``acts`` is readable SQLite JSON text: an ordered list of
:class:`ActRecord` objects. An empty ``acts`` list means the scope was probed
but needed no action. ``replay_count`` tracks how often the stored recipe was
used successfully.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from yosoi.models.selectors import SelectorEntry
from yosoi.storage.sqlite_store import YosoiSQLiteStore

logger = logging.getLogger(__name__)

# On-disk recipe format. 1 = {kind, cycles} only; 2 = adds a concrete `target` per act
# so replay skips the discovery catalogues. A file with no `format` key is format 1.
_A3NODE_FORMAT = 2
_A3NODE_TABLE = 'a3nodes'
_A3FRAGMENT_TABLE = 'a3fragments'
_A3NODE_SCOPE_SCHEMA = 'a3scope:v1'
_A3FRAGMENT_SCHEMA = 'a3fragment:v1'
A3_FRAGMENT_BANK_KINDS = frozenset({'cookie', 'popup', 'age_gate'})
_LEGACY_PAGE_PROFILE = 'legacy-domain'
_DEFAULT_ROUTE = '/'


def _acts_shape(acts: list[dict[str, Any]]) -> list[tuple[object, object]]:
    """Recipe identity for stat preservation: the (kind, cycles) sequence only.

    Adding or refining a concrete ``target`` on an otherwise-identical recipe must NOT
    reset ``replay_count`` — that is what makes the format-1 -> format-2 upgrade
    non-destructive for battle-tested domains.
    """
    return [(a.get('kind'), a.get('cycles')) for a in acts]


def _canonical_json(value: Any) -> str:
    """Return stable compact JSON for hashing scope payloads."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _scope_fingerprint(payload: dict[str, object]) -> str:
    """Return a versioned SQLite-safe fingerprint for an A3Node scope payload."""
    digest = hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()[:32]
    return f'{_A3NODE_SCOPE_SCHEMA}:{digest}'


def _target_signature(kind: str, target: SelectorEntry) -> str:
    """Return the domain-free structural identity for one replayable target."""
    payload: dict[str, object] = {
        'schema': _A3FRAGMENT_SCHEMA,
        'kind': kind,
        'target': target.model_dump(mode='json', exclude_none=True),
    }
    digest = hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()[:32]
    return f'{_A3FRAGMENT_SCHEMA}:{digest}'


def _route_signature_for_url(url: str) -> str:
    """Return the normalized path bucket used in A3Node page profiles."""
    parsed = urlparse(url)
    path = parsed.path or _DEFAULT_ROUTE
    return path if path.startswith('/') else f'/{path}'


def _query_signature_for_url(url: str) -> str:
    """Return a query-key shape that ignores values but splits different key sets."""
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if not pairs:
        return ''
    counts = Counter(key for key, _value in pairs if key)
    return '&'.join(f'{key}[]' if count > 1 else key for key, count in sorted(counts.items()))


@dataclass(frozen=True)
class A3NodeScope:
    """Stable pre-navigation identity for an A3Node recipe.

    The ``scope_key`` is a fingerprint of the other fields and is the SQLite primary
    key. It intentionally uses URL shape and replay intent rather than post-fetch DOM
    fingerprints because replay has to be selected before the DOM is captured.
    """

    scope_key: str
    domain: str
    page_profile: str
    intent: str
    browser_fingerprint: str
    route_signature: str = ''
    query_signature: str = ''
    schema: str = _A3NODE_SCOPE_SCHEMA

    @classmethod
    def for_url(
        cls,
        url: str,
        *,
        domain: str,
        intent: str = 'fetch',
        browser_fingerprint: str = 'default',
    ) -> A3NodeScope:
        """Build a scoped recipe key from URL shape, replay intent, and browser identity."""
        route = _route_signature_for_url(url)
        query = _query_signature_for_url(url)
        page_profile = f'{route}?{query}' if query else route
        payload: dict[str, object] = {
            'schema': _A3NODE_SCOPE_SCHEMA,
            'domain': domain,
            'route_signature': route,
            'query_signature': query,
            'page_profile': page_profile,
            'intent': intent or 'fetch',
            'browser_fingerprint': browser_fingerprint or 'default',
        }
        return cls(
            scope_key=_scope_fingerprint(payload),
            domain=domain,
            page_profile=page_profile,
            intent=str(payload['intent']),
            browser_fingerprint=str(payload['browser_fingerprint']),
            route_signature=route,
            query_signature=query,
        )

    @classmethod
    def legacy_domain(cls, domain: str) -> A3NodeScope:
        """Represent a pre-CAS-166 domain-only recipe without making it broadly reusable."""
        return cls(
            scope_key=domain,
            domain=domain,
            page_profile=_LEGACY_PAGE_PROFILE,
            intent=_LEGACY_PAGE_PROFILE,
            browser_fingerprint=_LEGACY_PAGE_PROFILE,
        )


def _coerce_scope(scope: A3NodeScope | str) -> A3NodeScope:
    """Coerce legacy string callers into an inert domain-only scope."""
    if isinstance(scope, A3NodeScope):
        return scope
    if scope.startswith(f'{_A3NODE_SCOPE_SCHEMA}:'):
        return A3NodeScope(
            scope_key=scope,
            domain='',
            page_profile='unknown',
            intent='unknown',
            browser_fingerprint='unknown',
        )
    return A3NodeScope.legacy_domain(scope)


@dataclass
class ActRecord:
    """A single recorded action from a DOMLoader run.

    Attributes:
        kind: TriggerKind value string (e.g. 'load_more', 'cookie', 'infinite_scroll').
        cycles: How many times the action was repeated before the trigger was exhausted.

    """

    kind: str
    cycles: int
    target: SelectorEntry | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialise to a plain dict for JSON storage."""
        d: dict[str, object] = {'kind': self.kind, 'cycles': self.cycles}
        if self.target is not None:
            d['target'] = self.target.model_dump(exclude_none=True)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActRecord:
        """Deserialise from a plain dict (tolerates format-1 records with no target)."""
        raw_target = d.get('target')
        target = SelectorEntry.model_validate(raw_target) if raw_target else None
        return cls(kind=str(d['kind']), cycles=int(d['cycles']), target=target)


@dataclass(frozen=True)
class A3Fragment:
    """Domain-free reusable A3 action fragment keyed by structural target."""

    fragment_key: str
    kind: str
    target: SelectorEntry
    source_domain: str
    evidence_count: int = 1
    replay_count: int = 0
    created_at: str = ''
    updated_at: str = ''
    last_replayed_at: str | None = None

    @classmethod
    def from_act(cls, scope: A3NodeScope, act: ActRecord, *, now: str) -> A3Fragment | None:
        """Mint a reusable fragment from a scoped act when it has a durable target."""
        if act.kind not in A3_FRAGMENT_BANK_KINDS or act.target is None:
            return None
        return cls(
            fragment_key=_target_signature(act.kind, act.target),
            kind=act.kind,
            target=act.target,
            source_domain=scope.domain,
            created_at=now,
            updated_at=now,
        )

    def to_act(self) -> ActRecord:
        """Return a one-cycle act suitable for direct replay before scoped probing."""
        return ActRecord(kind=self.kind, cycles=1, target=self.target)


class A3NodeStorage(YosoiSQLiteStore):
    """Saves and loads scoped DOM stability recipes from Yosoi SQLite."""

    def __init__(
        self,
        storage_dir: str | Path | None = None,
        *,
        database_url: str | Path | None = None,
        auth_token: str | None = None,
    ) -> None:
        """Initialise storage.

        ``storage_dir`` is accepted for source compatibility with the old JSON-file
        implementation but is intentionally ignored: A3Nodes now live in SQLite.
        """
        del storage_dir
        super().__init__(database_url=database_url, auth_token=auth_token)

    async def save(self, scope: A3NodeScope | str, acts: list[ActRecord]) -> None:
        """Persist the stability recipe for *scope*.

        Passing a string keeps source compatibility and writes an inert legacy
        domain-only row. New browser callers pass :class:`A3NodeScope` so unrelated
        paths/intents/profiles cannot overwrite each other.
        """
        await self._ensure_migrated()
        client = await self._connect()
        now = datetime.now().isoformat()
        resolved = _coerce_scope(scope)

        existing = await self._load_raw_by_scope_key(resolved.scope_key)
        existing_acts = existing.get('acts', []) if existing else []
        new_acts_dicts = [a.to_dict() for a in acts]
        same = _acts_shape(existing_acts) == _acts_shape(new_acts_dicts)

        params: dict[str, object] = {
            'scope_key': resolved.scope_key,
            'domain': resolved.domain,
            'page_profile': resolved.page_profile,
            'intent': resolved.intent,
            'browser_fingerprint': resolved.browser_fingerprint,
            'route_signature': resolved.route_signature,
            'query_signature': resolved.query_signature,
            'format': _A3NODE_FORMAT,
            'acts': json.dumps(new_acts_dicts, sort_keys=True),
            'discovered_at': existing.get('discovered_at', now) if existing else now,
            'replay_count': existing.get('replay_count', 0) if (existing and same) else 0,
            'last_replayed_at': existing.get('last_replayed_at') if existing else None,
            'updated_at': now,
        }
        try:
            await client.execute(
                f"""
                INSERT INTO {_A3NODE_TABLE} (
                    scope_key, domain, page_profile, intent, browser_fingerprint,
                    route_signature, query_signature, format, acts, discovered_at,
                    replay_count, last_replayed_at, updated_at
                )
                VALUES (
                    :scope_key, :domain, :page_profile, :intent, :browser_fingerprint,
                    :route_signature, :query_signature, :format, json(:acts), :discovered_at,
                    :replay_count, :last_replayed_at, :updated_at
                )
                ON CONFLICT(scope_key) DO UPDATE SET
                    domain = excluded.domain,
                    page_profile = excluded.page_profile,
                    intent = excluded.intent,
                    browser_fingerprint = excluded.browser_fingerprint,
                    route_signature = excluded.route_signature,
                    query_signature = excluded.query_signature,
                    format = excluded.format,
                    acts = excluded.acts,
                    discovered_at = excluded.discovered_at,
                    replay_count = excluded.replay_count,
                    last_replayed_at = excluded.last_replayed_at,
                    updated_at = excluded.updated_at
                """,
                params,
            )
            logger.debug('Saved A3Node for %s scope=%s (%d acts)', resolved.domain, resolved.scope_key, len(acts))
        except sqlite3.Error as e:
            logger.warning('Could not save A3Node for %s scope=%s: %s', resolved.domain, resolved.scope_key, e)

    async def load(self, scope: A3NodeScope | str) -> A3Node | None:
        """Return the stored A3Node for *scope*, or None if not found."""
        resolved = _coerce_scope(scope)
        raw = await self._load_raw_by_scope_key(resolved.scope_key)
        if raw is None:
            return None
        return self._node_from_raw(raw, resolved.scope_key)

    async def record_replay(self, scope: A3NodeScope | str) -> None:
        """Increment replay count and update ``last_replayed_at`` after successful replay."""
        await self._ensure_migrated()
        client = await self._connect()
        resolved = _coerce_scope(scope)
        now = datetime.now().isoformat()
        await client.execute(
            f"""
            UPDATE {_A3NODE_TABLE}
            SET replay_count = replay_count + 1,
                last_replayed_at = :last_replayed_at,
                updated_at = :updated_at
            WHERE scope_key = :scope_key
            """,
            {
                'scope_key': resolved.scope_key,
                'last_replayed_at': now,
                'updated_at': now,
            },
        )

    async def delete(self, scope: A3NodeScope | str) -> bool:
        """Delete the stored A3Node for *scope*."""
        await self._ensure_migrated()
        resolved = _coerce_scope(scope)
        if await self._load_raw_by_scope_key(resolved.scope_key) is None:
            return False
        client = await self._connect()
        await client.execute(
            f'DELETE FROM {_A3NODE_TABLE} WHERE scope_key = :scope_key', {'scope_key': resolved.scope_key}
        )
        logger.debug('Deleted A3Node for %s scope=%s', resolved.domain, resolved.scope_key)
        return True

    async def list_domains(self) -> list[str]:
        """Return all domains with a stored A3Node, sorted alphabetically."""
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(f'SELECT DISTINCT domain FROM {_A3NODE_TABLE} ORDER BY domain')
        return [str(row[0]) for row in result.rows if row[0]]

    async def list_scope_keys(self) -> list[str]:
        """Return all stored A3Node scope fingerprints, sorted for deterministic callers."""
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(f'SELECT scope_key FROM {_A3NODE_TABLE} ORDER BY domain, page_profile, intent')
        return [str(row[0]) for row in result.rows]

    async def load_all(self) -> dict[str, A3Node]:
        """Load every stored A3Node into a scope-key → A3Node mapping."""
        result: dict[str, A3Node] = {}
        for scope_key in await self.list_scope_keys():
            raw = await self._load_raw_by_scope_key(scope_key)
            if raw is None:
                continue
            node = self._node_from_raw(raw, scope_key)
            if node is not None:
                result[scope_key] = node
        return result

    async def save_fragments_from_acts(self, scope: A3NodeScope | str, acts: list[ActRecord]) -> list[A3Fragment]:
        """Mint or refresh reusable domain-free fragments from successful scoped acts."""
        await self._ensure_migrated()
        resolved = _coerce_scope(scope)
        now = datetime.now().isoformat()
        fragments = [fragment for act in acts if (fragment := A3Fragment.from_act(resolved, act, now=now)) is not None]
        if not fragments:
            return []
        client = await self._connect()
        for fragment in fragments:
            params: dict[str, object] = {
                'fragment_key': fragment.fragment_key,
                'kind': fragment.kind,
                'target_signature': fragment.fragment_key,
                'target': json.dumps(fragment.target.model_dump(mode='json', exclude_none=True), sort_keys=True),
                'source_domain': fragment.source_domain,
                'created_at': fragment.created_at,
                'updated_at': fragment.updated_at,
            }
            await client.execute(
                f"""
                INSERT INTO {_A3FRAGMENT_TABLE} (
                    fragment_key, kind, target_signature, target, source_domain,
                    evidence_count, replay_count, created_at, updated_at
                ) VALUES (
                    :fragment_key, :kind, :target_signature, json(:target), :source_domain,
                    1, 0, :created_at, :updated_at
                )
                ON CONFLICT(fragment_key) DO UPDATE SET
                    evidence_count = evidence_count + 1,
                    source_domain = excluded.source_domain,
                    updated_at = excluded.updated_at
                """,
                params,
            )
        return fragments

    async def load_fragments(self, *, kinds: set[str] | None = None, limit: int = 20) -> list[A3Fragment]:
        """Return reusable obstacle fragments, best candidates first, optionally filtered by kind."""
        await self._ensure_migrated()
        client = await self._connect()
        allowed = A3_FRAGMENT_BANK_KINDS if kinds is None else kinds & A3_FRAGMENT_BANK_KINDS
        if not allowed:
            return []
        kind_params = {f'kind_{idx}': kind for idx, kind in enumerate(sorted(allowed))}
        placeholders = ', '.join(f':{name}' for name in kind_params)
        result = await client.execute(
            f"""
            SELECT fragment_key, kind, json(target) AS target, source_domain, evidence_count,
                   replay_count, created_at, updated_at, last_replayed_at
            FROM {_A3FRAGMENT_TABLE}
            WHERE kind IN ({placeholders})
            ORDER BY replay_count DESC, evidence_count DESC, updated_at DESC
            LIMIT :limit
            """,
            {'limit': max(1, limit), **kind_params},
        )
        fragments: list[A3Fragment] = []
        for row in result.rows:
            raw = dict(zip(result.columns, row, strict=True))
            fragment = self._fragment_from_raw(raw)
            if fragment is not None:
                fragments.append(fragment)
        return fragments

    async def record_fragment_replay(self, fragment_key: str) -> None:
        """Increment replay stats for a successful reusable fragment."""
        await self._ensure_migrated()
        client = await self._connect()
        now = datetime.now().isoformat()
        await client.execute(
            f"""
            UPDATE {_A3FRAGMENT_TABLE}
            SET replay_count = replay_count + 1,
                last_replayed_at = :last_replayed_at,
                updated_at = :updated_at
            WHERE fragment_key = :fragment_key
            """,
            {'fragment_key': fragment_key, 'last_replayed_at': now, 'updated_at': now},
        )

    def _fragment_from_raw(self, raw: dict[str, Any]) -> A3Fragment | None:
        try:
            return A3Fragment(
                fragment_key=str(raw['fragment_key']),
                kind=str(raw['kind']),
                target=SelectorEntry.model_validate(json.loads(str(raw['target']))),
                source_domain=str(raw.get('source_domain', '')),
                evidence_count=int(raw.get('evidence_count', 1)),
                replay_count=int(raw.get('replay_count', 0)),
                created_at=str(raw.get('created_at', '')),
                updated_at=str(raw.get('updated_at', '')),
                last_replayed_at=raw.get('last_replayed_at'),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
            logger.warning('Corrupt A3 fragment %s — ignoring: %s', raw.get('fragment_key'), e)
            return None

    def _node_from_raw(self, raw: dict[str, Any], scope_key: str) -> A3Node | None:
        try:
            acts = [ActRecord.from_dict(a) for a in raw.get('acts', [])]
            return A3Node(
                domain=str(raw['domain']),
                acts=acts,
                discovered_at=str(raw.get('discovered_at', '')),
                replay_count=int(raw.get('replay_count', 0)),
                last_replayed_at=raw.get('last_replayed_at'),
                scope_key=scope_key,
                page_profile=str(raw.get('page_profile', _LEGACY_PAGE_PROFILE)),
                intent=str(raw.get('intent', _LEGACY_PAGE_PROFILE)),
                browser_fingerprint=str(raw.get('browser_fingerprint', _LEGACY_PAGE_PROFILE)),
                route_signature=str(raw.get('route_signature', '')),
                query_signature=str(raw.get('query_signature', '')),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning('Corrupt A3Node for scope %s — ignoring: %s', scope_key, e)
            return None

    async def _load_raw(self, scope: A3NodeScope | str) -> dict[str, Any] | None:
        """Compatibility helper for tests: load raw data by scope/domain."""
        return await self._load_raw_by_scope_key(_coerce_scope(scope).scope_key)

    async def _load_raw_by_scope_key(self, scope_key: str) -> dict[str, Any] | None:
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT scope_key, domain, page_profile, intent, browser_fingerprint, route_signature,
                   query_signature, format, json(acts) AS acts, discovered_at, replay_count,
                   last_replayed_at, updated_at
            FROM {_A3NODE_TABLE}
            WHERE scope_key = :scope_key
            LIMIT 1
            """,
            {'scope_key': scope_key},
        )
        if not result.rows:
            return None
        values = dict(zip(result.columns, result.rows[0], strict=True))
        try:
            values['acts'] = json.loads(str(values['acts']))
        except json.JSONDecodeError as e:
            logger.warning('Could not read A3Node for scope %s: %s', scope_key, e)
            return None
        return values

    async def _ensure_migrated(self) -> None:
        if self._migrated:
            await self._connect()
            return
        client = await self._connect()
        columns = await self._table_columns()
        if columns and 'scope_key' not in columns and {'domain', 'acts'} <= set(columns):
            await self._migrate_domain_only_table()
        elif columns and not self._schema_is_compatible(columns):
            await client.execute(f'DROP TABLE IF EXISTS {_A3NODE_TABLE}')
        await self._create_schema()
        self._migrated = True

    async def _create_schema(self) -> None:
        client = await self._connect()
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_A3NODE_TABLE} (
                scope_key TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                page_profile TEXT NOT NULL,
                intent TEXT NOT NULL,
                browser_fingerprint TEXT NOT NULL DEFAULT 'default',
                route_signature TEXT NOT NULL DEFAULT '',
                query_signature TEXT NOT NULL DEFAULT '',
                format INTEGER NOT NULL DEFAULT {_A3NODE_FORMAT},
                acts JSON NOT NULL,
                discovered_at TEXT NOT NULL,
                replay_count INTEGER NOT NULL DEFAULT 0,
                last_replayed_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        await client.execute(f'CREATE INDEX IF NOT EXISTS idx_a3nodes_domain ON {_A3NODE_TABLE}(domain)')
        await client.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_a3nodes_scope_parts
            ON {_A3NODE_TABLE}(domain, page_profile, intent, browser_fingerprint)
            """
        )
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_A3FRAGMENT_TABLE} (
                fragment_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                target_signature TEXT NOT NULL,
                target JSON NOT NULL,
                source_domain TEXT NOT NULL DEFAULT '',
                evidence_count INTEGER NOT NULL DEFAULT 1,
                replay_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_replayed_at TEXT
            )
            """
        )
        await client.execute(f'CREATE INDEX IF NOT EXISTS idx_a3fragments_kind ON {_A3FRAGMENT_TABLE}(kind)')

    async def _table_columns(self) -> dict[str, str]:
        client = await self._connect()
        result = await client.execute(f'PRAGMA table_info({_A3NODE_TABLE})')
        return {str(row[1]): str(row[2]).upper() for row in result.rows}

    @staticmethod
    def _schema_is_compatible(columns: dict[str, str]) -> bool:
        required = {
            'scope_key': 'TEXT',
            'domain': 'TEXT',
            'page_profile': 'TEXT',
            'intent': 'TEXT',
            'browser_fingerprint': 'TEXT',
            'route_signature': 'TEXT',
            'query_signature': 'TEXT',
            'format': 'INTEGER',
            'acts': 'JSON',
            'discovered_at': 'TEXT',
            'replay_count': 'INTEGER',
            'last_replayed_at': 'TEXT',
            'updated_at': 'TEXT',
        }
        return all(columns.get(name) == column_type for name, column_type in required.items())

    async def _migrate_domain_only_table(self) -> None:
        """Migrate pre-CAS-166 rows into explicit legacy-domain scopes."""
        client = await self._connect()
        legacy_table = f'{_A3NODE_TABLE}_domain_legacy'
        await client.execute(f'DROP TABLE IF EXISTS {legacy_table}')
        await client.execute(f'ALTER TABLE {_A3NODE_TABLE} RENAME TO {legacy_table}')
        await self._create_schema()
        result = await client.execute(f'SELECT * FROM {legacy_table}')
        now = datetime.now().isoformat()
        imported = 0
        for row in result.rows:
            values = dict(zip(result.columns, row, strict=True))
            domain = str(values.get('domain') or '').strip()
            if not domain:
                continue
            try:
                raw_acts = values.get('acts', '[]')
                acts = json.loads(str(raw_acts))
                if not isinstance(acts, list):
                    continue
            except (TypeError, json.JSONDecodeError):
                continue
            discovered = str(values.get('discovered_at') or now)
            updated = str(values.get('updated_at') or now)
            scope = A3NodeScope.legacy_domain(domain)
            await client.execute(
                f"""
                INSERT OR REPLACE INTO {_A3NODE_TABLE} (
                    scope_key, domain, page_profile, intent, browser_fingerprint,
                    route_signature, query_signature, format, acts, discovered_at,
                    replay_count, last_replayed_at, updated_at
                ) VALUES (
                    :scope_key, :domain, :page_profile, :intent, :browser_fingerprint,
                    :route_signature, :query_signature, :format, json(:acts), :discovered_at,
                    :replay_count, :last_replayed_at, :updated_at
                )
                """,
                {
                    'scope_key': scope.scope_key,
                    'domain': scope.domain,
                    'page_profile': scope.page_profile,
                    'intent': scope.intent,
                    'browser_fingerprint': scope.browser_fingerprint,
                    'route_signature': scope.route_signature,
                    'query_signature': scope.query_signature,
                    'format': int(values.get('format') or 1),
                    'acts': json.dumps(acts, sort_keys=True),
                    'discovered_at': discovered,
                    'replay_count': int(values.get('replay_count') or 0),
                    'last_replayed_at': values.get('last_replayed_at'),
                    'updated_at': updated,
                },
            )
            imported += 1
        await client.execute(f'DROP TABLE IF EXISTS {legacy_table}')
        logger.info('Migrated %d domain-only A3Node recipes into legacy scopes', imported)


@dataclass
class A3Node:
    """A stored DOM stability recipe for one replay scope.

    Attributes:
        domain: Bare domain string.
        acts: Ordered list of ActRecords to replay.
        discovered_at: ISO timestamp of when this recipe was first recorded.
        replay_count: How many times this recipe has been replayed successfully.
        last_replayed_at: ISO timestamp of the most recent successful replay, or None.
        scope_key: Versioned scope fingerprint used as SQLite primary key.

    """

    domain: str
    acts: list[ActRecord]
    discovered_at: str
    replay_count: int = 0
    last_replayed_at: str | None = None
    scope_key: str = ''
    page_profile: str = _LEGACY_PAGE_PROFILE
    intent: str = _LEGACY_PAGE_PROFILE
    browser_fingerprint: str = _LEGACY_PAGE_PROFILE
    route_signature: str = ''
    query_signature: str = ''

    @property
    def domloader_acts(self) -> list[ActRecord]:
        """Acts that DOMLoader should replay (excludes wait_for_js settle acts)."""
        return [a for a in self.acts if a.kind != 'wait_for_js']

    @property
    def settle_seconds(self) -> float:
        """Total settle delay to apply before content() on replay.

        Derived from recorded ``wait_for_js`` acts — each cycle represents
        one 500 ms poll interval that was needed for the JS assert to pass.
        """
        return float(sum(a.cycles * 0.5 for a in self.acts if a.kind == 'wait_for_js'))

    @property
    def is_empty(self) -> bool:
        """True when this scope needs no DOMLoader actions to reach stability.

        A recipe containing only ``wait_for_js`` settle acts is considered
        empty (no DOMLoader clicks/scrolls needed) but still carries a non-zero
        :attr:`settle_seconds` that replay must honour.
        """
        return len(self.domloader_acts) == 0

    @property
    def battle_tested(self) -> bool:
        """True when the recipe has been replayed at least 3 times."""
        return self.replay_count >= 3
