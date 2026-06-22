from __future__ import annotations

from typing import ClassVar

import pytest

from yosoi.core.crawler import CrawlRunSummary
from yosoi.core.crawler.coordinator import CrawlJob, CrawlResult
from yosoi.core.crawler.links import CrawlLink
from yosoi.core.crawler.run import crawl
from yosoi.generalization.fingerprint import PageFingerprint
from yosoi.models.defaults import NewsArticle
from yosoi.models.results import FetchResult
from yosoi.policy import CrawlBudget, CrawlSafety, OutputPolicy, PagePolicy, Policy, SchedulerPolicy


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


class ContextFetcher(FakeFetcher):
    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__(pages)
        self.entered = False
        self.exited = False
        self.fetch_entered: list[bool] = []

    async def __aenter__(self) -> ContextFetcher:
        self.entered = True
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exited = True

    async def fetch(self, url: str) -> FetchResult:
        self.fetch_entered.append(self.entered)
        return await super().fetch(url)


@pytest.fixture(autouse=True)
def _no_persist(tmp_path, monkeypatch):
    """Keep the frontier off disk and out of the real .yosoi store."""
    monkeypatch.setattr('yosoi.core.crawler.frontier.init_yosoi', lambda _name: tmp_path)


def _inject(monkeypatch, fetcher: FakeFetcher) -> None:
    monkeypatch.setattr('yosoi.core.crawler.run.create_fetcher', lambda _type, **_kwargs: fetcher)


class FakeProgress:
    instances: ClassVar[list[FakeProgress]] = []

    def __init__(self, **_kwargs: object) -> None:
        self.events: list[str] = []
        FakeProgress.instances.append(self)

    def __enter__(self) -> FakeProgress:
        self.events.append('enter')
        return self

    def __exit__(self, *_args: object) -> None:
        self.events.append('exit')

    def start(self, **_kwargs: object) -> None:
        self.events.append('start')

    def batch(self, *_args: object) -> None:
        self.events.append('batch')

    def result(self, *_args: object) -> None:
        self.events.append('result')

    def finish(self, *_args: object) -> None:
        self.events.append('finish')


async def test_crawl_returns_summary_with_pages_fetched(monkeypatch) -> None:
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

    summary = await crawl(['https://example.com/'], policy=policy)

    assert isinstance(summary, CrawlRunSummary)
    assert summary.pages_fetched >= 1
    assert fetcher.calls[0] == 'https://example.com/'


async def test_crawl_exposes_neutral_representative_urls(monkeypatch) -> None:
    fetcher = FakeFetcher(
        {
            'https://example.com/news/': (
                '<a href="/news/articles/story-one">Story One</a>'
                '<a href="/news/articles/blocked">Blocked Story</a>'
                '<a href="/products/anvil">Anvil</a>'
            ),
            'https://example.com/news/articles/story-one': '<main><article><h1>Story One</h1></article></main>',
            'https://example.com/news/articles/blocked': '<article>Blocked Story</article>',
            'https://example.com/products/anvil': '<main>Anvil</main>',
        }
    )
    _inject(monkeypatch, fetcher)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=4, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=2, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',), blocked_path_prefixes=('/news/articles/blocked',)),
        target_contracts=('NewsArticle',),
    )

    summary = await crawl(['https://example.com/news/'], policy=policy, progress=False)

    assert summary.representative_urls(limit=1) == ['https://example.com/news/']
    assert summary.scrape_target_urls(limit=1) == ['https://example.com/news/articles/story-one']
    assert 'https://example.com/news/articles/blocked' not in fetcher.calls


async def test_scrape_target_urls_fall_back_to_seed_for_single_page_crawls(monkeypatch) -> None:
    fetcher = FakeFetcher({'https://example.com/story': '<main><article><h1>Story</h1></article></main>'})
    _inject(monkeypatch, fetcher)
    policy = Policy.for_crawl(
        'crawl.local_single',
        budget=CrawlBudget(max_pages=1, max_depth=0),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )

    summary = await crawl('https://example.com/story', policy=policy, progress=False)

    assert summary.scrape_target_urls() == ['https://example.com/story']


def test_scrape_target_urls_does_not_penalize_uppercase_ids_or_skus() -> None:
    summary = CrawlRunSummary(
        results=[
            CrawlResult(
                job=CrawlJob(url='https://example.com/SKU/ABC123', depth=1, source_url=None, batch_index=0),
                status='succeeded',
                html='<main><article><p>' + ('Product content. ' * 20) + '</p></article></main>',
                content_type='text/html',
            ),
            CrawlResult(
                job=CrawlJob(url='https://example.com/thin', depth=1, source_url=None, batch_index=1),
                status='succeeded',
                html='<main>Thin</main>',
                content_type='text/html',
            ),
        ]
    )

    assert summary.scrape_target_urls(limit=1) == ['https://example.com/SKU/ABC123']


def test_scrape_target_urls_deprioritizes_structural_artifact_routes() -> None:
    summary = CrawlRunSummary(
        results=[
            CrawlResult(
                job=CrawlJob(url='https://example.com/AGENTS/', depth=1, source_url=None, batch_index=0),
                status='succeeded',
                html='<main><p>' + ('Large repository instructions. ' * 100) + '</p></main>',
                content_type='text/html',
            ),
            CrawlResult(
                job=CrawlJob(url='https://example.com/story', depth=1, source_url=None, batch_index=1),
                status='succeeded',
                html='<main><article><p>' + ('Useful content. ' * 20) + '</p></article></main>',
                content_type='text/html',
            ),
        ]
    )

    assert summary.scrape_target_urls(limit=1) == ['https://example.com/story']


def test_scrape_target_urls_prefers_pages_with_content_evidence_over_thin_pages() -> None:
    summary = CrawlRunSummary(
        results=[
            CrawlResult(
                job=CrawlJob(url='https://example.com/thin', depth=1, source_url=None, batch_index=0),
                status='succeeded',
                html='<main><a href="/home">Home</a></main>',
                content_type='text/html',
            ),
            CrawlResult(
                job=CrawlJob(url='https://example.com/listing', depth=1, source_url=None, batch_index=1),
                status='succeeded',
                discovered_links=tuple(
                    CrawlLink(url=f'https://example.com/item/{index}', text=str(index), score=0.5)
                    for index in range(20)
                ),
                html='<main>'
                + ' '.join(f'<a href="/item/{index}">Item {index}</a>' for index in range(20))
                + '</main>',
                content_type='text/html',
            ),
            CrawlResult(
                job=CrawlJob(url='https://example.com/story', depth=1, source_url=None, batch_index=2),
                status='succeeded',
                html='<main><article><h1>Story</h1><p>' + ('Useful content. ' * 60) + '</p></article></main>',
                content_type='text/html',
            ),
        ]
    )

    assert summary.scrape_target_urls(limit=1) == ['https://example.com/story']


def test_representative_urls_dedupe_clusters_without_limit() -> None:
    fingerprint = PageFingerprint.of('<main><article><h1>Story</h1></article></main>')
    summary = CrawlRunSummary(
        results=[
            CrawlResult(
                job=CrawlJob(url='https://example.com/story/1', depth=1, source_url=None, batch_index=0),
                status='succeeded',
                content_type='text/html',
                fingerprint=fingerprint,
            ),
            CrawlResult(
                job=CrawlJob(url='https://example.com/story/2', depth=1, source_url=None, batch_index=1),
                status='succeeded',
                content_type='text/html',
                fingerprint=fingerprint,
            ),
        ]
    )

    assert summary.representative_urls() == ['https://example.com/story/1']


async def test_crawl_passes_policy_chrome_ws_urls_to_auto_fetcher(monkeypatch) -> None:
    fetcher = FakeFetcher({'https://example.com/': '<html><body><h1>Home</h1></body></html>'})
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_create_fetcher(fetcher_type: str, **kwargs: object) -> FakeFetcher:
        calls.append((fetcher_type, kwargs))
        return fetcher

    monkeypatch.setattr('yosoi.core.crawler.run.create_fetcher', fake_create_fetcher)
    policy = Policy.cascade(
        Policy.for_crawl(
            'crawl.local_single',
            scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
            safety=CrawlSafety(allowed_hosts=('example.com',)),
            fetcher_type='auto',
        ),
        Policy(page=PagePolicy(chrome_ws_urls=('http://127.0.0.1:9222',))),
    )

    await crawl('https://example.com/', policy=policy, progress=False)

    assert calls[0][0] == 'auto'
    assert calls[0][1]['chrome_ws_urls'] == ('http://127.0.0.1:9222',)
    assert calls[0][1]['max_concurrent'] == 1
    assert calls[0][1]['crawl_frontier_only'] is True
    assert 'accept_simple_requires_js' not in calls[0][1]


async def test_crawl_policy_can_scrape_representative_urls(monkeypatch) -> None:
    fetcher = FakeFetcher(
        {
            'https://example.com/news/': '<a href="/story">Story One</a>',
            'https://example.com/story': (
                '<html><head><script type="application/ld+json">'
                '{"@type": "NewsArticle"}'
                '</script></head><body><article><h1>Story One</h1>'
                '<p>First paragraph.</p><p>Second paragraph.</p><p>Third paragraph.</p>'
                '</article></body></html>'
            ),
        }
    )
    scraped_calls: list[tuple[list[str], object]] = []

    async def fake_scrape(urls: list[str], contract: object, **_kwargs: object) -> list[dict[str, str]]:
        scraped_calls.append((urls, contract))
        return [{'headline': 'Story One'}]

    _inject(monkeypatch, fetcher)
    monkeypatch.setattr('yosoi.api.scrape', fake_scrape)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=2, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
        scrape_contracts=True,
    )

    summary = await crawl('https://example.com/news/', contracts=NewsArticle, policy=policy, progress=False)

    assert scraped_calls == [(['https://example.com/story'], NewsArticle)]
    assert summary.scraped_content == {'NewsArticle': [{'headline': 'Story One'}]}


async def test_crawl_policy_scrape_contracts_uses_call_site_contract_classes(monkeypatch) -> None:
    class LocalArticle(NewsArticle):
        """Local custom article contract."""

    fetcher = FakeFetcher(
        {
            'https://example.com/news/': '<a href="/story">Story One</a>',
            'https://example.com/story': (
                '<html><head><script type="application/ld+json">'
                '{"@type": "NewsArticle"}'
                '</script></head><body><article><h1>Story One</h1>'
                '<p>First paragraph.</p><p>Second paragraph.</p><p>Third paragraph.</p>'
                '</article></body></html>'
            ),
        }
    )
    scraped_calls: list[tuple[list[str], object]] = []

    async def fake_scrape(urls: list[str], contract: object, **_kwargs: object) -> list[dict[str, str]]:
        scraped_calls.append((urls, contract))
        return [{'headline': 'Story One'}]

    _inject(monkeypatch, fetcher)
    monkeypatch.setattr('yosoi.api.scrape', fake_scrape)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=2, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
        scrape_contracts=[LocalArticle],
    )

    summary = await crawl('https://example.com/news/', contracts=[LocalArticle], policy=policy, progress=False)

    assert scraped_calls == [(['https://example.com/story'], LocalArticle)]
    assert summary.scraped_content == {'LocalArticle': [{'headline': 'Story One'}]}


async def test_crawl_policy_scrape_contracts_rejects_multi_contract_without_planner(monkeypatch) -> None:
    fetcher = FakeFetcher({'https://example.com/': '<a href="/story">Story One</a>'})
    _inject(monkeypatch, fetcher)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=1, max_depth=0),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
        scrape_contracts=[NewsArticle, 'Product'],
    )

    with pytest.raises(ValueError, match='cannot route multiple contracts'):
        await crawl('https://example.com/', contracts=[NewsArticle, 'Product'], policy=policy, progress=False)


async def test_crawl_policy_scrape_contracts_can_supply_targets(monkeypatch) -> None:
    fetcher = FakeFetcher(
        {
            'https://example.com/news/': '<a href="/story">Story One</a>',
            'https://example.com/story': (
                '<html><head><script type="application/ld+json">'
                '{"@type": "NewsArticle"}'
                '</script></head><body><article><h1>Story One</h1>'
                '<p>First paragraph.</p><p>Second paragraph.</p><p>Third paragraph.</p>'
                '</article></body></html>'
            ),
        }
    )
    scraped_calls: list[tuple[list[str], object]] = []

    async def fake_scrape(urls: list[str], contract: object, **_kwargs: object) -> list[dict[str, str]]:
        scraped_calls.append((urls, contract))
        return [{'headline': 'Story One'}]

    _inject(monkeypatch, fetcher)
    monkeypatch.setattr('yosoi.api.scrape', fake_scrape)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=2, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
        scrape_contracts=[NewsArticle],
    )

    summary = await crawl('https://example.com/news/', policy=policy, progress=False)

    assert summary.scrape_target_urls() == ['https://example.com/story']
    assert scraped_calls == [(['https://example.com/story'], 'NewsArticle')]
    assert summary.scraped_content == {'NewsArticle': [{'headline': 'Story One'}]}


async def test_crawl_accepts_contract_classes_at_call_site(monkeypatch) -> None:
    fetcher = FakeFetcher(
        {
            'https://example.com/news/': '<a href="/story">Story One</a>',
            'https://example.com/story': (
                '<html><head><script type="application/ld+json">'
                '{"@type": "NewsArticle"}'
                '</script></head><body><article><h1>Story One</h1>'
                '<section><p>First paragraph.</p><p>Second paragraph.</p><p>Third paragraph.</p>'
                '<p>Fourth paragraph.</p><p>Fifth paragraph.</p></section>'
                '</article></body></html>'
            ),
        }
    )
    _inject(monkeypatch, fetcher)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=2, max_depth=1),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )

    summary = await crawl('https://example.com/news/', contracts=NewsArticle, limit=1, policy=policy, progress=False)

    assert summary.scrape_target_urls() == ['https://example.com/story']


async def test_crawl_enters_async_fetcher_context(monkeypatch) -> None:
    fetcher = ContextFetcher({'https://example.com/': '<article>home</article>'})
    _inject(monkeypatch, fetcher)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=1, max_depth=0),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )

    await crawl(['https://example.com/'], policy=policy, progress=False)

    assert fetcher.entered is True
    assert fetcher.exited is True
    assert fetcher.fetch_entered
    assert all(fetcher.fetch_entered)


async def test_crawl_uses_rich_progress_by_default(monkeypatch) -> None:
    fetcher = FakeFetcher({'https://example.com/': '<article>home</article>'})
    _inject(monkeypatch, fetcher)
    FakeProgress.instances.clear()
    monkeypatch.setattr('yosoi.core.crawler.run.RichCrawlProgress', FakeProgress)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=1, max_depth=0),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )

    await crawl(['https://example.com/'], policy=policy)

    assert len(FakeProgress.instances) == 1
    assert FakeProgress.instances[0].events == ['enter', 'start', 'batch', 'result', 'finish', 'exit']


async def test_crawl_plain_output_disables_rich_progress(monkeypatch) -> None:
    fetcher = FakeFetcher({'https://example.com/': '<article>home</article>'})
    _inject(monkeypatch, fetcher)
    FakeProgress.instances.clear()
    monkeypatch.setattr('yosoi.core.crawler.run.RichCrawlProgress', FakeProgress)
    crawl_policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=1, max_depth=0),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )
    policy = Policy.cascade(crawl_policy, Policy(output=OutputPolicy(plain_output=True)))

    await crawl(['https://example.com/'], policy=policy)

    assert FakeProgress.instances == []


async def test_crawl_default_policy_is_conservative(monkeypatch) -> None:
    """Calling without a policy resolves the opinionated crawl.conservative preset."""
    fetcher = FakeFetcher({'https://example.com/': '<article>home</article>'})
    _inject(monkeypatch, fetcher)

    summary = await crawl(['https://example.com/'])

    # crawl.conservative resolves seed host as the allow-list, so the seed fetches.
    assert isinstance(summary, CrawlRunSummary)
    assert summary.pages_fetched == 1
    assert fetcher.calls == ['https://example.com/']


async def test_crawl_blocks_denied_host_before_fetch(monkeypatch) -> None:
    fetcher = FakeFetcher({'https://example.com/': '<article>home</article>'})
    _inject(monkeypatch, fetcher)
    policy = Policy.for_crawl(
        'crawl.conservative',
        budget=CrawlBudget(max_pages=2, max_depth=0),
        scheduler=SchedulerPolicy(max_workers=1, politeness_delay=0),
        safety=CrawlSafety(allowed_hosts=('example.com',)),
    )

    summary = await crawl(['https://blocked.test/'], policy=policy)

    assert fetcher.calls == []
    assert summary.policy_blocked == 1
    assert summary.outcome_lanes['policy_blocked'] == ['https://blocked.test/']
