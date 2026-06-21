"""Run public-web crawl stress cases with small, bounded policies.

Run:
    uv run python examples/crawl_public_stress.py

Each case uses the same public API shape:

    summary = await ys.crawl(seeds, policy=policy, progress=False)

The target list is intentionally mixed. Some sites are clean static docs, some
redirect aggressively, some expose large navigation surfaces, and some block
non-content paths. The output is a compact table so weak spots in crawl policy,
display, and fetch behavior are easy to compare.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from rich.console import Console

import yosoi as ys


@dataclass(frozen=True)
class CrawlCase:
    name: str
    seeds: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    max_pages: int = 6
    max_depth: int = 1
    max_attempts: int = 10
    allow_redirects: bool = True
    respect_robots: bool = True
    target_contracts: tuple[str, ...] = ()
    blocked_path_prefixes: tuple[str, ...] = ()
    timeout_seconds: float = 20.0


CASES = (
    CrawlCase(
        name='qscrape',
        seeds=('https://qscrape.dev/l1/news/articles/',),
        allowed_hosts=('qscrape.dev',),
        respect_robots=False,
        target_contracts=('NewsArticle',),
        max_pages=8,
        max_attempts=12,
    ),
    CrawlCase(
        name='py-peps',
        seeds=('https://peps.python.org/',),
        allowed_hosts=('peps.python.org',),
    ),
    CrawlCase(
        name='py-docs',
        seeds=('https://docs.python.org/3/',),
        allowed_hosts=('docs.python.org',),
        blocked_path_prefixes=('/3/_downloads', '/3/archives'),
    ),
    CrawlCase(
        name='wiki',
        seeds=('https://en.wikipedia.org/wiki/Main_Page',),
        allowed_hosts=('en.wikipedia.org',),
        blocked_path_prefixes=('/w/', '/wiki/Special:', '/wiki/Talk:'),
    ),
    CrawlCase(
        name='iana',
        seeds=('https://www.iana.org/domains/reserved',),
        allowed_hosts=('www.iana.org',),
    ),
    CrawlCase(
        name='w3c-tr',
        seeds=('https://www.w3.org/TR/',),
        allowed_hosts=('www.w3.org',),
        blocked_path_prefixes=('/People/', '/Consortium/'),
    ),
    CrawlCase(
        name='mdn-http',
        seeds=('https://developer.mozilla.org/en-US/docs/Web/HTTP',),
        allowed_hosts=('developer.mozilla.org',),
        blocked_path_prefixes=('/users', '/admin'),
    ),
    CrawlCase(
        name='loc',
        seeds=('https://www.loc.gov/collections/',),
        allowed_hosts=('www.loc.gov',),
        target_contracts=('NewsArticle',),
        blocked_path_prefixes=('/login', '/accounts'),
    ),
    CrawlCase(
        name='nasa',
        seeds=('https://www.nasa.gov/news/',),
        allowed_hosts=('www.nasa.gov',),
        target_contracts=('NewsArticle',),
        blocked_path_prefixes=('/wp-admin', '/wp-login'),
    ),
    CrawlCase(
        name='noaa',
        seeds=('https://www.noaa.gov/news',),
        allowed_hosts=('www.noaa.gov',),
        target_contracts=('NewsArticle',),
        blocked_path_prefixes=('/user', '/admin'),
    ),
    CrawlCase(
        name='hn',
        seeds=('https://news.ycombinator.com/',),
        allowed_hosts=('news.ycombinator.com',),
        target_contracts=('NewsArticle',),
        blocked_path_prefixes=('/login', '/logout', '/submit'),
    ),
    CrawlCase(
        name='yahoo-fin',
        seeds=('https://finance.yahoo.com/news/',),
        allowed_hosts=('finance.yahoo.com',),
        max_pages=12,
        max_depth=10,
        max_attempts=24,
        allow_redirects=False,
        target_contracts=('NewsArticle',),
        blocked_path_prefixes=(
            '/account',
            '/about',
            '/calendar',
            '/chart',
            '/login',
            '/markets',
            '/personal-finance',
            '/portfolios',
            '/quote',
            '/screener',
        ),
        timeout_seconds=45.0,
    ),
)


def policy_for(case: CrawlCase) -> ys.Policy:
    return ys.Policy.for_crawl(
        'crawl.seed_hunt',
        budget=ys.CrawlBudget(
            max_pages=case.max_pages,
            max_depth=case.max_depth,
            max_attempts=case.max_attempts,
            max_pages_per_host=case.max_pages,
            crawl_session_id=f'public-stress-{case.name}',
        ),
        scheduler=ys.SchedulerPolicy(
            max_workers=2,
            per_host_concurrency=1,
            politeness_delay=0.25,
            fetch_timeout_seconds=case.timeout_seconds,
            max_fetch_retries=1,
        ),
        safety=ys.CrawlSafety(
            respect_robots=case.respect_robots,
            allow_redirects=case.allow_redirects,
            allowed_hosts=case.allowed_hosts,
            blocked_path_prefixes=case.blocked_path_prefixes,
        ),
        target_contracts=case.target_contracts,
        fetcher_type='simple',
    )


async def run_case(case: CrawlCase) -> dict[str, Any]:
    try:
        summary = await asyncio.wait_for(
            ys.crawl(case.seeds, policy=policy_for(case), progress=False),
            timeout=case.timeout_seconds + 45.0,
        )
    except Exception as exc:
        return {
            'case': case.name,
            'outcome': 'error',
            'pages': 0,
            'attempted': 0,
            'urls_seen': 0,
            'indexed': 0,
            'blocked': 0,
            'failed': 1,
            'max_depth': case.max_depth,
            'seconds': '',
            'note': str(exc)[:80],
        }

    if summary.pages_fetched == 0:
        outcome = 'failed'
    elif summary.failures:
        outcome = 'partial'
    elif summary.policy_blocked:
        outcome = 'bounded'
    else:
        outcome = 'clean'

    return {
        'case': case.name,
        'outcome': outcome,
        'pages': summary.pages_fetched,
        'attempted': summary.attempted_urls,
        'urls_seen': summary.unique_urls_seen,
        'candidates': sum(len(urls) for urls in summary.contract_candidate_urls.values()),
        'blocked': summary.policy_blocked,
        'failed': summary.failures,
        'max_depth': case.max_depth,
        'seconds': f'{summary.wall_time:.1f}',
        'note': _note(summary),
    }


def _note(summary: ys.CrawlRunSummary) -> str:
    if summary.pages_fetched == 0:
        failed = summary.outcome_lanes.get('failed', ())
        blocked = summary.outcome_lanes.get('policy_blocked', ())
        if failed:
            return 'first fetch failed'
        if blocked:
            return 'first URL blocked'
        return 'no pages fetched'
    notes = []
    if summary.policy_blocked:
        notes.append('policy bounded')
    if summary.failures:
        notes.append('fetch failures')
    return '; '.join(notes)


async def main() -> None:
    logging.getLogger('yosoi.core.fetcher.simple').setLevel(logging.ERROR)
    records = [await run_case(case) for case in CASES]
    ys.show(records, title='Public crawl stress', console=Console(width=140))


if __name__ == '__main__':
    asyncio.run(main())
