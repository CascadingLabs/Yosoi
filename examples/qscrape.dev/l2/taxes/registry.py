"""Scrape the qscrape.dev L2 JavaScript-rendered Registry of Deeds page.

Run:
    uv run python examples/qscrape.dev/l2/taxes/registry.py
"""

from __future__ import annotations

import asyncio
import json
import os

import yosoi as ys

URL = 'https://qscrape.dev/l2/taxes/'


class RegistryService(ys.Contract):
    """One public service listed on the JS-rendered Registry of Deeds page."""

    service_name: str = ys.Title(description='Registry service name')
    description: str = ys.BodyText(description='What the service lets users do')
    service_url: str | None = ys.Url(default=None, description='Link target for the service')


async def main() -> None:
    items = await ys.scrape(
        URL,
        RegistryService,
        model=os.getenv('YOSOI_MODEL') or None,
        fetcher_type='waterfall',
        selector_level=ys.SelectorLevel.XPATH,
        force=os.getenv('YOSOI_FORCE', '').lower() in {'1', 'true', 'yes'},
        quiet=False,
    )
    print(json.dumps(items, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
