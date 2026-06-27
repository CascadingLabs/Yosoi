"""Per-domain A3Node storage — DOM stability recipes in Yosoi SQLite.

After DOMLoader finishes driving a page to a fully-loaded state, the sequence
of actions that succeeded is persisted as a "stability recipe". On the next
visit to the same domain the recipe is replayed directly, skipping probe work.

Storage location: `.yosoi/yosoi.sqlite3`, table `a3nodes`.

Schema shape::

    domain TEXT PRIMARY KEY
    format INTEGER
    acts JSON
    discovered_at TEXT
    replay_count INTEGER
    last_replayed_at TEXT
    updated_at TEXT

``acts`` is readable SQLite JSON text: an ordered list of
:class:`ActRecord` objects. An empty ``acts`` list means the domain was probed
but needed no action. ``replay_count`` tracks how often the stored recipe was
used successfully.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from libsql_client import LibsqlError

from yosoi.models.selectors import SelectorEntry
from yosoi.storage.sqlite_store import YosoiSQLiteStore

logger = logging.getLogger(__name__)

# On-disk recipe format. 1 = {kind, cycles} only; 2 = adds a concrete `target` per act
# so replay skips the discovery catalogues. A file with no `format` key is format 1.
_A3NODE_FORMAT = 2
_A3NODE_TABLE = 'a3nodes'


def _acts_shape(acts: list[dict[str, Any]]) -> list[tuple[object, object]]:
    """Recipe identity for stat preservation: the (kind, cycles) sequence only.

    Adding or refining a concrete ``target`` on an otherwise-identical recipe must NOT
    reset ``replay_count`` — that is what makes the format-1 -> format-2 upgrade
    non-destructive for battle-tested domains.
    """
    return [(a.get('kind'), a.get('cycles')) for a in acts]


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


class A3NodeStorage(YosoiSQLiteStore):
    """Saves and loads per-domain DOM stability recipes from Yosoi SQLite."""

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

    async def save(self, domain: str, acts: list[ActRecord]) -> None:
        """Persist the stability recipe for *domain*.

        If the recipe's ``(kind, cycles)`` shape changed, replay stats reset. Target
        refinements preserve replay stats.
        """
        await self._ensure_migrated()
        client = await self._connect()
        now = datetime.now().isoformat()

        existing = await self._load_raw(domain)
        existing_acts = existing.get('acts', []) if existing else []
        new_acts_dicts = [a.to_dict() for a in acts]
        same = _acts_shape(existing_acts) == _acts_shape(new_acts_dicts)

        params: dict[str, object] = {
            'domain': domain,
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
                    domain, format, acts, discovered_at, replay_count, last_replayed_at, updated_at
                )
                VALUES (
                    :domain, :format, json(:acts), :discovered_at, :replay_count, :last_replayed_at, :updated_at
                )
                ON CONFLICT(domain) DO UPDATE SET
                    format = excluded.format,
                    acts = excluded.acts,
                    discovered_at = excluded.discovered_at,
                    replay_count = excluded.replay_count,
                    last_replayed_at = excluded.last_replayed_at,
                    updated_at = excluded.updated_at
                """,
                params,
            )
            logger.debug('Saved A3Node for %s (%d acts)', domain, len(acts))
        except LibsqlError as e:
            logger.warning('Could not save A3Node for %s: %s', domain, e)

    async def load(self, domain: str) -> A3Node | None:
        """Return the stored A3Node for *domain*, or None if not found."""
        raw = await self._load_raw(domain)
        if raw is None:
            return None
        try:
            acts = [ActRecord.from_dict(a) for a in raw.get('acts', [])]
            return A3Node(
                domain=str(raw['domain']),
                acts=acts,
                discovered_at=str(raw.get('discovered_at', '')),
                replay_count=int(raw.get('replay_count', 0)),
                last_replayed_at=raw.get('last_replayed_at'),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning('Corrupt A3Node for %s — ignoring: %s', domain, e)
            return None

    async def record_replay(self, domain: str) -> None:
        """Increment replay count and update ``last_replayed_at`` after successful replay."""
        await self._ensure_migrated()
        client = await self._connect()
        await client.execute(
            f"""
            UPDATE {_A3NODE_TABLE}
            SET replay_count = replay_count + 1,
                last_replayed_at = :last_replayed_at,
                updated_at = :updated_at
            WHERE domain = :domain
            """,
            {
                'domain': domain,
                'last_replayed_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
            },
        )

    async def delete(self, domain: str) -> bool:
        """Delete the stored A3Node for *domain*."""
        await self._ensure_migrated()
        if await self._load_raw(domain) is None:
            return False
        client = await self._connect()
        await client.execute(f'DELETE FROM {_A3NODE_TABLE} WHERE domain = :domain', {'domain': domain})
        logger.debug('Deleted A3Node for %s', domain)
        return True

    async def list_domains(self) -> list[str]:
        """Return all domains with a stored A3Node, sorted alphabetically."""
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(f'SELECT domain FROM {_A3NODE_TABLE} ORDER BY domain')
        return [str(row[0]) for row in result.rows]

    async def load_all(self) -> dict[str, A3Node]:
        """Load every stored A3Node into a domain → A3Node mapping."""
        result: dict[str, A3Node] = {}
        for domain in await self.list_domains():
            node = await self.load(domain)
            if node is not None:
                result[domain] = node
        return result

    async def _load_raw(self, domain: str) -> dict[str, Any] | None:
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(
            f"""
            SELECT domain, format, json(acts) AS acts, discovered_at, replay_count, last_replayed_at, updated_at
            FROM {_A3NODE_TABLE}
            WHERE domain = :domain
            LIMIT 1
            """,
            {'domain': domain},
        )
        if not result.rows:
            return None
        values = dict(zip(result.columns, result.rows[0], strict=True))
        try:
            values['acts'] = json.loads(str(values['acts']))
        except json.JSONDecodeError as e:
            logger.warning('Could not read A3Node for %s: %s', domain, e)
            return None
        return values

    async def _ensure_migrated(self) -> None:
        if self._migrated:
            await self._connect()
            return
        client = await self._connect()
        if await self._schema_needs_reset():
            await client.execute(f'DROP TABLE IF EXISTS {_A3NODE_TABLE}')
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_A3NODE_TABLE} (
                domain TEXT PRIMARY KEY,
                format INTEGER NOT NULL DEFAULT {_A3NODE_FORMAT},
                acts JSON NOT NULL,
                discovered_at TEXT NOT NULL,
                replay_count INTEGER NOT NULL DEFAULT 0,
                last_replayed_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._migrated = True

    async def _schema_needs_reset(self) -> bool:
        client = await self._connect()
        result = await client.execute(f'PRAGMA table_info({_A3NODE_TABLE})')
        if not result.rows:
            return False
        columns = {str(row[1]): str(row[2]).upper() for row in result.rows}
        required = {
            'domain': 'TEXT',
            'format': 'INTEGER',
            'acts': 'JSON',
            'discovered_at': 'TEXT',
            'replay_count': 'INTEGER',
            'last_replayed_at': 'TEXT',
            'updated_at': 'TEXT',
        }
        return any(columns.get(name) != column_type for name, column_type in required.items())


@dataclass
class A3Node:
    """A stored DOM stability recipe for one domain.

    Attributes:
        domain: Bare domain string.
        acts: Ordered list of ActRecords to replay.
        discovered_at: ISO timestamp of when this recipe was first recorded.
        replay_count: How many times this recipe has been replayed successfully.
        last_replayed_at: ISO timestamp of the most recent successful replay, or None.

    """

    domain: str
    acts: list[ActRecord]
    discovered_at: str
    replay_count: int = 0
    last_replayed_at: str | None = None

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
        """True when this domain needs no DOMLoader actions to reach stability.

        A recipe containing only ``wait_for_js`` settle acts is considered
        empty (no DOMLoader clicks/scrolls needed) but still carries a non-zero
        :attr:`settle_seconds` that replay must honour.
        """
        return len(self.domloader_acts) == 0

    @property
    def battle_tested(self) -> bool:
        """True when the recipe has been replayed at least 3 times."""
        return self.replay_count >= 3
