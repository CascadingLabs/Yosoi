"""Per-domain JS action script cache — mirrors SelectorStorage for action fields."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import aiofiles
import aiofiles.os

from yosoi.utils.files import atomic_write_json_async, init_yosoi, safe_domain

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
    """All discovered JS scripts for one domain, keyed by contract field name."""

    domain: str
    fields: dict[str, JsScriptEntry]
    updated_at: str


class JsScriptStorage:
    """Saves and loads per-domain JS action scripts.

    Keyed by **domain** (not contract signature) so a field's script survives
    unrelated contract edits — parity with the per-domain selector cache (CAS-115).
    A cached script is reused only when its stored ``description`` still matches the
    field's current description; a changed description means the field's intent
    changed, so it is rediscovered.

    Storage location: ``.yosoi/js_scripts/js_<domain>.json``

    File format::

        {
          "domain": "shsboston.com",
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

    def _filepath(self, domain: str) -> str:
        safe = safe_domain(domain)
        return os.path.join(self._dir, f'js_{safe}.json')

    async def load(self, domain: str) -> JsScriptRecord | None:
        """Return the stored record for *domain*, or None."""
        filepath = self._filepath(domain)
        if not await aiofiles.os.path.exists(filepath):
            return None
        try:
            async with aiofiles.open(filepath, encoding='utf-8') as f:
                raw: dict[str, Any] = json.loads(await f.read())
            fields = {name: JsScriptEntry(**entry) for name, entry in raw.get('fields', {}).items()}
            return JsScriptRecord(
                domain=raw['domain'],
                fields=fields,
                updated_at=raw.get('updated_at', ''),
            )
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning('Corrupt JS script record for %s — ignoring: %s', domain, exc)
            return None

    async def save_entries(self, domain: str, entries: dict[str, JsScriptEntry]) -> None:
        """Persist (merge) the JS script entries for *domain*, keyed by field name."""
        existing = await self.load(domain)
        merged = dict(existing.fields) if existing else {}
        merged.update(entries)

        data: dict[str, Any] = {
            'domain': domain,
            'fields': {name: asdict(entry) for name, entry in merged.items()},
            'updated_at': _utc_now(),
        }
        try:
            await atomic_write_json_async(self._filepath(domain), data)
            logger.debug('Saved JS scripts for %s (%d fields)', domain, len(merged))
        except OSError as exc:
            logger.warning('Could not save JS scripts for %s: %s', domain, exc)

    async def get_scripts(self, domain: str, field_descriptions: Mapping[str, str] | None = None) -> dict[str, str]:
        """Return ``{field_name: script}`` for verified cached scripts.

        When ``field_descriptions`` is provided, a script is returned only if the
        field is requested AND its stored description still matches — so a field
        whose description changed is treated as stale (omitted ⇒ rediscover), and a
        field's script survives changes to *other* contract fields.
        """
        record = await self.load(domain)
        if record is None:
            return {}
        result: dict[str, str] = {}
        for name, entry in record.fields.items():
            if not (entry.verified and entry.script):
                continue
            if field_descriptions is not None:
                wanted = field_descriptions.get(name)
                if wanted is None or wanted != entry.description:
                    continue
            result[name] = entry.script
        return result
