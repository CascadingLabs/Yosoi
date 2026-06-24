"""Scrape qscrape.dev L2 JavaScript-rendered news article cards.

Run:
    uv run python examples/qscrape.dev/l2/news/articles.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys

URL = 'https://qscrape.dev/l2/news/articles'


class ArticleSummary(ys.Contract):
    """One article card in the JS-rendered qscrape.dev L2 news archive."""

    headline: str = ys.Title(description='Article headline')
    author: str | None = ys.Author(description='Article author')
    published_at: str | None = ys.Datetime(description='Article publication date')
    excerpt: str = ys.BodyText(description='Short article summary')
    article_url: str | None = ys.Url(description='Link target for the article')


async def main() -> None:
    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            scrape=ys.ScrapePolicy(selector_level=ys.SelectorLevel.XPATH),
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
