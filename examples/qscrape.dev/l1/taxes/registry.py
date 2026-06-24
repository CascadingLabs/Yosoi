"""Scrape the qscrape.dev L1 Arcane Registry of Deeds landing page.

Run:
    uv run python examples/qscrape.dev/l1/taxes/registry.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys

URL = 'https://qscrape.dev/l1/taxes/'


class RegistryService(ys.Contract):
    """One public service listed on the Arcane Registry of Deeds page."""

    service_name: str = ys.Title(description='Registry service name')
    description: str = ys.BodyText(description='What the service lets users do')
    service_url: str | None = ys.Url(description='Link target for the service')


async def main() -> None:
    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            scrape=ys.ScrapePolicy(fetcher_type='simple'),
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    items = await ys.scrape(
        URL,
        RegistryService,
        policy=policy,
    )
    ys.show(items)


if __name__ == '__main__':
    asyncio.run(main())
