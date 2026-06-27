"""Scrape one qscrape.dev L1 Mountainhome Herald article with OpenCode discovery.

Run:
    YOSOI_MODEL=opencode:openai/gpt-5.3-codex-spark \
    YOSOI_DISCOVERY_MODE=mcp \
    YOSOI_FORCE=1 \
    uv run python examples/qscrape.dev/l1/news/article_opencode.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys

URL = (
    'https://qscrape.dev/l1/news/article/'
    '?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-008%26HASH%3Dqdh75qk96wdXXXNNNXXXtR7vYw1hF3dGXXXNNNXXX'
)


class NewsArticle(ys.Contract):
    """One rendered qscrape.dev Mountainhome Herald article."""

    headline: str = ys.Title(description='Article headline')
    author: str | None = ys.Author(description='Article author or byline')
    date: str | None = ys.Datetime(description='Article publication date')
    category: str | None = ys.Field(description='Article category or section')
    body_text: str = ys.BodyText(description='Article body text')


async def main() -> None:
    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            scrape=ys.ScrapePolicy(fetcher_type='headless'),
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    item = await ys.scrape(URL, NewsArticle, policy=policy)
    ys.show(item)


if __name__ == '__main__':
    asyncio.run(main())
