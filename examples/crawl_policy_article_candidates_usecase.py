"""Policy-as-code example for live article-candidate crawling.

This example performs a small live crawl against the maintained qscrape.dev demo
target. It shows how an article-candidate crawl becomes a typed policy document that
can be checked before execution, then run through the public ``ys.crawl`` verb.
"""

from __future__ import annotations

import asyncio

from pydantic import ValidationError

import yosoi as ys


def conservative_article_archive_policy() -> ys.Policy:
    """A respectful host-scoped article-candidate crawl policy."""
    return ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(
            max_pages=100,
            max_depth=2,
            max_attempts=120,
            max_pages_per_host=100,
            crawl_session_id='qscrape-article-candidates-demo',
        ),
        scheduler=ys.SchedulerPolicy(
            max_workers=5,
            per_host_concurrency=1,
            politeness_delay=1.0,
            fetch_timeout_seconds=15.0,
            max_fetch_retries=2,
        ),
        safety=ys.CrawlSafety(
            respect_robots=False,
            allow_redirects=True,
            allowed_hosts=('qscrape.dev',),
            blocked_path_prefixes=('/login', '/account', '/admin'),
        ),
        escalation=ys.EscalationPolicy(
            allow_model_discovery=False,
            allow_paid_scrapers=False,
            max_llm_calls=0,
            max_paid_scraper_calls=0,
        ),
        path_planning=ys.PathPlanningPolicy(enabled=True, min_similarity=0.72, score_boost=0.20),
        target_contracts=(ys.CrawlTarget(name='NewsArticle'),),
        fetcher_type='simple',
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
        target_contracts=(ys.CrawlTarget(name='NewsArticle'),),
        fetcher_type='simple',
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


async def run_live_article_candidates() -> None:
    """Run a small live policy-driven article-candidate crawl."""
    policy = ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(max_pages=8, max_depth=1, max_attempts=10, crawl_session_id='live-articles-demo'),
        scheduler=ys.SchedulerPolicy(max_workers=2, per_host_concurrency=1, politeness_delay=0),
        safety=ys.CrawlSafety(
            respect_robots=False,
            allow_redirects=True,
            allowed_hosts=('qscrape.dev',),
            blocked_path_prefixes=('/login',),
        ),
        escalation=ys.EscalationPolicy(),
        path_planning=ys.PathPlanningPolicy(min_similarity=0.72, score_boost=0.20),
        target_contracts=(ys.CrawlTarget(name='NewsArticle'),),
        fetcher_type='simple',
    )

    summary = await ys.crawl(
        'https://qscrape.dev/l1/news/articles/',
        contracts=ys.NewsArticle,
        policy=policy,
        progress=False,
    )

    print('live article candidate run')
    ys.show(summary.candidates_for(ys.NewsArticle), title='NewsArticle crawl candidates')


async def amain() -> None:
    archive_policy = conservative_article_archive_policy()
    archive_check = ys.check_policy(archive_policy, seeds=('https://qscrape.dev/l1/news/articles',))
    print('article candidate crawl policy')
    print(archive_check.model_dump_json(indent=2))

    backlog_policy = direct_article_backlog_policy()
    backlog_check = ys.check_policy(backlog_policy)
    print('known article backlog policy')
    print(backlog_check.model_dump_json(indent=2))

    bad_policy_example()
    await run_live_article_candidates()


if __name__ == '__main__':
    asyncio.run(amain())
