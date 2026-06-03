"""Integration tests for CAS-49 (Frontier) and CAS-51 (LinkExtractor)."""

import asyncio

import yosoi as ys
from yosoi.core.cleaning import HTMLCleaner
from yosoi.core.crawler.frontier import Frontier, normalize_url
from yosoi.core.crawler.link_extractor import LinkExtractor
from yosoi.core.fetcher.waterfall import JSFetcher
from yosoi.models.defaults import NewsArticle

URL = 'https://www.espn.com'


async def test_link_extractor() -> None:
    """CAS-51: link extraction and structure fingerprinting."""
    print('\n=== CAS-51: LinkExtractor ===')
    async with JSFetcher() as fetcher:
        result = await fetcher.fetch(URL)

    assert result.html, 'Fetch failed'
    print(f'✓ Fetched {len(result.html):,} chars')

    cleaner = HTMLCleaner()
    cleaned = cleaner.clean_html(result.html)
    print(f'✓ Cleaned to {len(cleaned):,} chars')

    fp = LinkExtractor.fingerprint(cleaned)
    print(f'✓ Structure fingerprint: {fp}')

    extractor = LinkExtractor()
    links = extractor.extract(cleaned, base_url=URL)
    print(f'✓ Found {len(links)} candidate links')

    pagination = [link for link in links if link.is_pagination]
    listing = [link for link in links if not link.is_pagination and link.score >= 0.7]
    other = [link for link in links if not link.is_pagination and link.score < 0.7]

    print(f'\n--- Pagination ({len(pagination)}) ---')
    for link in pagination:
        print(f'  [{link.score:.2f}] {link.url}  ({link.anchor_text!r})')

    print(f'\n--- Listing links ({len(listing)}) ---')
    for link in listing[:10]:
        print(f'  [{link.score:.2f}] {link.url}  ({link.anchor_text!r})')

    print(f'\n--- Other links ({len(other)}) ---')
    for link in other[:5]:
        print(f'  [{link.score:.2f}] {link.url}  ({link.anchor_text!r})')

    links_kw = extractor.extract(
        cleaned,
        base_url=URL,
        field_descriptions=NewsArticle.field_descriptions(),
    )
    print('\n--- With NewsArticle keyword boost ---')
    for link in links_kw[:5]:
        print(f'  [{link.score:.2f}] {link.url}  ({link.anchor_text!r})')


async def test_frontier() -> None:
    """CAS-49: frontier dedup, scoring, and persistence."""
    print('\n=== CAS-49: Frontier ===')

    f = Frontier(session_id='test-cas49', score_threshold=0.3)

    assert f.push(URL, depth=0, score=1.0)
    print('✓ Seed URL pushed')

    assert not f.push(URL, depth=0, score=1.0)
    print('✓ Duplicate rejected')

    assert not f.push('https://www.espn.com/low-score', depth=1, score=0.1)
    print('✓ Below-threshold URL rejected')

    assert f.push('https://www.espn.com/nba', depth=1, score=0.7)
    assert f.push('https://www.espn.com/mlb', depth=1, score=0.7)
    print(f'✓ Queue size: {f.queue_size()}, visited: {f.visited_count()}')

    url1, d1 = await f.popleft()
    assert url1 == normalize_url(URL)
    assert d1 == 0
    print(f'✓ popleft: {url1} depth={d1}')
    print(f'  pages_scraped: {f.pages_scraped}')

    await f.save()
    f2 = Frontier(session_id='test-cas49', score_threshold=0.3)
    assert f2.queue_size() == 2
    assert f2.visited_count() == 3
    assert not f2.push(URL, depth=0, score=1.0)
    print(f'✓ Persistence: reloaded queue={f2.queue_size()} visited={f2.visited_count()}')


async def test_crawl() -> None:
    """CAS-49: full pipeline crawl with depth=1."""
    print('\n=== CAS-49: Pipeline crawl depth=1 ===')

    config = ys.auto_config()
    pipeline = ys.Pipeline(llm_config=config, contract=ys.NewsArticle)

    items_found = []
    async with JSFetcher() as fetcher:
        async for item in pipeline.scrape(
            URL,
            fetcher=fetcher,
            fetcher_type='waterfall',
            depth=1,
            max_pages=3,
            score_threshold=0.3,
            session_id='test-crawl-cas49',
        ):
            items_found.append(item)
            print(f'  Item: {item.get("headline", "(no headline)")[:60]}')

    print(f'✓ Crawl complete: {len(items_found)} items from up to 3 pages')


async def main() -> None:
    """Run all CAS-49 and CAS-51 integration tests."""
    await test_link_extractor()
    await test_frontier()
    await test_crawl()
    print('\n✓ All tests done')


if __name__ == '__main__':
    asyncio.run(main())
