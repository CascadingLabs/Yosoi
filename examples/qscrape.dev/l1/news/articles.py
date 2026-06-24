"""Scrape the qscrape.dev L1 Mountainhome Herald article archive.

Run:
    uv run python examples/qscrape.dev/l1/news/articles.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys

URL = 'https://qscrape.dev/l1/news/articles'


class ArticleSummary(ys.Contract):
    """One row in the static qscrape.dev L1 news article archive."""

    published_at: str = ys.Datetime(description='Article publication date')
    category: str = ys.Field(description='Article category')
    headline: str = ys.Title(description='Article headline')
    author: str = ys.Author(description='Article author')
    excerpt: str = ys.BodyText(description='Short article summary')


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
        ArticleSummary,
        policy=policy,
    )
    ys.show(items)


if __name__ == '__main__':
    asyncio.run(main())
