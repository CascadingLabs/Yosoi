"""Storage and tracking components.

Lazy (PEP 562) so importing one storage backend does not pull the others. See
``CLAUDE.md`` ("Lazy loading").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.storage.a3node import A3_FRAGMENT_BANK_KINDS as A3_FRAGMENT_BANK_KINDS
    from yosoi.storage.a3node import A3Fragment as A3Fragment
    from yosoi.storage.a3node import A3Node as A3Node
    from yosoi.storage.a3node import A3NodeStorage as A3NodeStorage
    from yosoi.storage.a3node import ActRecord as ActRecord
    from yosoi.storage.cache_metrics_libsql import CacheFieldMetric as CacheFieldMetric
    from yosoi.storage.cache_metrics_libsql import ContractCacheMetrics as ContractCacheMetrics
    from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore as LibSQLCacheMetricsStore
    from yosoi.storage.cache_metrics_libsql import ScrapeHealth as ScrapeHealth
    from yosoi.storage.cache_metrics_libsql import ScrapeRunMetric as ScrapeRunMetric
    from yosoi.storage.crawl_runs import CrawlRunsStore as CrawlRunsStore
    from yosoi.storage.debug import DebugManager as DebugManager
    from yosoi.storage.lesson import LessonStorage as LessonStorage
    from yosoi.storage.persistence import SelectorStorage as SelectorStorage
    from yosoi.storage.strategy import FetchStrategyStorage as FetchStrategyStorage
    from yosoi.storage.tracking import LLMTracker as LLMTracker

_LAZY: dict[str, str] = {
    'A3_FRAGMENT_BANK_KINDS': 'yosoi.storage.a3node',
    'A3Fragment': 'yosoi.storage.a3node',
    'A3Node': 'yosoi.storage.a3node',
    'A3NodeStorage': 'yosoi.storage.a3node',
    'ActRecord': 'yosoi.storage.a3node',
    'CacheFieldMetric': 'yosoi.storage.cache_metrics_libsql',
    'LibSQLCacheMetricsStore': 'yosoi.storage.cache_metrics_libsql',
    'ContractCacheMetrics': 'yosoi.storage.cache_metrics_libsql',
    'ScrapeHealth': 'yosoi.storage.cache_metrics_libsql',
    'ScrapeRunMetric': 'yosoi.storage.cache_metrics_libsql',
    'CrawlRunsStore': 'yosoi.storage.crawl_runs',
    'DebugManager': 'yosoi.storage.debug',
    'LessonStorage': 'yosoi.storage.lesson',
    'SelectorStorage': 'yosoi.storage.persistence',
    'FetchStrategyStorage': 'yosoi.storage.strategy',
    'LLMTracker': 'yosoi.storage.tracking',
}

__all__ = sorted(_LAZY)

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
