from __future__ import annotations

import time

import pytest

from yosoi.core.crawler import CrawlCoordinator
from yosoi.models.results import FetchResult
from yosoi.policies import CrawlBudget, CrawlPolicy, CrawlSafety, Policy, SchedulerPolicy


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        html = self.pages.get(url)
        if html is None:
            return FetchResult(url=url, html=None, block_reason='missing fixture')
        return FetchResult(url=url, html=html, status_code=200, fetch_time=0.01)


class TimingFetcher(FakeFetcher):
    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__(pages)
        self.started_at: list[float] = []

    async def fetch(self, url: str) -> FetchResult:
        self.started_at.append(time.monotonic())
        return await super().fetch(url)


def _runtime(policy: Policy, *seeds: str):
    return policy.check_crawl(seeds=tuple(seeds)).runtime


async def test_policy_coordinator_fans_out_after_single_seed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('yosoi.core.crawler.frontier.init_yosoi', lambda _name: tmp_path)
    fetcher = FakeFetcher(
        {
            'https://example.com/': '<a href="/a">A</a><a href="/b">B</a><a href="/c">C</a>',
            'https://example.com/a': '<article>A</article>',
            'https://example.com/b': '<article>B</article>',
            'https://example.com/c': '<article>C</article>',
        }
    )
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=4, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=3, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )
    runtime = _runtime(policy, 'https://example.com/')
    assert runtime is not None

    summary = await CrawlCoordinator(fetcher=fetcher, config=runtime, persist_frontier=False).run()

    assert fetcher.calls == [
        'https://example.com/',
        'https://example.com/a',
        'https://example.com/b',
        'https://example.com/c',
    ]
    assert [result.job.url for result in summary.results] == fetcher.calls
    assert summary.pages_fetched == 4
    assert summary.unique_urls_seen == 4
    assert summary.batches == 2
    assert summary.idle_worker_slots == 2
    assert summary.worker_slots_total == 6
    assert summary.worker_slots_used == 4
    assert summary.average_batch_fill == 2
    assert summary.dispatch_slot_idle_ratio == pytest.approx(2 / 6)
    assert summary.outcome_lanes['succeeded'] == fetcher.calls


async def test_policy_coordinator_blocks_denied_paths_before_fetch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('yosoi.core.crawler.frontier.init_yosoi', lambda _name: tmp_path)
    fetcher = FakeFetcher(
        {
            'https://example.com/': '<a href="/article/1">Article</a><a href="/login">Login</a>',
            'https://example.com/article/1': '<article>A</article>',
        }
    )
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=3, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=2, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',), blocked_path_prefixes=('/login',)),
    )
    runtime = _runtime(policy, 'https://example.com/')
    assert runtime is not None

    summary = await CrawlCoordinator(fetcher=fetcher, config=runtime, persist_frontier=False).run()

    assert fetcher.calls == ['https://example.com/', 'https://example.com/article/1']
    assert summary.pages_fetched == 2
    assert summary.policy_blocked == 1
    assert summary.outcome_lanes['policy_blocked'] == ['https://example.com/login']
    assert summary.results[-1].error == 'path blocked by policy: /login'


async def test_policy_coordinator_records_failures_without_blocking_siblings(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('yosoi.core.crawler.frontier.init_yosoi', lambda _name: tmp_path)
    fetcher = FakeFetcher(
        {
            'https://example.com/': '<a href="/a">A</a><a href="/missing">Missing</a>',
            'https://example.com/a': '<article>A</article>',
        }
    )
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=3, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=2, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )
    runtime = _runtime(policy, 'https://example.com/')
    assert runtime is not None

    summary = await CrawlCoordinator(fetcher=fetcher, config=runtime, persist_frontier=False).run()

    assert fetcher.calls == ['https://example.com/', 'https://example.com/a', 'https://example.com/missing']
    assert summary.pages_fetched == 2
    assert summary.attempted_urls == 3
    assert summary.failures == 1
    assert summary.outcome_lanes['failed'] == ['https://example.com/missing']


async def test_policy_coordinator_attempt_budget_counts_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('yosoi.core.crawler.frontier.init_yosoi', lambda _name: tmp_path)
    fetcher = FakeFetcher({})
    policy = Policy(
        crawl=CrawlPolicy(
            budget=CrawlBudget(max_pages=1, max_depth=0, max_attempts=1),
            scheduler=SchedulerPolicy(max_workers=3, politeness_delay=0),
            safety=CrawlSafety(allowed_hosts=('example.com',)),
        )
    )
    runtime = _runtime(
        policy,
        'https://example.com/a',
        'https://example.com/b',
        'https://example.com/c',
    )
    assert runtime is not None

    summary = await CrawlCoordinator(fetcher=fetcher, config=runtime, persist_frontier=False).run()

    assert fetcher.calls == ['https://example.com/c']
    assert summary.attempted_urls == 1
    assert summary.pages_fetched == 0
    assert summary.failures == 1


async def test_policy_coordinator_enforces_politeness_between_same_host_workers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('yosoi.core.crawler.frontier.init_yosoi', lambda _name: tmp_path)
    fetcher = TimingFetcher(
        {
            'https://example.com/': '<a href="/a">A</a><a href="/b">B</a>',
            'https://example.com/a': '<article>A</article>',
            'https://example.com/b': '<article>B</article>',
        }
    )
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=3, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=2, politeness_delay=0.01),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )
    runtime = _runtime(policy, 'https://example.com/')
    assert runtime is not None

    await CrawlCoordinator(fetcher=fetcher, config=runtime, persist_frontier=False).run()

    assert len(fetcher.started_at) == 3
    assert fetcher.started_at[1] - fetcher.started_at[0] >= 0.009
    assert fetcher.started_at[2] - fetcher.started_at[1] >= 0.009
