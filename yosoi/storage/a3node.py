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

from yosoi.utils.files import init_yosoi

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
    def from_dict(cls, d: dict[str, object]) -> ActRecord:
        """Deserialise from a plain dict."""
        return cls(kind=str(d['kind']), cycles=int(d['cycles']))  # type: ignore[arg-type]


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

    def save(self, domain: str, acts: list[ActRecord]) -> None:
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
        existing = self._load_raw(domain)
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
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            logger.debug('Saved A3Node for %s (%d acts)', domain, len(acts))
        except OSError as e:
            logger.warning('Could not save A3Node for %s: %s', domain, e)

    def load(self, domain: str) -> A3Node | None:
        """Return the stored A3Node for *domain*, or None if not found.

        Args:
            domain: Bare domain string.

        Returns:
            A3Node with the stability recipe, or None if no recipe exists.

        """
        raw = self._load_raw(domain)
        if raw is None:
            return None
        try:
            acts = [ActRecord.from_dict(a) for a in raw.get('acts', [])]
            return A3Node(
                domain=str(raw['domain']),
                acts=acts,
                discovered_at=str(raw.get('discovered_at', '')),
                replay_count=int(raw.get('replay_count', 0)),  # type: ignore[arg-type]
                last_replayed_at=raw.get('last_replayed_at'),  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning('Corrupt A3Node for %s — ignoring: %s', domain, e)
            return None

    def record_replay(self, domain: str) -> None:
        """Increment the replay count and update last_replayed_at timestamp.

        Call this after a successful replay so the UI and future heuristics
        know how battle-tested the stored recipe is.

        Args:
            domain: Bare domain string.

        """
        raw = self._load_raw(domain)
        if raw is None:
            return
        raw['replay_count'] = int(raw.get('replay_count', 0)) + 1  # type: ignore[arg-type]
        raw['last_replayed_at'] = datetime.now().isoformat()
        filepath = self._filepath(domain)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(raw, f, indent=2)
        except OSError as e:
            logger.warning('Could not update A3Node replay count for %s: %s', domain, e)

    def delete(self, domain: str) -> bool:
        """Delete the stored A3Node for *domain*.

        Args:
            domain: Bare domain string.

        Returns:
            True if a file was deleted, False if nothing existed.

        """
        filepath = self._filepath(domain)
        if not os.path.exists(filepath):
            return False
        try:
            os.remove(filepath)
            logger.debug('Deleted A3Node for %s', domain)
            return True
        except OSError as e:
            logger.warning('Could not delete A3Node for %s: %s', domain, e)
            return False

    def list_domains(self) -> list[str]:
        """Return all domains with a stored A3Node, sorted alphabetically."""
        if not os.path.exists(self._dir):
            return []
        domains: list[str] = []
        for filename in os.listdir(self._dir):
            if not (filename.startswith('a3node_') and filename.endswith('.json')):
                continue
            filepath = os.path.join(self._dir, filename)
            try:
                with open(filepath, encoding='utf-8') as f:
                    data = json.load(f)
                domain = data.get('domain')
                if isinstance(domain, str) and domain:
                    domains.append(domain)
            except (OSError, json.JSONDecodeError):
                pass
        return sorted(domains)

    def load_all(self) -> dict[str, A3Node]:
        """Load every stored A3Node into a domain → A3Node mapping.

        Useful for pre-populating an in-memory cache at fetcher startup.

        Returns:
            Dict mapping domain strings to A3Node instances.

        """
        result: dict[str, A3Node] = {}
        for domain in self.list_domains():
            node = self.load(domain)
            if node is not None:
                result[domain] = node
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filepath(self, domain: str) -> str:
        safe = domain.replace('.', '_').replace('/', '_').replace(':', '_')
        return os.path.join(self._dir, f'a3node_{safe}.json')

    def _load_raw(self, domain: str) -> dict[str, object] | None:
        filepath = self._filepath(domain)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, encoding='utf-8') as f:
                data: dict[str, object] = json.load(f)
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
    def is_empty(self) -> bool:
        """True when this domain needs no actions to reach stability."""
        return len(self.acts) == 0

    @property
    def battle_tested(self) -> bool:
        """True when the recipe has been replayed at least 3 times."""
        return self.replay_count >= 3
