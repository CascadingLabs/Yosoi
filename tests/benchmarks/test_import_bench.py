"""CodSpeed benchmarks for package import cost — a lazy-loading regression guard.

Yosoi's package ``__init__`` files use PEP 562 lazy exports (see AGENTS.md
"Lazy Loading"), so ``import yosoi`` and short-lived subprocesses (notably the
``yosoi-validator-mcp`` server spawned cold by every MCP-discovery backend) pull
only a handful of modules instead of the whole pydantic-ai / SDK / parsel graph.

These benchmarks measure how much of the *yosoi* module tree executes for one
import. We snapshot ``sys.modules``, drop the ``yosoi.*`` entries, import the
target, then restore — so each iteration re-runs the real package ``__init__``
chain while leaving heavy third-party modules cached (deterministic, no flaky
C-extension re-imports, no session pollution). If a package ``__init__`` ever
regresses to eager ``from .submodule import X`` re-exports, the tree it pulls —
and this instruction count — spikes.

``yosoi.types`` is preserved across the clear on purpose: it registers coercions
on import (the documented eager exception), so re-importing it every iteration
would re-run registration.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest
from pytest_codspeed import BenchmarkFixture


def _is_yosoi(name: str) -> bool:
    return name == 'yosoi' or name.startswith('yosoi.')


def _preserve(name: str) -> bool:
    # Keep the eager, side-effect-registering types package cached.
    return name == 'yosoi.types' or name.startswith('yosoi.types.')


def _cold_import(target: str) -> ModuleType:
    """Import ``target`` from a cleared ``yosoi.*`` module state, then restore it."""
    cleared = {name: sys.modules.pop(name) for name in list(sys.modules) if _is_yosoi(name) and not _preserve(name)}
    try:
        return importlib.import_module(target)
    finally:
        for name in [n for n in sys.modules if _is_yosoi(n) and not _preserve(n)]:
            del sys.modules[name]
        sys.modules.update(cleared)


@pytest.mark.parametrize(
    'target',
    ['yosoi', 'yosoi.integrations.validator_mcp', 'yosoi.core.discovery.mcp_draft', 'yosoi.policy'],
    ids=['top-level', 'validator-path', 'discovery-leaf', 'policy-pkg'],
)
def test_cold_import(benchmark: BenchmarkFixture, target: str) -> None:
    # Warm the eager types package once so the first iteration doesn't pay (and
    # never re-pays) its registration inside the measured region.
    importlib.import_module('yosoi.types')

    module = benchmark(lambda: _cold_import(target))

    assert module is not None
    assert module.__name__ == target
