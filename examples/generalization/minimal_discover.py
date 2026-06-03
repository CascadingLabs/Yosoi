"""The whole thing: AI-discover selectors from a contract once, reuse across 7 URLs — one call."""

import asyncio

import yosoi as ys

URLS = [
    'https://finance.yahoo.com/news/anthropic-more-valuable-than-openai-in-latest-funding-round-184115376.html',
    'https://finance.yahoo.com/news/a-jobs-report-more-big-chip-earnings-and-sticky-inflation-what-to-watch-this-week-105149903.html',
    'https://finance.yahoo.com/news/review-the-2026-nissan-leaf-ev-arrives-at-the-right-moment-173733205.html',
    'https://finance.yahoo.com/news/schwab-ceo-says-his-firm-will-attract-new-customers-with-wealth-building-instead-of-meme-coins-and-gambling-143445773.html',
    'https://finance.yahoo.com/news/theres-mania-strategists-weigh-in-on-looming-spacex-ipo-130000210.html',
    'https://finance.yahoo.com/news/stocks-and-earnings-surge-and-iran-deal-may-be-imminent-what-to-watch-this-week-114338066.html',
    'https://finance.yahoo.com/news/anthropic-debuts-flagship-claude-opus-48-ai-model-as-ipo-race-with-openai-heats-up-170000527.html',
]

for article in asyncio.run(ys.scrape(URLS, ys.NewsArticle, model=ys.claude_sdk())):
    print(article['headline'], '·', article['date'])
