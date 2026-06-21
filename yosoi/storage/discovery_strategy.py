"""Per-(domain, contract) discovery-mode persistence.

Mirrors :class:`~yosoi.storage.strategy.FetchStrategyStorage`: once a page proves
it needs interaction-driven MCP discovery (a required field is unreachable from
the rendered snapshot), record that so later runs skip the wasted static attempt
and escalate straight away. Keyed by contract signature too, so different
contracts on one domain don't poison each other's decision.

Storage location: ``.yosoi/discovery/discovery_<domain>__<contract_sig>.json``
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Literal

from yosoi.utils.files import atomic_write_json_async, init_yosoi, safe_domain

logger = logging.getLogger(__name__)

DiscoveryMode = Literal['static', 'mcp']
_VALID_MODES = frozenset({'static', 'mcp'})


class DiscoveryStrategyStorage:
    """Saves and loads the chosen discovery mode per (domain, contract)."""

    def __init__(self, storage_dir: str = 'discovery') -> None:
        """Initialise storage under ``.yosoi/discovery/``."""
        self._dir = str(init_yosoi(storage_dir))

    async def save(self, domain: str, contract_sig: str, mode: DiscoveryMode) -> None:
        """Persist the discovery mode for ``(domain, contract_sig)``."""
        if mode not in _VALID_MODES:
            logger.warning('DiscoveryStrategyStorage.save: unknown mode %r for %s', mode, domain)
            return
        data = {
            'domain': domain,
            'contract_signature': contract_sig,
            'mode': mode,
            'discovered_at': datetime.now(timezone.utc).isoformat(),
        }
        try:
            await atomic_write_json_async(self._filepath(domain, contract_sig), data)
            logger.debug('Saved discovery strategy: %s -> %s', domain, mode)
        except OSError as e:
            logger.warning('Could not save discovery strategy for %s: %s', domain, e)

    async def load(self, domain: str, contract_sig: str) -> DiscoveryMode | None:
        """Return the cached discovery mode, or None if unknown/corrupt."""
        return self._load_sync(domain, contract_sig)

    def _load_sync(self, domain: str, contract_sig: str) -> DiscoveryMode | None:
        filepath = self._filepath(domain, contract_sig)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, encoding='utf-8') as f:
                data = json.loads(f.read())
        except (OSError, json.JSONDecodeError) as e:
            logger.warning('Could not read discovery strategy for %s: %s', domain, e)
            return None
        mode = data.get('mode')
        if mode in _VALID_MODES:
            return mode  # type: ignore[no-any-return]
        return None

    def _filepath(self, domain: str, contract_sig: str) -> str:
        safe = safe_domain(domain)
        safe_sig = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in contract_sig)
        return os.path.join(self._dir, f'discovery_{safe}__{safe_sig}.json')
