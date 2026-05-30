"""Detect Alita health AI embed and competitor chat widgets across N URLs.

Uses ``ys.js()`` — a JS program evaluated in the live browser tab after page
load — to inspect script/iframe sources without CSS selector discovery.  No
LLM is involved in extraction; the JS probe runs deterministically every time.

Run (single URL):
    uv run python experiments/alita_tech_detect.py

Run (batch from file):
    ALITA_URLS_FILE=my_urls.txt uv run python experiments/alita_tech_detect.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import yosoi as ys
from yosoi.utils.files import init_yosoi, is_initialized

# ── Config ─────────────────────────────────────────────────────────────────────

MODEL = ys.claude_sdk(os.getenv('CLAUDE_SDK_MODEL', 'claude-sonnet-4-6'))
FETCHER = os.getenv('ALITA_FETCHER', 'headless')

DEFAULT_URLS = [
    'https://shsboston.com/',
]

URLS_FILE = os.getenv('ALITA_URLS_FILE', '')

# ── JS probe ───────────────────────────────────────────────────────────────────

_DETECT_JS = """
(() => {
  const srcs = [...document.querySelectorAll('script[src],iframe[src]')]
                 .map(e => e.src || e.getAttribute('src') || '');

  const alitaEmbedSrc  = srcs.find(s => s.includes('alita-embed')) || null;
  const alitaIframeSrc = srcs.find(s => s.includes('hub.alitahealth.ai')) || null;

  const alitaOrg = alitaIframeSrc
    ? (new URL(alitaIframeSrc).searchParams.get('org') || null)
    : null;

  const COMPETITORS = {
    comm100:   'Comm100',
    intercom:  'Intercom',
    'drift.com': 'Drift',
    tidio:     'Tidio',
    freshchat: 'Freshchat',
    freshworks: 'Freshworks',
    zendesk:   'Zendesk',
    'tawk.to': 'Tawk.to',
    hubspot:   'HubSpot',
    'ada.support': 'Ada',
  };

  const competitors = Object.entries(COMPETITORS)
    .filter(([k]) => srcs.some(s => s.toLowerCase().includes(k)))
    .map(([, v]) => v);

  return {
    has_alita_embed:  !!alitaEmbedSrc,
    has_alita_agent:  !!alitaIframeSrc,
    alita_org_id:     alitaOrg,
    alita_embed_src:  alitaEmbedSrc,
    competitors,
  };
})()
"""

# ── Contract ──────────────────────────────────────────────────────────────────


class AlitaPresence(ys.Contract):
    """Tech-stack signals for Alita health AI and competitor chat widgets."""

    signals: dict = ys.js(  # type: ignore[assignment]
        _DETECT_JS,
        default=None,
        description='Tech detection signals from live DOM — has_alita_embed, competitors, etc.',
    )


# ── Display helpers ────────────────────────────────────────────────────────────


def _hr(char: str = '─', width: int = 72) -> None:
    print(char * width)


def _print_result(url: str, item: dict[str, Any]) -> None:
    signals: dict[str, Any] = item.get('signals') or {}
    has_embed = signals.get('has_alita_embed', False)
    has_agent = signals.get('has_alita_agent', False)
    org = signals.get('alita_org_id') or '—'
    competitors = signals.get('competitors') or []

    alita_status = '✓ Alita' if (has_embed or has_agent) else '✗ no Alita'
    comp_str = ', '.join(competitors) if competitors else '—'

    print(f'  URL        {url}')
    print(f'  Alita      {alita_status}  (embed={has_embed}  agent={has_agent}  org={org})')
    print(f'  Competitors {comp_str}')
    _hr()


# ── Runner ────────────────────────────────────────────────────────────────────


async def run(urls: list[str]) -> None:  # noqa: D103
    if not is_initialized():
        init_yosoi()

    pipeline = ys.Pipeline(
        MODEL,
        contract=AlitaPresence,
        output_format=['json'],
        selector_level=ys.SelectorLevel.CSS,
    )

    _hr('═')
    print(f'  Alita tech-detect — {len(urls)} URL(s)  fetcher={FETCHER}')
    _hr('═')

    for url in urls:
        _hr()
        items: list[dict[str, Any]] = [
            item
            async for item in pipeline.scrape(
                url,
                fetcher_type=FETCHER,
                force=False,
            )
        ]
        if items:
            _print_result(url, items[0])
        else:
            print(f'  {url}  → (no result)')
            _hr()

    print(
        json.dumps(
            [{'url': u} for u in urls],
            indent=2,
        )
    )


# ── Entry point ────────────────────────────────────────────────────────────────


def _load_urls() -> list[str]:
    if URLS_FILE and Path(URLS_FILE).exists():
        return [
            line.strip()
            for line in Path(URLS_FILE).read_text().splitlines()
            if line.strip() and not line.startswith('#')
        ]
    return DEFAULT_URLS


async def main() -> None:  # noqa: D103
    await run(_load_urls())


if __name__ == '__main__':
    asyncio.run(main())
