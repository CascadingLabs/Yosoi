from __future__ import annotations

from typing import ClassVar

import pytest

from yosoi.core.crawler import CrawlRunSummary
from yosoi.core.crawler.candidates import score_contract_fit
from yosoi.core.crawler.run import crawl
from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import PageFingerprint
from yosoi.models.defaults import NewsArticle
from yosoi.models.results import FetchResult
from yosoi.policy import CrawlBudget, CrawlSafety, OutputPolicy, Policy, SchedulerPolicy


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


def _score(contract: object, html: str):
    return _score_url(contract, 'https://example.com/page', html)


def _score_url(contract: object, url: str, html: str):
    return score_contract_fit(
        contract,
        url=url,
        source_url='https://example.com/',
        fingerprint=PageFingerprint.of(html),
        observation=observe_html(url, html, row_selector=''),
        html=html,
    )


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


async def test_crawl_builds_contract_candidates_for_targets(monkeypatch) -> None:
    fetcher = FakeFetcher(
        {
            'https://example.com/news/': (
                '<a href="/news/articles/story-one">Story One</a>'
                '<a href="/news/articles/blocked">Blocked Story</a>'
                '<a href="/products/anvil">Anvil</a>'
                '<a href="/news/about">About</a>'
                '<a href="/news/rss/">RSS</a>'
            ),
            'https://example.com/news/articles/story-one': (
                '<html><head><script type="application/ld+json">'
                '{"@type": "NewsArticle"}'
                '</script></head><body><main><article><h1>Story One</h1>'
                '<p>First paragraph.</p><p>Second paragraph.</p><p>Third paragraph.</p>'
                '</article></main></body></html>'
            ),
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

    assert summary.urls_for('NewsArticle') == ['https://example.com/news/articles/story-one']
    assert summary.urls_for(NewsArticle, limit=1) == ['https://example.com/news/articles/story-one']
    entries = summary.candidates_for('NewsArticle')
    assert entries[0].url == 'https://example.com/news/articles/story-one'
    assert entries[0].fit == 'strong'
    assert entries[0].scrape_verified is False
    assert 'structured data' in entries[0].evidence
    assert 'article landmark' in entries[0].evidence
    assert 'headline' in entries[0].evidence
    assert 'body text' in entries[0].evidence
    assert 'schema:NewsArticle' in entries[0].reasons
    assert 'field:headline<-heading' in entries[0].reasons
    assert 'field:body_text<-prose' in entries[0].reasons
    assert 'https://example.com/products/anvil' not in summary.urls_for('NewsArticle')
    assert 'https://example.com/news/articles/blocked' not in summary.urls_for('NewsArticle')
    assert 'https://example.com/news/about' not in summary.urls_for('NewsArticle')
    assert 'https://example.com/news/rss/' not in summary.urls_for('NewsArticle')
    assert 'https://example.com/news/articles/blocked' not in fetcher.calls


async def test_crawl_policy_can_scrape_selected_contract_candidates(monkeypatch) -> None:
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

    assert summary.urls_for(NewsArticle) == ['https://example.com/story']
    assert summary.candidates_for(NewsArticle)[0].fit == 'strong'


def test_news_article_shape_without_related_content_scores_strong() -> None:
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "NewsArticle", "headline": "Story", "author": "A", "datePublished": "2026-01-01"}'
        '</script></head><body><main><article><h1>Story</h1>'
        '<p>One paragraph with enough words for a story.</p>'
        '<p>Second paragraph with more body text.</p>'
        '<p>Third paragraph with more body text.</p>'
        '</article></main></body></html>'
    )

    entry = _score(NewsArticle, html)

    assert entry is not None
    assert entry.fit == 'strong'
    assert 'related_content' not in ''.join(entry.reasons)


def test_article_detail_shape_without_schema_or_landmark_scores_strong() -> None:
    html = (
        '<html><body><main><h1>Story</h1>'
        '<p>One paragraph with enough words for a story.</p>'
        '<p>Second paragraph with more body text.</p>'
        '<p>Third paragraph with more body text.</p>'
        '</main></body></html>'
    )

    entry = _score(NewsArticle, html)

    assert entry is not None
    assert entry.fit == 'strong'
    assert 'detail page shape' in entry.evidence
    assert 'headline' in entry.evidence
    assert 'body text' in entry.evidence
    assert 'shape:detail' in entry.reasons


def test_legacy_visible_title_and_body_containers_score_strong() -> None:
    html = (
        '<html><body><div class="pageTitle">Story One</div>'
        '<div class="articleBody">'
        'This article body has enough visible words to look like a detail page. '
        'It is not a listing, not a loading shell, and not just a headline. '
        'The crawler should treat this as body evidence without needing site selectors.'
        '</div></body></html>'
    )

    entry = _score(NewsArticle, html)

    assert entry is not None
    assert entry.fit == 'strong'
    assert 'headline' in entry.evidence
    assert 'body text' in entry.evidence
    assert 'field:headline<-visible' in entry.reasons
    assert 'field:body_text<-visible' in entry.reasons


def test_schema_and_headline_without_body_is_not_strong_and_weak_is_debug_only() -> None:
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "NewsArticle", "headline": "Story"}'
        '</script></head><body><main><h1>Story</h1><div>Short teaser.</div></main></body></html>'
    )

    entry = _score(NewsArticle, html)

    assert entry is not None
    assert entry.fit != 'strong'


def test_listing_page_with_many_links_is_weak() -> None:
    links = ''.join(f'<a href="/story-{idx}">Story {idx}</a>' for idx in range(40))
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "NewsArticle"}'
        '</script></head><body><main><h1>Latest stories</h1>'
        f'{links}</main></body></html>'
    )

    entry = _score(NewsArticle, html)

    assert entry is None or entry.fit == 'weak'


def test_profile_schema_without_article_structure_is_not_article_candidate() -> None:
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "ProfilePage", "mainEntity": {"@type": "Person", "name": "Reporter"}}'
        '</script></head><body><main><h1>Reporter</h1>'
        '<section class="profile-body">'
        '<p>Reporter writes about markets, technology, leadership, and public companies.</p>'
        '<p>This page collects recent work and biographical details for readers.</p>'
        '<p>It has enough prose to look substantive, but it is not an article.</p>'
        '</section></main></body></html>'
    )

    entry = _score(NewsArticle, html)

    assert entry is None


def test_root_page_without_article_structure_is_not_article_candidate() -> None:
    html = (
        '<html><body><main><h1>Latest news</h1>'
        '<section class="content-body">'
        '<p>This home page has enough visible body text to look substantial.</p>'
        '<p>It summarizes markets, technology, politics, and culture.</p>'
        '<p>But without article structure it should not be a scrape candidate.</p>'
        '</section></main></body></html>'
    )

    entry = _score_url(NewsArticle, 'https://example.com/', html)

    assert entry is None


def test_archive_grid_container_does_not_score_as_article_body() -> None:
    rows = ''.join(f'<tr><td>Story {idx}</td><td><a href="/article/{idx}">Read</a></td></tr>' for idx in range(8))
    html = (
        f'<html><body><div class="pageTitle">Article Archive</div><table id="articlesGrid">{rows}</table></body></html>'
    )

    entry = _score(NewsArticle, html)

    assert entry is None or entry.fit != 'strong'


def test_candidate_scoring_ignores_invalid_attribute_values(monkeypatch) -> None:
    class BrokenAttrib(dict):
        def get(self, _key: object, _default: object = None) -> object:
            raise ValueError('All strings must be XML compatible')

    class BrokenNode:
        attrib = BrokenAttrib()

        def xpath(self, query: str):
            if query == 'name()':
                return _SelectorResult(['div'])
            if query.startswith('.//text()'):
                return _SelectorResult(['Story body text'])
            return _SelectorResult([])

    class FakeSelector:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def css(self, _query: str):
            return _SelectorResult([])

        def xpath(self, query: str):
            if query == '//*':
                return [BrokenNode()]
            return _SelectorResult([])

    html = '<html><body><div bad="x">Story</div></body></html>'
    fingerprint = PageFingerprint.of(html)
    observation = observe_html('https://example.com/page', html, row_selector='')
    monkeypatch.setattr('parsel.Selector', FakeSelector)

    entry = score_contract_fit(
        NewsArticle,
        url='https://example.com/page',
        source_url='https://example.com/',
        fingerprint=fingerprint,
        observation=observation,
        html=html,
    )

    assert entry is None or entry.fit != 'strong'


class _SelectorResult:
    def __init__(self, values: list[str]) -> None:
        self.values = values

    def get(self) -> str | None:
        return self.values[0] if self.values else None

    def getall(self) -> list[str]:
        return self.values


def test_repeated_card_body_containers_do_not_score_as_article_body() -> None:
    cards = ''.join(
        '<div class="articleCard">'
        f'<div class="featuredContent"><h2>Story {idx}</h2>'
        '<p>This card teaser has enough words to look substantial in isolation.</p></div>'
        '<a href="/story">Read</a>'
        '</div>'
        for idx in range(8)
    )
    html = f'<html><body><main><h1>Latest stories</h1>{cards}</main></body></html>'

    entry = _score(NewsArticle, html)

    assert entry is None or entry.fit != 'strong'


def test_large_main_container_alone_does_not_score_as_article_body() -> None:
    links = ''.join(f'<a href="/story-{idx}">Story {idx}</a>' for idx in range(24))
    html = (
        '<html><body><main><h1>News</h1>'
        '<p>This section has plenty of words about the latest headlines, markets, '
        'weather, politics, and culture, but it is still an index surface.</p>'
        f'{links}'
        '</main></body></html>'
    )

    entry = _score(NewsArticle, html)

    assert entry is None or entry.fit != 'strong'


def test_news_schema_video_without_article_body_is_not_strong() -> None:
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "NewsArticle", "headline": "Clip"}'
        '</script></head><body><main><h1>Clip</h1><video src="/clip.mp4"></video>'
        '<p>Watch the latest market update.</p></main></body></html>'
    )

    entry = _score(NewsArticle, html)

    assert entry is not None
    assert entry.fit != 'strong'


def test_product_schema_with_name_but_no_price_is_below_strong() -> None:
    from yosoi.models.defaults import Product

    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "Product", "name": "Anvil"}'
        '</script></head><body><main><h1>Anvil</h1>'
        '<p>Forged tool for metalwork.</p></main></body></html>'
    )

    entry = _score(Product, html)

    assert entry is not None
    assert entry.fit != 'strong'


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
