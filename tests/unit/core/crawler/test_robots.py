"""robots.txt gating in the crawl coordinator (policy ``CrawlSafety.respect_robots``)."""

from __future__ import annotations

from types import SimpleNamespace

import yosoi as ys
from yosoi.core.crawler.coordinator import CrawlCoordinator

INDEX_HTML = '<a href="http://site.test/public/a">a</a><a href="http://site.test/private/b">b</a>'
ROBOTS = 'User-agent: *\nDisallow: /private/\n'


class RobotsFetcher:
    """Serves robots.txt for the robots URL and a two-link index for everything else."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    async def fetch(self, url: str) -> SimpleNamespace:
        if url.endswith('/robots.txt'):
            return SimpleNamespace(html=ROBOTS, success=True)
        self.fetched.append(url)
        return SimpleNamespace(html=INDEX_HTML, success=True)


def _runtime(*, respect_robots: bool) -> ys.CrawlRuntimeConfig:
    policy = ys.Policy.for_crawl(
        'crawl.local_single',
        budget=ys.CrawlBudget(max_pages=5, max_depth=1),
        scheduler=ys.SchedulerPolicy(max_workers=2, politeness_delay=0.0),
        safety=ys.CrawlSafety(allowed_hosts=('site.test',), respect_robots=respect_robots),
    )
    return policy.require_crawl().to_runtime_config(seeds=('http://site.test/',))


async def test_respect_robots_blocks_disallowed_paths() -> None:
    fetcher = RobotsFetcher()
    summary = await CrawlCoordinator(
        fetcher=fetcher, config=_runtime(respect_robots=True), persist_frontier=False
    ).run()

    blocked = summary.outcome_lanes.get('policy_blocked', [])
    assert 'http://site.test/private/b' in blocked
    assert 'http://site.test/private/b' not in fetcher.fetched  # disallowed → never fetched
    assert 'http://site.test/public/a' in fetcher.fetched  # allowed sibling still crawled


async def test_opt_out_ignores_robots() -> None:
    fetcher = RobotsFetcher()
    summary = await CrawlCoordinator(
        fetcher=fetcher, config=_runtime(respect_robots=False), persist_frontier=False
    ).run()

    assert 'http://site.test/private/b' in fetcher.fetched  # opted out → fetched anyway
    assert not summary.outcome_lanes.get('policy_blocked', [])
