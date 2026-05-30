"""Per-domain A3Node storage — DOM stability recipes.

After DOMLoader finishes driving a page to a fully-loaded state, the sequence
of actions that succeeded is persisted here as a "stability recipe". On the
next visit to the same domain the recipe is replayed directly, skipping the
probe phase entirely and reaching page stability at significantly higher speed.

Storage location: .yosoi/a3nodes/a3node_<domain>.json

File format::

    {
      "domain": "finance.yahoo.com",
      "acts": [
        {"kind": "cookie", "cycles": 1},
        {"kind": "load_more", "cycles": 7}
      ],
      "discovered_at": "2026-05-23T14:00:00",
      "replay_count": 3,
      "last_replayed_at": "2026-05-23T15:00:00"
    }

``acts`` is an ordered list — replay executes them in the stored order.
An empty ``acts`` list means the domain was probed but needed no action.
``replay_count`` tracks how often the stored recipe was used successfully.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiofiles
import aiofiles.os

from yosoi.utils.files import atomic_write_json_async, init_yosoi

logger = logging.getLogger(__name__)


@dataclass
class ActRecord:
    """A single recorded action from a DOMLoader run.

    Attributes:
        kind: TriggerKind value string (e.g. 'load_more', 'cookie', 'infinite_scroll').
        cycles: How many times the action was repeated before the trigger was exhausted.

    """

    kind: str
    cycles: int

    def to_dict(self) -> dict[str, object]:
        """Serialise to a plain dict for JSON storage."""
        return {'kind': self.kind, 'cycles': self.cycles}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActRecord:
        """Deserialise from a plain dict."""
        return cls(kind=str(d['kind']), cycles=int(d['cycles']))


class A3NodeStorage:
    """Saves and loads per-domain DOM stability recipes.

    Usage::

        storage = A3NodeStorage()

        # After a successful DOMLoader run:
        storage.save("finance.yahoo.com", acts)

        # Before the next fetch — try replay:
        node = storage.load("finance.yahoo.com")
        if node is not None:
            # node.acts is the ordered sequence to replay
            ...

    """

    def __init__(self, storage_dir: str = 'a3nodes') -> None:
        """Initialise storage under .yosoi/a3nodes/.

        Args:
            storage_dir: Sub-directory name inside .yosoi/. Defaults to 'a3nodes'.

        """
        self._dir = str(init_yosoi(storage_dir))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save(self, domain: str, acts: list[ActRecord]) -> None:
        """Persist the stability recipe for *domain*.

        If a recipe already exists for this domain, it is overwritten with
        the fresh acts sequence. ``replay_count`` is reset to 0 since the
        stored acts have changed.

        Args:
            domain: Bare domain string (e.g. 'finance.yahoo.com').
            acts: Ordered list of ActRecord objects from this DOMLoader run.
                  May be empty — that is a valid recipe meaning "no action needed".

        """
        filepath = self._filepath(domain)
        now = datetime.now().isoformat()

        # Preserve replay stats when acts haven't changed
        existing = await self._load_raw(domain)
        existing_acts = existing.get('acts', []) if existing else []
        new_acts_dicts = [a.to_dict() for a in acts]
        same = existing_acts == new_acts_dicts

        data: dict[str, object] = {
            'domain': domain,
            'acts': new_acts_dicts,
            'discovered_at': existing.get('discovered_at', now) if existing else now,
            'replay_count': existing.get('replay_count', 0) if (existing and same) else 0,
            'last_replayed_at': existing.get('last_replayed_at') if existing else None,
            'updated_at': now,
        }

        try:
            await atomic_write_json_async(filepath, data)
            logger.debug('Saved A3Node for %s (%d acts)', domain, len(acts))
        except OSError as e:
            logger.warning('Could not save A3Node for %s: %s', domain, e)

    async def load(self, domain: str) -> A3Node | None:
        """Return the stored A3Node for *domain*, or None if not found.

        Args:
            domain: Bare domain string.

        Returns:
            A3Node with the stability recipe, or None if no recipe exists.

        """
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
        """Increment the replay count and update last_replayed_at timestamp.

        Call this after a successful replay so the UI and future heuristics
        know how battle-tested the stored recipe is.

        Args:
            domain: Bare domain string.

        """
        raw = await self._load_raw(domain)
        if raw is None:
            return
        raw['replay_count'] = int(raw.get('replay_count', 0)) + 1
        raw['last_replayed_at'] = datetime.now().isoformat()
        filepath = self._filepath(domain)
        try:
            await atomic_write_json_async(filepath, raw)
        except OSError as e:
            logger.warning('Could not update A3Node replay count for %s: %s', domain, e)

    async def delete(self, domain: str) -> bool:
        """Delete the stored A3Node for *domain*.

        Args:
            domain: Bare domain string.

        Returns:
            True if a file was deleted, False if nothing existed.

        """
        filepath = self._filepath(domain)
        if not await aiofiles.os.path.exists(filepath):
            return False
        try:
            await aiofiles.os.remove(filepath)
            logger.debug('Deleted A3Node for %s', domain)
            return True
        except OSError as e:
            logger.warning('Could not delete A3Node for %s: %s', domain, e)
            return False

    async def list_domains(self) -> list[str]:
        """Return all domains with a stored A3Node, sorted alphabetically."""
        if not await aiofiles.os.path.exists(self._dir):
            return []
        domains: list[str] = []
        for filename in await aiofiles.os.listdir(self._dir):
            if not (filename.startswith('a3node_') and filename.endswith('.json')):
                continue
            filepath = os.path.join(self._dir, filename)
            try:
                async with aiofiles.open(filepath, encoding='utf-8') as f:
                    data = json.loads(await f.read())
                domain = data.get('domain')
                if isinstance(domain, str) and domain:
                    domains.append(domain)
            except (OSError, json.JSONDecodeError):
                pass
        return sorted(domains)

    async def load_all(self) -> dict[str, A3Node]:
        """Load every stored A3Node into a domain → A3Node mapping.

        Useful for pre-populating an in-memory cache at fetcher startup.

        Returns:
            Dict mapping domain strings to A3Node instances.

        """
        result: dict[str, A3Node] = {}
        for domain in await self.list_domains():
            node = await self.load(domain)
            if node is not None:
                result[domain] = node
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filepath(self, domain: str) -> str:
        safe = domain.replace('.', '_').replace('/', '_').replace(':', '_')
        return os.path.join(self._dir, f'a3node_{safe}.json')

    async def _load_raw(self, domain: str) -> dict[str, Any] | None:
        filepath = self._filepath(domain)
        if not await aiofiles.os.path.exists(filepath):
            return None
        try:
            async with aiofiles.open(filepath, encoding='utf-8') as f:
                data: dict[str, object] = json.loads(await f.read())
                return data
        except (OSError, json.JSONDecodeError) as e:
            logger.warning('Could not read A3Node for %s: %s', domain, e)
            return None


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
