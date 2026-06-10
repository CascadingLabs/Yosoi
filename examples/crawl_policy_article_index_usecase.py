"""Policy-as-code example for article-index crawling.

This example intentionally performs no network, browser, selector, or model
work. It shows how a large article-index crawl becomes a typed policy document
that can be checked before execution.
"""

from __future__ import annotations

import asyncio

from pydantic import ValidationError

import yosoi as ys
from yosoi.core.crawler import CrawlCoordinator
from yosoi.models.results import FetchResult


class InMemoryArticleFetcher:
    """Tiny fetcher for policy/crawler demonstration without network traffic."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        html = self.pages.get(url)
        if html is None:
            return FetchResult(url=url, html=None, block_reason='missing fixture')
        return FetchResult(url=url, html=html, status_code=200, fetch_time=0.001)


def conservative_sports_article_policy() -> ys.Policy:
    """A respectful multi-host article-index policy learned from the DFS spike."""
    return ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(
            max_pages=1_000,
            max_depth=2,
            max_attempts=1_200,
            max_pages_per_host=300,
            crawl_session_id='sports-article-index-demo',
        ),
        scheduler=ys.SchedulerPolicy(
            max_workers=5,
            per_host_concurrency=1,
            politeness_delay=1.0,
            fetch_timeout_seconds=15.0,
            max_fetch_retries=2,
        ),
        safety=ys.CrawlSafety(
            respect_robots=True,
            allowed_hosts=(
                'espn.com',
                'www.espn.com',
                'cbssports.com',
                'www.cbssports.com',
                'sports.yahoo.com',
            ),
            blocked_path_prefixes=('/login', '/account', '/cart', '/checkout'),
        ),
        escalation=ys.EscalationPolicy(
            allow_model_discovery=False,
            allow_paid_scrapers=False,
            max_llm_calls=0,
            max_paid_scraper_calls=0,
        ),
        fetcher_type='auto',
    )


def direct_article_backlog_policy() -> ys.Policy:
    """A policy for known article URLs where crawling expands no new links."""
    return ys.Policy.for_crawl(
        'crawl.local_single',
        budget=ys.CrawlBudget(
            max_pages=200_000,
            max_depth=0,
            max_attempts=220_000,
            max_pages_per_host=25_000,
            crawl_session_id='known-article-backlog-demo',
        ),
        scheduler=ys.SchedulerPolicy(
            max_workers=32,
            per_host_concurrency=1,
            politeness_delay=0.25,
            fetch_timeout_seconds=20.0,
            max_fetch_retries=2,
        ),
        safety=ys.CrawlSafety(respect_robots=True, allow_cross_domain=True),
        escalation=ys.EscalationPolicy(),
        fetcher_type='auto',
    )


def bad_policy_example() -> None:
    """Show that expensive invalid crawl configs fail before they can run."""
    try:
        ys.Policy.for_crawl(
            'crawl.conservative',
            scheduler=ys.SchedulerPolicy(max_workers=2, per_host_concurrency=3),
        )
    except ValidationError as exc:
        print(f'bad policy rejected: {exc.errors()[0]["msg"]}')


async def run_offline_article_index() -> None:
    """Run a local policy-driven article index crawl."""
    pages = {
        'https://www.espn.com/nfl/': """
            <main>
              <a href="/nfl/story/1">Story One</a>
              <a href="/nfl/story/2">Story Two</a>
              <a href="/login">Login</a>
              <a href="https://ads.example.com/ad/1">Ad</a>
            </main>
        """,
        'https://www.espn.com/nfl/story/1': '<article><h1>Story One</h1><p>Clean article body.</p></article>',
        'https://www.espn.com/nfl/story/2': '<article><h1>Story Two</h1><p>Clean article body.</p></article>',
    }
    policy = ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(max_pages=4, max_depth=1, max_attempts=4, crawl_session_id='offline-sports-demo'),
        scheduler=ys.SchedulerPolicy(max_workers=2, per_host_concurrency=1, politeness_delay=0),
        safety=ys.CrawlSafety(
            respect_robots=True,
            allowed_hosts=('www.espn.com',),
            blocked_path_prefixes=('/login',),
        ),
        escalation=ys.EscalationPolicy(),
    )
    check = ys.check_policy(policy, seeds=('https://www.espn.com/nfl/',))
    assert check.runtime is not None

    fetcher = InMemoryArticleFetcher(pages)
    summary = await CrawlCoordinator(fetcher=fetcher, config=check.runtime, persist_frontier=False).run()

    print('offline article index run')
    print(
        {
            'pages_fetched': summary.pages_fetched,
            'attempted_urls': summary.attempted_urls,
            'unique_urls_seen': summary.unique_urls_seen,
            'idle_worker_ratio': round(summary.idle_worker_ratio, 3),
            'outcome_lanes': summary.outcome_lanes,
        }
    )


async def amain() -> None:
    sports_policy = conservative_sports_article_policy()
    sports_check = ys.check_policy(sports_policy, seeds=('https://www.espn.com/nfl/',))
    print('sports article index policy')
    print(sports_check.model_dump_json(indent=2))

    backlog_policy = direct_article_backlog_policy()
    backlog_check = ys.check_policy(backlog_policy)
    print('known article backlog policy')
    print(backlog_check.model_dump_json(indent=2))

    bad_policy_example()
    await run_offline_article_index()


if __name__ == '__main__':
    asyncio.run(amain())
