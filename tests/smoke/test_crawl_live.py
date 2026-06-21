"""Opt-in live smoke test for the public crawl candidate surface."""

from __future__ import annotations

import os

import pytest

import yosoi as ys

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.getenv('YOSOI_LIVE_SMOKE') != '1',
        reason='set YOSOI_LIVE_SMOKE=1 to run live crawl smoke tests',
    ),
]


@pytest.mark.asyncio
async def test_live_crawl_produces_newsarticle_candidates() -> None:
    policy = ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(max_pages=8, max_depth=1, max_attempts=10),
        scheduler=ys.SchedulerPolicy(max_workers=2, per_host_concurrency=1, politeness_delay=0.25),
        safety=ys.CrawlSafety(
            respect_robots=False,
            allow_redirects=True,
            allowed_hosts=('qscrape.dev',),
            blocked_path_prefixes=('/login', '/account'),
        ),
        path_planning=ys.PathPlanningPolicy(min_similarity=0.72, score_boost=0.25),
        fetcher_type='simple',
    )

    summary = await ys.crawl(
        'https://qscrape.dev/l1/news/articles/',
        contracts=ys.NewsArticle,
        policy=policy,
        progress=False,
    )

    candidates = summary.candidates_for(ys.NewsArticle, limit=5)
    assert summary.pages_fetched >= 1
    assert candidates
    assert all(candidate.contract == 'NewsArticle' for candidate in candidates)
    assert all(candidate.scrape_verified is False for candidate in candidates)
