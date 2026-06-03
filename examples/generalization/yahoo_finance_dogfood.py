"""Live dogfood: one ``ys.scrape`` over a LIST of Yahoo Finance articles.

The contract is the only thing we author; discovery owns the selectors. Passing a
list lets ``ys.scrape`` do it on its own — discover the recipe once on the first
URL, then replay the rest concurrently as cache hits, scoring each into the reuse
ledger. Content lands in ``.yosoi/content/``; the reuse decisions land in the
ledger. We don't print a report here — the ``yosoi-generalization`` CLI explains it.

    uv run python examples/generalization/yahoo_finance_dogfood.py
    uv run yosoi-generalization summary
    uv run yosoi-generalization review list --all --json

Discovery runs on the local Claude SDK (``ys.claude_sdk``): no API key.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault('YOSOI_REUSE_HINT', '1')
os.environ.setdefault('YOSOI_REUSE_PROFILE', 'balanced')

import yosoi as ys

# First URL is the discovery seed; the rest reuse the cached recipe concurrently.
URLS = [
    'https://finance.yahoo.com/news/anthropic-more-valuable-than-openai-in-latest-funding-round-184115376.html',
    'https://finance.yahoo.com/news/a-jobs-report-more-big-chip-earnings-and-sticky-inflation-what-to-watch-this-week-105149903.html',
    'https://finance.yahoo.com/news/review-the-2026-nissan-leaf-ev-arrives-at-the-right-moment-173733205.html',
    'https://finance.yahoo.com/news/schwab-ceo-says-his-firm-will-attract-new-customers-with-wealth-building-instead-of-meme-coins-and-gambling-143445773.html',
    'https://finance.yahoo.com/news/theres-mania-strategists-weigh-in-on-looming-spacex-ipo-130000210.html',
    'https://finance.yahoo.com/news/stocks-and-earnings-surge-and-iran-deal-may-be-imminent-what-to-watch-this-week-114338066.html',
    'https://finance.yahoo.com/news/anthropic-debuts-flagship-claude-opus-48-ai-model-as-ipo-race-with-openai-heats-up-170000527.html',
]


async def main() -> None:
    articles = await ys.scrape(URLS, ys.NewsArticle, model=ys.claude_sdk(), save_formats=('json',))
    print(f'{len(articles)} articles from {len(URLS)} URLs → .yosoi/content/')
    print('explain the reuse with:  uv run yosoi-generalization summary  (or: review list --all --json)')


if __name__ == '__main__':
    asyncio.run(main())
