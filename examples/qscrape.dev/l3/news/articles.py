"""Scrape qscrape.dev L3 island-rendered news article cards.

Run:
    uv run python examples/qscrape.dev/l3/news/articles.py
"""

from __future__ import annotations

import asyncio
import json
import os

import yosoi as ys

URL = 'https://qscrape.dev/l3/news/'


class ArticleSummary(ys.Contract):
    """One article assembled across qscrape.dev L3 framework islands."""

    headline: str = ys.Title(description='Article headline')
    author: str | None = ys.Author(default=None, description='Article author')
    published_at: str | None = ys.Datetime(default=None, description='Article publication date')
    excerpt: str = ys.BodyText(description='Short article summary')
    article_url: str | None = ys.Url(default=None, description='Link target for the article')


async def main() -> None:
    items = await ys.scrape(
        URL,
        ArticleSummary,
        model=os.getenv('YOSOI_MODEL') or None,
        fetcher_type='waterfall',
        selector_level=ys.SelectorLevel.XPATH,
        force=os.getenv('YOSOI_FORCE', '').lower() in {'1', 'true', 'yes'},
        quiet=False,
    )
    print(json.dumps(items, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
