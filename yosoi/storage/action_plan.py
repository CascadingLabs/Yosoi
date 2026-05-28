"""Per-domain action-plan storage — LLM-discovered A3Node sequences.

Sibling of :class:`yosoi.storage.a3node.A3NodeStorage` but holds the
**rich** plans emitted by :class:`yosoi.core.discovery.action_plan_agent
.ActionPlanDiscoveryAgent` — full :class:`yosoi.models.replay.ReplayPlan`
objects with selectors, assertions, and ``click_until`` repeats — rather
than the coarse heuristic ``(kind, cycles)`` records that the DOMLoader
probe writes.

Two reasons for the parallel storage:

  * **Granularity** — A3NodeStorage is keyed off ``TriggerKind`` (load_more /
    pagination / infinite_scroll); the rich plan carries the actual selector
    and termination signal, which is what reddit needs (the heuristic
    ``load_more`` kind misses ``<faceplate-partial>`` custom-element triggers).
  * **Discovery source** — A3NodeStorage caches what the heuristic prober found
    during its sweep. This module caches what the LLM agent emitted. The two
    have different freshness / invalidation profiles and the consumer code is
    cleaner when they don't share a file.

Storage location: ``.yosoi/action_plans/plan_<slug>.json``

The file is the plan's own ``model_dump_json`` — same shape as the canonical
``ReplayPlan`` JSON used by the example replay-runtime, so plans round-trip
between hand-authored examples and LLM-discovered ones.
"""

from __future__ import annotations

import logging
from pathlib import Path

from yosoi.models.replay import ReplayPlan
from yosoi.utils.files import init_yosoi

logger = logging.getLogger(__name__)

DEFAULT_DIR_NAME = 'action_plans'


def _slug(target: str) -> str:
    """Normalise a target string into a filesystem-safe slug.

    The ``target`` of a ``ReplayPlan`` is typically a domain (or
    ``domain/section``). We replace path/scheme separators with underscores;
    the input is trusted (it came from our own callers, never user content).
    """
    return target.replace('/', '_').replace(':', '').replace('?', '_').strip('_') or 'default'


class ActionPlanStorage:
    """Persist and reload LLM-discovered :class:`ReplayPlan`s, keyed by target.

    Usage::

        storage = ActionPlanStorage()

        # After a successful discovery:
        storage.save(plan)

        # Before the next fetch — try replay:
        plan = storage.load("reddit.com/r/ted/post")
        if plan is not None:
            ...  # run plan via the replay-runtime
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        """Initialise storage. Creates the directory tree if it does not exist.

        Args:
            storage_dir: Override the default ``.yosoi/action_plans/`` location.
                Useful for tests and for examples that want a sandboxed cache.
        """
        if storage_dir is None:
            init_yosoi()
            base = Path.cwd() / '.yosoi'
            storage_dir = base / DEFAULT_DIR_NAME
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, target: str) -> Path:
        return self.storage_dir / f'plan_{_slug(target)}.json'

    def save(self, plan: ReplayPlan) -> Path:
        """Persist *plan* as JSON. Returns the written path."""
        path = self._path_for(plan.target)
        path.write_text(plan.model_dump_json(indent=2), encoding='utf-8')
        logger.info('Saved action plan: %s (%d nodes)', plan.target, len(plan.nodes))
        return path

    def load(self, target: str) -> ReplayPlan | None:
        """Load the persisted plan for *target*, or ``None`` if none exists.

        A malformed file is treated as a cache miss (logged) rather than raised
        — the caller's next step is to re-discover, which is the right recovery.
        """
        path = self._path_for(target)
        if not path.exists():
            return None
        try:
            return ReplayPlan.model_validate_json(path.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            logger.warning('Failed to load action plan %s: %s', path, exc)
            return None

    def delete(self, target: str) -> bool:
        """Delete the cached plan for *target*. Returns True if anything removed."""
        path = self._path_for(target)
        if path.exists():
            path.unlink()
            logger.info('Deleted action plan: %s', target)
            return True
        return False

    def has(self, target: str) -> bool:
        """Cheap existence check (no parse)."""
        return self._path_for(target).exists()
