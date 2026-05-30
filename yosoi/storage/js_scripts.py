"""Per-domain JS action script cache — mirrors SelectorStorage for action fields."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import aiofiles
import aiofiles.os

from yosoi.utils.files import atomic_write_json_async, init_yosoi

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JsScriptEntry:
    """A verified JS extraction script for one contract field on one domain."""

    script: str
    description: str
    discovered_at: str
    verified: bool
    model: str | None
    attempts: int


@dataclass
class JsScriptRecord:
    """All discovered JS scripts for one (domain, contract_signature) pair."""

    domain: str
    contract_signature: str
    fields: dict[str, JsScriptEntry]
    updated_at: str


class JsScriptStorage:
    """Saves and loads per-domain JS action scripts.

    Storage location: .yosoi/js_scripts/js_<domain>_<contract_sig>.json

    File format::

        {
          "domain": "shsboston.com",
          "contract_signature": "abc123",
          "fields": {
            "signals": {
              "script": "(() => ({has_alita: ...}))()",
              "description": "Tech detection signals",
              "discovered_at": "2026-05-30T...",
              "verified": true,
              "model": "claude-sonnet-4-6",
              "attempts": 2
            }
          },
          "updated_at": "..."
        }

    """

    def __init__(self, storage_dir: str = 'js_scripts') -> None:
        """Initialise storage under .yosoi/js_scripts/."""
        self._dir = str(init_yosoi(storage_dir))

    def _filepath(self, domain: str, contract_sig: str) -> str:
        safe_domain = domain.replace('.', '_').replace('/', '_').replace(':', '_')
        safe_sig = contract_sig[:16]
        return os.path.join(self._dir, f'js_{safe_domain}_{safe_sig}.json')

    async def load(self, domain: str, contract_sig: str) -> JsScriptRecord | None:
        """Return stored record for (domain, contract_sig), or None."""
        filepath = self._filepath(domain, contract_sig)
        if not await aiofiles.os.path.exists(filepath):
            return None
        try:
            async with aiofiles.open(filepath, encoding='utf-8') as f:
                raw: dict[str, Any] = json.loads(await f.read())
            fields = {name: JsScriptEntry(**entry) for name, entry in raw.get('fields', {}).items()}
            return JsScriptRecord(
                domain=raw['domain'],
                contract_signature=raw['contract_signature'],
                fields=fields,
                updated_at=raw.get('updated_at', ''),
            )
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning('Corrupt JS script record for %s — ignoring: %s', domain, exc)
            return None

    async def save_entries(
        self,
        domain: str,
        contract_sig: str,
        entries: dict[str, JsScriptEntry],
    ) -> None:
        """Persist (or merge into) the JS script record for (domain, contract_sig)."""
        existing = await self.load(domain, contract_sig)
        merged = dict(existing.fields) if existing else {}
        merged.update(entries)

        record = JsScriptRecord(
            domain=domain,
            contract_signature=contract_sig,
            fields=merged,
            updated_at=_utc_now(),
        )
        data: dict[str, Any] = {
            'domain': record.domain,
            'contract_signature': record.contract_signature,
            'fields': {name: asdict(entry) for name, entry in record.fields.items()},
            'updated_at': record.updated_at,
        }
        try:
            await atomic_write_json_async(self._filepath(domain, contract_sig), data)
            logger.debug('Saved JS scripts for %s (%d fields)', domain, len(merged))
        except OSError as exc:
            logger.warning('Could not save JS scripts for %s: %s', domain, exc)

    async def get_scripts(self, domain: str, contract_sig: str) -> dict[str, str]:
        """Return {field_name: script} for all verified cached scripts."""
        record = await self.load(domain, contract_sig)
        if record is None:
            return {}
        return {name: entry.script for name, entry in record.fields.items() if entry.verified and entry.script}
