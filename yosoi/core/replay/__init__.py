"""Replay runtime for persisted MCP discovery lessons.

Lazy (PEP 562). See ``CLAUDE.md`` ("Lazy loading").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.core.replay.reactions import BusReactionResolver as BusReactionResolver
    from yosoi.core.replay.reactions import ReactionMiss as ReactionMiss
    from yosoi.core.replay.reactions import ReactionResolver as ReactionResolver
    from yosoi.core.replay.runtime import ReplayExecutionError as ReplayExecutionError
    from yosoi.core.replay.runtime import execute_plan as execute_plan
    from yosoi.core.replay.runtime import execute_tree as execute_tree
    from yosoi.core.replay.runtime import verify_plan as verify_plan

_RUNTIME = 'yosoi.core.replay.runtime'
_REACTIONS = 'yosoi.core.replay.reactions'
_LAZY: dict[str, str] = {
    'ReplayExecutionError': _RUNTIME,
    'execute_plan': _RUNTIME,
    'execute_tree': _RUNTIME,
    'verify_plan': _RUNTIME,
    'BusReactionResolver': _REACTIONS,
    'ReactionMiss': _REACTIONS,
    'ReactionResolver': _REACTIONS,
}

__all__ = sorted(_LAZY)

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
