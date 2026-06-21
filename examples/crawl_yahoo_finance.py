"""Find Yahoo Finance articles with crawl, then scrape the ranked index.

Run:
    uv run python examples/crawl_yahoo_finance.py

Crawl is separate from scrape: the crawl builds ``NewsArticle`` scrape
candidates, then scrape extracts those pages when a model is configured. The
policy below only tweaks crawl levers: budget, safety, scheduler, and fetcher.
"""

from __future__ import annotations

import asyncio
import os

import yosoi as ys

SEEDS = 'https://finance.yahoo.com/news/'


def finance_news_crawl_policy(
    *,
    max_pages: int = 8,
    max_depth: int = 2,
    max_attempts: int = 80,
    politeness_delay: float = 0.25,
) -> ys.Policy:
    return ys.Policy.for_crawl(
        'crawl.seed_hunt',
        budget=ys.CrawlBudget(
            max_pages=max_pages,
            max_depth=max_depth,
            max_attempts=max_attempts,
            max_pages_per_host=max_pages,
            crawl_session_id='yahoo-finance-news-candidates',
        ),
        scheduler=ys.SchedulerPolicy(
            max_workers=3,
            per_host_concurrency=1,
            politeness_delay=politeness_delay,
            fetch_timeout_seconds=15.0,
            max_fetch_retries=1,
        ),
        safety=ys.CrawlSafety(
            respect_robots=True,
            allow_redirects=False,
            allowed_hosts=('finance.yahoo.com',),
            blocked_path_prefixes=(
                '/account',
                '/about',
                '/calendar',
                '/chart',
                '/community',
                '/login',
                '/personal-finance',  # keep this market/news focused; skip evergreen consumer-finance guides
                '/portfolios',
                '/quote',
                '/research-hub',
                '/screener',
                '/video',
                '/topic',
                '/videos',
            ),
        ),
        fetcher_type='simple',
    )


async def find_finance_article_urls(*, limit: int = 12) -> tuple[list[str], ys.CrawlRunSummary, ys.Policy]:
    policy = ys.Policy.cascade(ys.Policy.from_env(), finance_news_crawl_policy())
    summary = await ys.crawl(SEEDS, contracts=ys.NewsArticle, limit=limit, policy=policy, progress=False)
    return summary.urls_for(ys.NewsArticle, limit=limit), summary, policy


async def scrape_articles(pages: list[str], policy: ys.Policy) -> object:
    if not pages:
        return []
    return await ys.scrape(pages, ys.NewsArticle, policy=policy)


async def main() -> None:
    urls, summary, policy = await find_finance_article_urls(limit=12)
    ys.show(summary.candidates_for(ys.NewsArticle, limit=12))

    try:
        articles = await scrape_articles(urls, policy)
    except ValueError as exc:
        if 'No model specified' not in str(exc):
            raise
        ys.show('Scrape skipped: no model configured', format='plain')
    else:
        ys.show(articles, title='NewsArticle scrape')

    if os.getenv('YOSOI_CRAWL_DEBUG') == '1':
        ys.show(summary, title='Crawl debug')


if __name__ == '__main__':
    asyncio.run(main())
