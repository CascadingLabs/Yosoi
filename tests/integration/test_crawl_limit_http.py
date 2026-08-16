"""CAS-232 over a real HTTP transport, against a link-trap site.

The bug was found while stress-testing a crawl against calendar/facet traps: ``limit=N``
changed nothing, and the crawl fetched the same page count every time. These tests rebuild
that shape — a handful of real pages buried in a combinatorial trap — and assert the cap
against the server's own request log, which is the only count that cannot be faked.
"""

from __future__ import annotations

import pytest

import yosoi as ys
from tests.fixtures.local_site import Route, serve

pytestmark = pytest.mark.local_http

TRAP_HOST_PAGES = 400


def _trap_site() -> dict[str, Route]:
    """Five real articles plus a calendar/facet trap that never runs out of links."""
    article_links = ''.join(f'<a href="/articles/{index}">Article {index}</a>' for index in range(5))
    calendar_links = ''.join(f'<a href="/calendar/2026-{month:02d}">{month}</a>' for month in range(1, 13))
    facet_links = ''.join(f'<a href="/facet/color-{index}">Facet {index}</a>' for index in range(40))
    filler = '<p>' + ('Body copy. ' * 40) + '</p>'

    routes: dict[str, Route] = {
        '/': Route(f'<html><body>{article_links}{calendar_links}{facet_links}</body></html>'.encode()),
        '/robots.txt': Route(b'User-agent: *\nAllow: /\n', content_type='text/plain'),
    }
    for index in range(5):
        body = f'<html><body><article><h1>Article {index}</h1>{filler}</article>{calendar_links}</body></html>'
        routes[f'/articles/{index}'] = Route(body.encode())
    for month in range(1, 13):
        # Each calendar month links onward to day pages and back to the facets: the classic
        # trap where a naive budget is diluted long before the real content is reached.
        days = ''.join(f'<a href="/calendar/2026-{month:02d}-{day:02d}">{day}</a>' for day in range(1, 29))
        routes[f'/calendar/2026-{month:02d}'] = Route(f'<html><body>{days}{facet_links}</body></html>'.encode())
        for day in range(1, 29):
            routes[f'/calendar/2026-{month:02d}-{day:02d}'] = Route(
                f'<html><body><p>Nothing on day {day}</p>{facet_links}</body></html>'.encode()
            )
    for index in range(40):
        routes[f'/facet/color-{index}'] = Route(
            f'<html><body><p>Facet {index}</p>{article_links}{calendar_links}</body></html>'.encode()
        )
    return routes


def _policy(*, max_pages: int = 500, max_pages_per_host: int | None = 500) -> ys.Policy:
    """A conservative-shaped policy with the politeness delay removed to keep tests quick."""
    return ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(max_pages=max_pages, max_depth=4, max_pages_per_host=max_pages_per_host),
        scheduler=ys.SchedulerPolicy(max_workers=3, per_host_concurrency=1, politeness_delay=0.0),
        fetcher_type='simple',
    )


def _page_requests(paths: list[str]) -> list[str]:
    return [path for path in paths if path != '/robots.txt']


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', [1, 5, 12])
async def test_limit_caps_a_trap_crawl_at_the_transport(limit: int) -> None:
    """The server sees at most ``limit`` page requests, however many links the trap offers."""
    with serve(_trap_site()) as site:
        summary = await ys.crawl(site.url('/'), limit=limit, policy=_policy(), fetcher_type='simple', progress=False)
        fetched = _page_requests(site.requests)

    succeeded = [result for result in summary.results if result.status == 'succeeded']
    assert summary.pages_fetched == limit
    assert len(succeeded) == limit
    assert len(fetched) == limit


@pytest.mark.asyncio
async def test_limit_beats_a_generous_policy_budget() -> None:
    """``limit`` lowers an explicit 500-page budget instead of being ignored by it."""
    with serve(_trap_site()) as site:
        summary = await ys.crawl(site.url('/'), limit=7, policy=_policy(), fetcher_type='simple', progress=False)
        fetched = _page_requests(site.requests)

    assert summary.pages_fetched == 7
    assert len(fetched) == 7


@pytest.mark.asyncio
async def test_distinct_limits_produce_distinct_page_counts() -> None:
    """The reported regression: every limit crawled the same number of pages."""
    counts: dict[int, int] = {}
    for limit in (3, 6, 9):
        with serve(_trap_site()) as site:
            await ys.crawl(site.url('/'), limit=limit, policy=_policy(), fetcher_type='simple', progress=False)
            counts[limit] = len(_page_requests(site.requests))

    assert counts == {3: 3, 6: 6, 9: 9}


@pytest.mark.asyncio
async def test_limit_outranks_a_lower_per_host_cap() -> None:
    """A preset per-host cap below ``limit`` must not silently shrink the answer."""
    with serve(_trap_site()) as site:
        await ys.crawl(
            site.url('/'),
            limit=12,
            policy=_policy(max_pages_per_host=5),  # the crawl.conservative shape, scaled down
            fetcher_type='simple',
            progress=False,
        )
        fetched = _page_requests(site.requests)

    assert len(fetched) == 12


@pytest.mark.asyncio
async def test_limit_above_the_site_size_stops_at_what_exists() -> None:
    """``limit`` is an upper bound: a tiny site is not padded up to it."""
    filler = ('<p>' + 'Body copy. ' * 40 + '</p>').encode()
    routes = {
        '/': Route(b'<html><body><a href="/only">Only</a>' + filler + b'</body></html>'),
        '/only': Route(b'<html><body><article>Only page</article>' + filler + b'</body></html>'),
    }
    with serve(routes) as site:
        summary = await ys.crawl(site.url('/'), limit=50, policy=_policy(), fetcher_type='simple', progress=False)

    assert summary.pages_fetched == 2


@pytest.mark.asyncio
async def test_limit_holds_under_the_default_policy() -> None:
    """No policy argument: the default crawl.conservative preset still honors the cap."""
    with serve(_trap_site()) as site:
        summary = await ys.crawl(site.url('/'), limit=4, fetcher_type='simple', progress=False)
        fetched = _page_requests(site.requests)

    assert summary.pages_fetched == 4
    assert len(fetched) == 4
