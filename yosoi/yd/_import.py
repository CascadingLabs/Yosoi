"""Shared import helper for yosoi_driver."""

from __future__ import annotations

import types
from typing import Any

_INSTALL_MSG = 'yosoi_driver is not installed. Build it with: cd yosoi_driver && ./build.sh'


def require_driver() -> types.ModuleType:
    """Import and return the yosoi_driver module, raising a clear error if missing."""
    try:
        import yosoi_driver
    except ImportError:
        raise ImportError(_INSTALL_MSG) from None
    return yosoi_driver


def get_driver_attr(name: str) -> Any:
    """Get a named attribute from yosoi_driver (lazy import)."""
    return getattr(require_driver(), name)
