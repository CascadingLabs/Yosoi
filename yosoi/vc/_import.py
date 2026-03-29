"""Shared import helper for void_crawl."""

from __future__ import annotations

import types
from typing import Any

_INSTALL_MSG = 'void_crawl is not installed. Build it with: cd void_crawl && ./build.sh'


def require_driver() -> types.ModuleType:
    """Import and return the void_crawl module, raising a clear error if missing."""
    try:
        import void_crawl  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(_INSTALL_MSG) from None
    mod: types.ModuleType = void_crawl
    return mod


def get_driver_attr(name: str) -> Any:
    """Get a named attribute from void_crawl (lazy import)."""
    return getattr(require_driver(), name)
