"""Use the public ys.map API for the same site-inventory use case as `yosoi map`.

Run:
    uv run python examples/api_design/map_api.py

Equivalent CLI:
    uv run yosoi map qscrape.dev --max-sitemaps 5 --max-urls 50 --json
"""

from __future__ import annotations

import asyncio

import yosoi as ys

SITE = 'qscrape.dev'


async def main() -> None:
    result = await ys.map(
        SITE,
        max_sitemaps=5,
        max_urls=50,
        include_robots=True,
        include_default_sitemaps=True,
    )

    print(f'{result.root_host}: {len(result.urls)} URLs from {len(result.sitemaps)} sitemap probes')
    for entry in result.urls[:10]:
        print(f'- {entry.url}')

    # For machine output matching `yosoi map --json`, use:
    # print(result.model_dump_json(indent=2))


if __name__ == '__main__':
    asyncio.run(main())
