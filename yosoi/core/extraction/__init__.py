"""Content extraction components.

Lazy (PEP 562): ``ContentExtractor`` pulls parsel; resolve it on first access.
See ``CLAUDE.md`` ("Lazy loading").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.core.extraction.extractor import ContentExtractor as ContentExtractor

_LAZY: dict[str, str] = {'ContentExtractor': 'yosoi.core.extraction.extractor'}

__all__ = ['ContentExtractor']

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
