"""Output formatting for extracted content.

Lazy (PEP 562). See ``CLAUDE.md`` ("Lazy loading").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.outputs.utils import format_content as format_content
    from yosoi.outputs.utils import format_selectors as format_selectors
    from yosoi.outputs.utils import save_formatted_content as save_formatted_content
    from yosoi.outputs.utils import save_formatted_selectors as save_formatted_selectors

_UTILS = 'yosoi.outputs.utils'
_LAZY: dict[str, str] = {
    'format_content': _UTILS,
    'format_selectors': _UTILS,
    'save_formatted_content': _UTILS,
    'save_formatted_selectors': _UTILS,
}

__all__ = ['format_content', 'format_selectors', 'save_formatted_content', 'save_formatted_selectors']

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
