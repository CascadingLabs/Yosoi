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


async def test_allowed_passes_hostless_urls() -> None:
    from yosoi.policy.robots import RobotsGate

    gate = RobotsGate(RobotsFetcher())
    assert await gate.allowed('not-a-url') is True


async def test_unreachable_robots_is_allow_all() -> None:

    from yosoi.policy.robots import RobotsGate

    class FailingFetcher:
        async def fetch(self, url: str) -> SimpleNamespace:
            raise RuntimeError('network down')

    gate = RobotsGate(FailingFetcher())
    assert await gate.allowed('http://site.test/private/b') is True


async def test_parser_is_fetched_once_under_concurrent_access() -> None:
    """Double-checked lock: concurrent first-touches on one host fetch robots.txt exactly once."""
    import asyncio
    from types import SimpleNamespace

    from yosoi.policy.robots import RobotsGate

    class CountingFetcher:
        def __init__(self) -> None:
            self.robots_fetches = 0

        async def fetch(self, url: str) -> SimpleNamespace:
            self.robots_fetches += 1
            await asyncio.sleep(0.01)  # hold the lock so the racer hits the cached branch
            return SimpleNamespace(html='User-agent: *\nDisallow: /private/\n', status_code=200)

    fetcher = CountingFetcher()
    gate = RobotsGate(fetcher)

    results = await asyncio.gather(
        gate.allowed('https://site.test/public/a'),
        gate.allowed('https://site.test/private/b'),
    )

    assert results == [True, False]
    assert fetcher.robots_fetches == 1  # the second coroutine took the already-cached branch
