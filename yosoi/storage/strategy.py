"""Per-domain fetcher strategy persistence.

Saves which fetcher tier worked for each domain so subsequent runs skip
the waterfall and go straight to the right tier.

Storage location: .yosoi/fetch/fetch_<domain>.json

File format::

    {
      "domain": "finance.yahoo.com",
      "fetcher": "headful",
      "discovered_at": "2026-03-21T22:49:05"
    }

Valid fetcher values: "simple", "headless", "headful"
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from yosoi.utils.files import init_yosoi

logger = logging.getLogger(__name__)

VALID_FETCHERS = frozenset({'simple', 'headless', 'headful'})


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

    def save(self, domain: str, fetcher: str) -> None:
        """Persist the winning fetcher tier for *domain*.

        Args:
            domain: Bare domain string (e.g. 'finance.yahoo.com').
            fetcher: Tier name — one of 'simple', 'headless', 'headful'.

        """
        if fetcher not in VALID_FETCHERS:
            logger.warning('FetchStrategyStorage.save: unknown fetcher %r for %s', fetcher, domain)
            return

        filepath = self._filepath(domain)
        data = {
            'domain': domain,
            'fetcher': fetcher,
            'discovered_at': datetime.now().isoformat(),
        }
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            logger.debug('Saved fetch strategy: %s -> %s', domain, fetcher)
        except OSError as e:
            logger.warning('Could not save fetch strategy for %s: %s', domain, e)

    def load(self, domain: str) -> str | None:
        """Return the cached fetcher tier for *domain*, or None if unknown.

        Args:
            domain: Bare domain string (e.g. 'finance.yahoo.com').

        Returns:
            Tier name ('simple', 'headless', 'headful'), or None if not cached.

        """
        filepath = self._filepath(domain)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, encoding='utf-8') as f:
                data = json.load(f)
            fetcher = data.get('fetcher')
            if fetcher in VALID_FETCHERS:
                return fetcher
            logger.warning('Invalid fetcher value %r in cache for %s', fetcher, domain)
            return None
        except (OSError, json.JSONDecodeError) as e:
            logger.warning('Could not read fetch strategy for %s: %s', domain, e)
            return None

    def load_all(self) -> dict[str, str]:
        """Load every cached strategy into a domain → fetcher mapping.

        Called once on JSFetcher startup to pre-populate the in-memory cache.

        Returns:
            Dict mapping domain strings to tier names.

        """
        result: dict[str, str] = {}
        if not os.path.exists(self._dir):
            return result
        for filename in os.listdir(self._dir):
            if not (filename.startswith('fetch_') and filename.endswith('.json')):
                continue
            filepath = os.path.join(self._dir, filename)
            try:
                with open(filepath, encoding='utf-8') as f:
                    data = json.load(f)
                domain = data.get('domain')
                fetcher = data.get('fetcher')
                if domain and fetcher in VALID_FETCHERS:
                    result[domain] = fetcher
            except (OSError, json.JSONDecodeError):
                pass
        if result:
            logger.info('Loaded fetch strategy cache (%d domains)', len(result))
        return result

    def list_domains(self) -> list[str]:
        """Return all domains with a cached strategy, sorted alphabetically."""
        return sorted(self.load_all().keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filepath(self, domain: str) -> str:
        safe = domain.replace('.', '_').replace('/', '_')
        return os.path.join(self._dir, f'fetch_{safe}.json')
