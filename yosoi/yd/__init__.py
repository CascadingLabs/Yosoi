"""yd — Pydantic-wrapped interface to yosoi_driver browser automation.

This module is the standard entry-point for all browser automation in Yosoi.
Users should never need to ``import yosoi_driver`` directly.

Also available as ``from yosoi import YosoiDriver``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi.yd.page import page, pages
from yosoi.yd.pool import PoolConfig, pool
from yosoi.yd.session import SessionConfig, session

if TYPE_CHECKING:
    from yosoi_driver import BrowserPool, BrowserSession, Page, PooledTab

# Lazy re-exports so ``yd.PooledTab`` etc. work at runtime without
# requiring yosoi_driver at import time.
_DRIVER_TYPES = frozenset({'BrowserPool', 'BrowserSession', 'Page', 'PooledTab'})


def __getattr__(name: str) -> object:
    if name in _DRIVER_TYPES:
        try:
            import yosoi_driver
        except ImportError:
            raise ImportError('yosoi_driver is not installed. Build it with: cd yosoi_driver && ./build.sh') from None
        return getattr(yosoi_driver, name)
    raise AttributeError(f"module 'yosoi.yd' has no attribute {name!r}")


__all__ = [
    'BrowserPool',
    'BrowserSession',
    'Page',
    'PoolConfig',
    'PooledTab',
    'SessionConfig',
    'page',
    'pages',
    'pool',
    'session',
]
