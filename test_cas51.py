"""Integration tests for CAS-49 (Frontier) and CAS-51 (LinkExtractor)."""

import asyncio

from pydantic import Field

import yosoi as ys
from yosoi.core.cleaning import HTMLCleaner
from yosoi.core.crawler.frontier import Frontier, normalize_url
from yosoi.core.crawler.link_extractor import LinkExtractor
from yosoi.core.fetcher.waterfall import JSFetcher
from yosoi.models.contract import Contract

# ESPN NFL section — a listing page that links to articles
URL = 'https://www.espn.com/nfl/'

# A known ESPN article URL for the crawl test
CRAWL_URL = 'https://www.espn.com/nfl'


class ESPNNewsArticle(Contract):
    """A specific contract for this test case."""

    headline: str = ys.Title(description='The main headline of the news article or story')
    author: str = ys.Author(description='The name of the article author or byline')
    date: str = ys.Datetime(description='The publication date of the article')
    body_text: str = ys.BodyText(description='The main body text of the article')
    url: str = Field(description='The URL of a news article or story page, with /story/ in the path')


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

    # Confirm field_descriptions works with keyword boosting
    links_with_keywords = extractor.extract(
        result.html,  # use raw HTML to find story links
        base_url=URL,
        field_descriptions=ESPNNewsArticle.field_descriptions(),
    )
    story_links = [lnk for lnk in links_with_keywords if '/nfl/story/' in lnk.url]
    print(f'\n✓ field_descriptions keyword boosting: {len(story_links)} story links found')
    if story_links:
        print(f'  Top story score: {story_links[0].score:.2f} (boosted from 0.70)')


async def test_frontier() -> None:
    """CAS-49: frontier dedup, scoring, persistence, and seed_domain penalty."""
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

    # Test seed_domain cross-domain penalty
    f3 = Frontier(session_id='test-domain', score_threshold=0.5, seed_domain='espn.com')
    assert f3.push('https://www.espn.com/nfl/story/1', depth=1, score=0.7)
    # VividSeats scores 0.7 but halved to 0.35 — below threshold
    assert not f3.push('https://www.vividseats.com/tickets', depth=1, score=0.7)
    print('✓ Cross-domain score penalty working (VividSeats filtered)')


async def test_crawl() -> None:
    """CAS-49: full pipeline crawl — contract url field drives content discovery."""
    print('\n=== CAS-49: Pipeline crawl depth=1 ===')
    print('  Strategy: contract url field → content URLs, LinkExtractor → listing/pagination only')

    config = ys.auto_config('google:gemini-2.5-flash')
    pipeline = ys.Pipeline(llm_config=config, contract=ESPNNewsArticle)

    items_found = []
    urls_followed = []

    async with JSFetcher() as fetcher:
        async for item in pipeline.scrape(
            CRAWL_URL,
            fetcher=fetcher,
            fetcher_type='waterfall',
            depth=1,
            max_pages=5,
            score_threshold=0.5,
            session_id='test-crawl-cas49',
            force=True,
        ):
            items_found.append(item)
            headline = item.get('headline', '(no headline)')
            article_url = item.get('url', '(no url)')
            urls_followed.append(article_url)
            print(f'  Item: {str(headline)[:60]}')
            print(f'    url: {str(article_url)[:80]}')

    print(f'\n✓ Crawl complete: {len(items_found)} items from up to 5 pages')

    if urls_followed:
        espn_urls = [u for u in urls_followed if 'espn' in str(u)]
        other_urls = [u for u in urls_followed if 'espn' not in str(u)]
        print(f'  ESPN URLs found: {len(espn_urls)}')
        print(f'  Other domain URLs found: {len(other_urls)}')
        if other_urls:
            print('  ⚠ Cross-domain URLs (should be rare with seed_domain penalty):')
            for u in other_urls[:3]:
                print(f'    {u}')


async def main() -> None:
    """Run all CAS-49 and CAS-51 integration tests."""
    await test_link_extractor()
    await test_frontier()
    await test_crawl()
    print('\n✓ All tests done')


if __name__ == '__main__':
    asyncio.run(main())
