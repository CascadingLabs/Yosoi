"""Selector-discovery pipeline package.

The pipeline is a thin spine (``base.Pipeline``) composing focused mixin modules:

* ``cache``      — cached selector replay
* ``extraction`` — fetch / clean / extract / downloads
* ``discovery``  — AI selector discovery, MCP escalation, JS actions
* ``crawler``    — frontier / crawl helpers (CAS-52)
* ``utils``      — stateless helpers, display methods

Public names are resolved lazily (PEP 562) so ``import yosoi.core.pipeline`` (and
``from yosoi.core.pipeline import Pipeline``) does not eagerly drag in pydantic-ai,
the provider SDKs, parsel, etc. See ``AGENTS.md`` ("Lazy Loading").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:  # static typing only — no runtime cost
    from yosoi.core.pipeline.base import ContentItems as ContentItems
    from yosoi.core.pipeline.base import ContentMap as ContentMap
    from yosoi.core.pipeline.base import Pipeline as Pipeline
    from yosoi.core.pipeline.base import SelectorMap as SelectorMap
    from yosoi.core.pipeline.base import _build_concurrent_table as _build_concurrent_table

_LAZY: dict[str, str] = {
    'Pipeline': 'yosoi.core.pipeline.base',
    'ContentMap': 'yosoi.core.pipeline.base',
    'ContentItems': 'yosoi.core.pipeline.base',
    'SelectorMap': 'yosoi.core.pipeline.base',
    '_build_concurrent_table': 'yosoi.core.pipeline.base',
}

__all__ = ['ContentItems', 'ContentMap', 'Pipeline', 'SelectorMap']

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
