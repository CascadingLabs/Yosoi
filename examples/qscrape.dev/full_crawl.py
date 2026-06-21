"""Crawl qscrape.dev, score pages for four contracts, then scrape the best matches.

Run URL discovery only:
    YOSOI_FULL_CRAWL_URLS_ONLY=1 uv run python examples/qscrape.dev/full_crawl.py

Run crawl + scrape:
    YOSOI_MODEL=groq:llama-3.3-70b-versatile uv run python examples/qscrape.dev/full_crawl.py

Set ``YOSOI_FULL_CRAWL_SCRAPE_URLS`` when you want to scrape more than the top
candidate per contract. The default keeps discovery to roughly one scrape target
per contract, so a cold run should need as few LLM discoveries as possible.
"""

from __future__ import annotations

import asyncio
import os

import yosoi as ys

SEED = 'https://qscrape.dev/'
URLS_ONLY = os.getenv('YOSOI_FULL_CRAWL_URLS_ONLY', '').lower() in {'1', 'true', 'yes'}
SCRAPE_URLS_PER_CONTRACT = int(os.getenv('YOSOI_FULL_CRAWL_SCRAPE_URLS', '1'))


class NewsArticle(ys.Contract):
    """One qscrape.dev Mountainhome Herald article/archive row."""

    published_at: str = ys.Datetime(description='Article publication date')
    category: str = ys.Field(description='Article category')
    headline: str = ys.Title(description='Article headline')
    author: str = ys.Author(description='Article author')
    excerpt: str = ys.BodyText(description='Short article summary')


class Product(ys.Contract):
    """One qscrape.dev e-shop product card."""

    name: str = ys.Title(description='Product name')
    category: str = ys.Field(description='Product category label')
    price: float = ys.Price(description='Product price as a number')
    rating: int = ys.Rating(as_float=True, description='Visible star rating as a 1-5 score')
    reviews_count: int | None = ys.Field(description='Number of product reviews')
    availability: str = ys.Field(description='Stock status')


class GameScore(ys.Contract):
    """One qscrape.dev ScoreTap match or standings row."""

    team_a: str = ys.Field(description='First team or player name')
    team_b: str = ys.Field(description='Second team or player name')
    score: str = ys.Field(description='Displayed score or result')
    status: str | None = ys.Field(description='Match state, round, or time')


class TaxInformation(ys.Contract):
    """One qscrape.dev Arcane Registry of Deeds public service."""

    service_name: str = ys.Title(description='Registry service name')
    description: str = ys.BodyText(description='What the service lets users do')
    service_url: str | None = ys.Url(description='Link target for the service')


CONTRACTS = [NewsArticle, Product, GameScore, TaxInformation]


async def main() -> None:
    crawl_policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            crawl=ys.CrawlPolicy(
                budget=ys.CrawlBudget(max_pages=200, max_depth=4, max_attempts=260),
                scheduler=ys.SchedulerPolicy(
                    max_workers=4,
                    per_host_concurrency=4,
                    politeness_delay=0,
                    fetch_timeout_seconds=5,
                    max_fetch_retries=1,
                ),
                safety=ys.CrawlSafety(
                    respect_robots=False,
                    allow_redirects=True,
                    allowed_hosts=('qscrape.dev',),
                    blocked_path_prefixes=('/cdn-cgi/',),
                ),
                escalation=ys.EscalationPolicy(
                    allow_model_discovery=not URLS_ONLY,
                    max_llm_calls=0 if URLS_ONLY else len(CONTRACTS),
                ),
                scrape_contracts=not URLS_ONLY,
                scrape_url_limit_per_contract=SCRAPE_URLS_PER_CONTRACT,
                fetcher_type='auto',
            ),
        ),
        ys.Policy(
            scrape=ys.ScrapePolicy(fetcher_type='auto', max_concurrency=4),
            output=ys.OutputPolicy(quiet=False),
        ),
    )

    summary = await ys.crawl(SEED, contracts=CONTRACTS, policy=crawl_policy)
    ys.show(summary)

    urls_by_contract = {
        contract.__name__: summary.urls_for(contract, limit=SCRAPE_URLS_PER_CONTRACT) for contract in CONTRACTS
    }
    ys.show(urls_by_contract, title='Selected scrape URLs')

    if not URLS_ONLY:
        ys.show(summary.scraped_content, title='Scraped content')


if __name__ == '__main__':
    asyncio.run(main())
