"""Per-domain fetcher strategy persistence.

Saves which fetcher tier worked for each domain so subsequent runs skip
the waterfall and go straight to the right tier.

Storage location: .yosoi/fetch/fetch_<domain>.json

File format::

    {
      "domain": "finance.yahoo.com",
      "fetcher": "headful",
      "selector_level": "css",
      "discovered_at": "2026-03-21T22:49:05"
    }

Valid fetcher values: "simple", "headless", "headful"
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import get_args

import aiofiles
import aiofiles.os

from yosoi.models.selectors import SelectorKind
from yosoi.utils.files import atomic_write_json_async, init_yosoi, safe_domain

logger = logging.getLogger(__name__)

VALID_FETCHERS = frozenset({'simple', 'headless', 'headful'})
# Derived from the canonical SelectorKind union — must cover every level the discovery
# pipeline can produce (css/xpath/regex/jsonld/attr/global_id/role/visual), or a winning
# higher-tier strategy (e.g. role/attr from AX discovery) is silently dropped on save.
VALID_SELECTOR_LEVELS = frozenset(get_args(SelectorKind))


@dataclass(frozen=True)
class FetchStrategy:
    """Cached loading strategy for a domain."""

    fetcher: str
    selector_level: str | None = None


class FetchStrategyStorage:
    """Saves and loads the winning fetcher tier per domain.

    Usage::

        storage = FetchStrategyStorage()

        # On successful fetch
        storage.save('finance.yahoo.com', 'headful')

        # Before fetching
        tier = storage.load('finance.yahoo.com')  # -> 'headful' or None
    """

    def __init__(self, storage_dir: str = 'fetch') -> None:
        """Initialise storage under .yosoi/fetch/.

        Args:
            storage_dir: Sub-directory name inside .yosoi/. Defaults to 'fetch'.

        """
        self._dir = str(init_yosoi(storage_dir))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save(self, domain: str, fetcher: str, selector_level: str | None = None) -> None:
        """Persist the winning fetcher tier for *domain*.

        Args:
            domain: Bare domain string (e.g. 'finance.yahoo.com').
            fetcher: Tier name — one of 'simple', 'headless', 'headful'.
            selector_level: Optional highest selector strategy that worked.

        """
        if fetcher not in VALID_FETCHERS:
            logger.warning('FetchStrategyStorage.save: unknown fetcher %r for %s', fetcher, domain)
            return
        if selector_level is not None and selector_level not in VALID_SELECTOR_LEVELS:
            logger.warning('FetchStrategyStorage.save: unknown selector level %r for %s', selector_level, domain)
            selector_level = None

        filepath = self._filepath(domain)
        data = {
            'domain': domain,
            'fetcher': fetcher,
            'selector_level': selector_level,
            'discovered_at': datetime.now().isoformat(),
        }
        try:
            await atomic_write_json_async(filepath, data)
            logger.debug('Saved fetch strategy: %s -> %s', domain, fetcher)
        except OSError as e:
            logger.warning('Could not save fetch strategy for %s: %s', domain, e)

    async def load_strategy(self, domain: str) -> FetchStrategy | None:
        """Return the cached fetcher tier for *domain*, or None if unknown.

        Args:
            domain: Bare domain string (e.g. 'finance.yahoo.com').

        Returns:
            FetchStrategy, or None if not cached.

        """
        filepath = self._filepath(domain)
        if not await aiofiles.os.path.exists(filepath):
            return None
        try:
            async with aiofiles.open(filepath, encoding='utf-8') as f:
                data = json.loads(await f.read())
            fetcher = data.get('fetcher')
            if fetcher in VALID_FETCHERS:
                selector_level = data.get('selector_level')
                level = str(selector_level) if selector_level in VALID_SELECTOR_LEVELS else None
                return FetchStrategy(fetcher=str(fetcher), selector_level=level)
            logger.warning('Invalid fetcher value %r in cache for %s', fetcher, domain)
            return None
        except (OSError, json.JSONDecodeError) as e:
            logger.warning('Could not read fetch strategy for %s: %s', domain, e)
            return None

    async def load(self, domain: str) -> str | None:
        """Return the cached fetcher tier for *domain*, or None if unknown."""
        strategy = await self.load_strategy(domain)
        return strategy.fetcher if strategy is not None else None

    async def load_all_strategies(self) -> dict[str, FetchStrategy]:
        """Load every cached strategy into a domain → fetcher mapping.

        Called once on JSFetcher startup to pre-populate the in-memory cache.

        Returns:
            Dict mapping domain strings to strategy records.

        """
        result: dict[str, FetchStrategy] = {}
        if not await aiofiles.os.path.exists(self._dir):
            return result
        for filename in await aiofiles.os.listdir(self._dir):
            if not (filename.startswith('fetch_') and filename.endswith('.json')):
                continue
            filepath = os.path.join(self._dir, filename)
            try:
                async with aiofiles.open(filepath, encoding='utf-8') as f:
                    data = json.loads(await f.read())
                domain = data.get('domain')
                fetcher = data.get('fetcher')
                if domain and fetcher in VALID_FETCHERS:
                    selector_level = data.get('selector_level')
                    level = str(selector_level) if selector_level in VALID_SELECTOR_LEVELS else None
                    result[domain] = FetchStrategy(fetcher=str(fetcher), selector_level=level)
            except (OSError, json.JSONDecodeError):
                pass
        if result:
            logger.info('Loaded fetch strategy cache (%d domains)', len(result))
        return result

    async def load_all(self) -> dict[str, str]:
        """Load every cached fetcher tier into a domain → tier mapping."""
        return {domain: strategy.fetcher for domain, strategy in (await self.load_all_strategies()).items()}

    async def list_domains(self) -> list[str]:
        """Return all domains with a cached strategy, sorted alphabetically."""
        return sorted((await self.load_all()).keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filepath(self, domain: str) -> str:
        safe = safe_domain(domain)
        return os.path.join(self._dir, f'fetch_{safe}.json')
