"""vc — Pydantic-wrapped interface to void_crawl browser automation.

This module is the standard entry-point for all browser automation in Yosoi.
Users should never need to ``import void_crawl`` directly.

Also available as ``from yosoi import VoidCrawl``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi.vc._import import get_driver_attr
from yosoi.vc.page import page, pages
from yosoi.vc.pool import PerformanceMode, PoolConfig, Viewport, create_pool, pool
from yosoi.vc.session import SessionConfig, session

if TYPE_CHECKING:
    from void_crawl import BrowserPool, BrowserSession, Page, PooledTab

# Lazy re-exports so ``vc.PooledTab`` etc. work at runtime without
# requiring void_crawl at import time.
_DRIVER_TYPES = frozenset({'BrowserPool', 'BrowserSession', 'Page', 'PooledTab'})


def __getattr__(name: str) -> object:
    if name in _DRIVER_TYPES:
        return get_driver_attr(name)
    raise AttributeError(f"module 'yosoi.vc' has no attribute {name!r}")


__all__ = [
    'BrowserPool',
    'BrowserSession',
    'Page',
    'PerformanceMode',
    'PoolConfig',
    'PooledTab',
    'SessionConfig',
    'Viewport',
    'create_pool',
    'page',
    'pages',
    'pool',
    'session',
]
