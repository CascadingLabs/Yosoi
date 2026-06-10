from __future__ import annotations

import pytest

from yosoi.core.crawler import CrawlRunSummary
from yosoi.core.crawler.run import crawl_index
from yosoi.models.results import FetchResult
from yosoi.policy import CrawlBudget, CrawlSafety, Policy, SchedulerPolicy


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchResult:
        if url.endswith('/robots.txt'):  # robots gate is default-on; allow-all, don't count it
            return FetchResult(url=url, html=None, status_code=404)
        self.calls.append(url)
        html = self.pages.get(url)
        if html is None:
            return FetchResult(url=url, html=None, block_reason='missing fixture')
        return FetchResult(url=url, html=html, status_code=200, fetch_time=0.01)


@pytest.fixture(autouse=True)
def _no_persist(tmp_path, monkeypatch):
    """Keep the frontier off disk and out of the real .yosoi store."""
    monkeypatch.setattr('yosoi.core.crawler.frontier.init_yosoi', lambda _name: tmp_path)


def _inject(monkeypatch, fetcher: FakeFetcher) -> None:
    monkeypatch.setattr('yosoi.core.crawler.run.create_fetcher', lambda _type: fetcher)


async def test_crawl_index_returns_summary_with_pages_fetched(monkeypatch) -> None:
    fetcher = FakeFetcher(
        {
            'https://example.com/': '<a href="/a">A</a><a href="/b">B</a>',
            'https://example.com/a': '<article>A</article>',
            'https://example.com/b': '<article>B</article>',
        }
    )
    _inject(monkeypatch, fetcher)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=3, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=2, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )

    summary = await crawl_index(['https://example.com/'], policy=policy)

    assert isinstance(summary, CrawlRunSummary)
    assert summary.pages_fetched >= 1
    assert fetcher.calls[0] == 'https://example.com/'


async def test_crawl_index_default_policy_is_conservative(monkeypatch) -> None:
    """Calling without a policy resolves the opinionated crawl.conservative preset."""
    fetcher = FakeFetcher({'https://example.com/': '<article>home</article>'})
    _inject(monkeypatch, fetcher)

    summary = await crawl_index(['https://example.com/'])

    # crawl.conservative resolves seed host as the allow-list, so the seed fetches.
    assert isinstance(summary, CrawlRunSummary)
    assert summary.pages_fetched == 1
    assert fetcher.calls == ['https://example.com/']


async def test_crawl_index_blocks_denied_host_before_fetch(monkeypatch) -> None:
    fetcher = FakeFetcher({'https://example.com/': '<article>home</article>'})
    _inject(monkeypatch, fetcher)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=2, max_depth=0),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )

    summary = await crawl_index(['https://blocked.test/'], policy=policy)

    assert fetcher.calls == []
    assert summary.policy_blocked == 1
    assert summary.outcome_lanes['policy_blocked'] == ['https://blocked.test/']
