"""Crawl frontier, link extraction, and structure fingerprinting.

Lazy (PEP 562). See ``CLAUDE.md`` ("Lazy loading").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.core.crawler.frontier import Frontier as Frontier
    from yosoi.core.crawler.frontier import normalize_url as normalize_url
    from yosoi.core.crawler.link_extractor import LinkExtractor as LinkExtractor
    from yosoi.core.crawler.link_extractor import LinkScore as LinkScore

_LAZY: dict[str, str] = {
    'Frontier': 'yosoi.core.crawler.frontier',
    'normalize_url': 'yosoi.core.crawler.frontier',
    'LinkExtractor': 'yosoi.core.crawler.link_extractor',
    'LinkScore': 'yosoi.core.crawler.link_extractor',
}

__all__ = ['Frontier', 'LinkExtractor', 'LinkScore', 'normalize_url']

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
