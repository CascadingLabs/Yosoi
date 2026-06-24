"""Opt-in live smoke test for the public crawl representative URL surface."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

import yosoi as ys

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.getenv('YOSOI_LIVE_SMOKE') != '1',
        reason='set YOSOI_LIVE_SMOKE=1 to run live crawl smoke tests',
    ),
]


def test_qscrape_full_crawl_example_completes_with_docker_cdp() -> None:
    env = {
        **os.environ,
        'PYTHONPATH': '.',
        'YOSOI_CHROME_WS_URLS': os.getenv('YOSOI_CHROME_WS_URLS', 'http://127.0.0.1:9222,http://127.0.0.1:9223'),
    }

    result = subprocess.run(
        [sys.executable, 'examples/qscrape.dev/full_crawl.py'],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert 'Crawl summary' in output
    assert 'Selected neutral scrape target URLs' in output


@pytest.mark.asyncio
async def test_live_crawl_produces_representative_urls() -> None:
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
        fetcher_type='simple',
    )

    summary = await ys.crawl(
        'https://qscrape.dev/l1/news/articles/',
        contracts=ys.NewsArticle,
        policy=policy,
        progress=False,
    )

    representatives = summary.representative_urls(limit=5)
    assert summary.pages_fetched >= 1
    assert representatives
    assert all(url.startswith('https://qscrape.dev/') for url in representatives)
