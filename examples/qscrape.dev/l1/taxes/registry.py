"""Scrape the qscrape.dev L1 Arcane Registry of Deeds landing page.

Run:
    uv run python examples/qscrape.dev/l1/taxes/registry.py
"""

from __future__ import annotations

import asyncio
import json
import os

import yosoi as ys

URL = 'https://qscrape.dev/l1/taxes/'


class RegistryService(ys.Contract):
    """One public service listed on the Arcane Registry of Deeds page."""

    root = ys.css('.formTable tr')

    service_name: str = ys.Title(description='Registry service name')
    description: str = ys.BodyText(description='What the service lets users do')
    service_url: str | None = ys.Url(default=None, description='Link target for the service')


async def main() -> None:
    items = await ys.scrape(
        URL,
        RegistryService,
        model=os.getenv('YOSOI_MODEL') or None,
        fetcher_type='simple',
        force=os.getenv('YOSOI_FORCE', '').lower() in {'1', 'true', 'yes'},
        quiet=False,
    )
    print(json.dumps(items, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
