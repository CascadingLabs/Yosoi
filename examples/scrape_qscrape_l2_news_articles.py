"""Scrape qscrape.dev L2 rendered news articles with the built-in NewsArticle contract.

Run:
    uv run python examples/scrape_qscrape_l2_news_articles.py

L2 renders the article cards with JavaScript. This example therefore uses the
auto JS waterfall fetcher; a plain HTTP fetcher will not see the final card grid.
"""

from __future__ import annotations

import asyncio

import yosoi as ys

URL = 'https://qscrape.dev/l2/news/articles'


async def main() -> None:
    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            scrape=ys.ScrapePolicy(fetcher_type='auto', selector_level=ys.SelectorLevel.XPATH),
            output=ys.OutputPolicy(quiet=False, plain_output=False),
        ),
    )

    if policy.model is None:
        ys.show('Scrape skipped: no model configured', format='plain')
        return

    articles = await ys.scrape(URL, ys.NewsArticle, policy=policy)
    ys.show(articles, title='NewsArticle')


if __name__ == '__main__':
    asyncio.run(main())
