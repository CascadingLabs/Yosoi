"""Replay runtime for persisted MCP discovery lessons.

Lazy (PEP 562). See ``CLAUDE.md`` ("Lazy loading").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.core.replay.runtime import ReplayExecutionError as ReplayExecutionError
    from yosoi.core.replay.runtime import execute_plan as execute_plan
    from yosoi.core.replay.runtime import verify_plan as verify_plan

_RUNTIME = 'yosoi.core.replay.runtime'
_LAZY: dict[str, str] = {
    'ReplayExecutionError': _RUNTIME,
    'execute_plan': _RUNTIME,
    'verify_plan': _RUNTIME,
}

__all__ = ['ReplayExecutionError', 'execute_plan', 'verify_plan']

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
