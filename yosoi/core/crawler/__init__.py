"""Model-free crawl/index primitives."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.core.crawler.coordinator import CrawlCoordinator as CrawlCoordinator
    from yosoi.core.crawler.coordinator import CrawlJob as CrawlJob
    from yosoi.core.crawler.coordinator import CrawlResult as CrawlResult
    from yosoi.core.crawler.coordinator import CrawlRunSummary as CrawlRunSummary
    from yosoi.core.crawler.frontier import CrawlFrontier as CrawlFrontier
    from yosoi.core.crawler.frontier import FrontierEntry as FrontierEntry
    from yosoi.core.crawler.frontier import canonicalize_url as canonicalize_url
    from yosoi.core.crawler.links import CrawlLink as CrawlLink
    from yosoi.core.crawler.links import LinkExtractor as LinkExtractor

_LAZY = {
    'CrawlCoordinator': 'yosoi.core.crawler.coordinator',
    'CrawlFrontier': 'yosoi.core.crawler.frontier',
    'CrawlJob': 'yosoi.core.crawler.coordinator',
    'CrawlLink': 'yosoi.core.crawler.links',
    'CrawlResult': 'yosoi.core.crawler.coordinator',
    'CrawlRunSummary': 'yosoi.core.crawler.coordinator',
    'FrontierEntry': 'yosoi.core.crawler.frontier',
    'LinkExtractor': 'yosoi.core.crawler.links',
    'canonicalize_url': 'yosoi.core.crawler.frontier',
}
__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
