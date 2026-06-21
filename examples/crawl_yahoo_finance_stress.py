"""Stress Yahoo Finance article candidate discovery and scrape readiness at larger target sizes.

Run:
    uv run python examples/crawl_yahoo_finance_stress.py
    uv run python examples/crawl_yahoo_finance_stress.py --targets 100
    uv run python examples/crawl_yahoo_finance_stress.py --targets 100,1000 --max-pages 120

This intentionally reports counts, not URL dumps. Use the regular
``crawl_yahoo_finance.py`` example when you want the clean crawl -> scrape flow.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from typing import Any

from crawl_yahoo_finance import SEEDS, finance_news_crawl_policy
from rich.console import Console

import yosoi as ys


@dataclass(frozen=True)
class StressCase:
    target: int
    max_pages: int
    max_depth: int
    max_attempts: int
    timeout_seconds: float


def case_for_target(
    target: int, *, max_pages: int | None, max_depth: int | None, max_attempts: int | None
) -> StressCase:
    if target <= 100:
        pages = max_pages or 32
        depth = max_depth or 3
        attempts = max_attempts or 96
        timeout = max(90.0, pages * 3.0)
    else:
        pages = max_pages or 160
        depth = max_depth or 4
        attempts = max_attempts or 480
        timeout = max(360.0, pages * 3.0)
    return StressCase(
        target=target,
        max_pages=pages,
        max_depth=depth,
        max_attempts=attempts,
        timeout_seconds=timeout,
    )


async def run_case(case: StressCase) -> dict[str, Any]:
    started = time.perf_counter()
    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        finance_news_crawl_policy(
            max_pages=case.max_pages,
            max_depth=case.max_depth,
            max_attempts=case.max_attempts,
            politeness_delay=0.25,
        ),
    )
    try:
        async with asyncio.timeout(case.timeout_seconds):
            summary = await ys.crawl(SEEDS, contracts=ys.NewsArticle, limit=case.target, policy=policy, progress=False)
    except Exception as exc:
        return {
            'target': case.target,
            'indexed': 0,
            'scraped': 0,
            'valid': 0,
            'hit_target': False,
            'pages': 0,
            'attempted': 0,
            'seen': 0,
            'blocked': 0,
            'failed': 1,
            'seconds': f'{time.perf_counter() - started:.1f}',
            'note': f'{type(exc).__name__}: {exc}'[:100],
        }

    urls = summary.urls_for(ys.NewsArticle, limit=case.target)
    indexed = len(urls)
    scraped, valid, scrape_note = await scrape_probe(urls, policy)
    note = ''
    if indexed < case.target and summary.attempted_urls >= case.max_attempts:
        note = 'attempt budget exhausted'
    elif indexed < case.target and summary.pages_fetched >= case.max_pages:
        note = 'page budget exhausted'
    elif indexed < case.target:
        note = 'frontier exhausted'
    if scrape_note:
        note = f'{note}; {scrape_note}' if note else scrape_note
    return {
        'target': case.target,
        'indexed': indexed,
        'scraped': scraped,
        'valid': valid,
        'hit_target': indexed >= case.target,
        'pages': summary.pages_fetched,
        'attempted': summary.attempted_urls,
        'seen': summary.unique_urls_seen,
        'blocked': summary.policy_blocked,
        'failed': summary.failures,
        'seconds': f'{time.perf_counter() - started:.1f}',
        'note': note,
    }


async def scrape_probe(urls: list[str], policy: ys.Policy) -> tuple[int, int, str]:
    if not urls:
        return 0, 0, ''
    try:
        articles = await ys.scrape(urls, ys.NewsArticle, policy=policy)
    except ValueError as exc:
        if 'No model specified' in str(exc):
            return 0, 0, 'scrape skipped: no model configured'
        raise
    scraped = _count_scraped(articles)
    valid = _count_valid(articles)
    return scraped, valid, ''


def _count_scraped(value: object) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sum(_count_scraped(item) for item in value.values())
    return 0


def _count_valid(value: object) -> int:
    if isinstance(value, list):
        return sum(1 for item in value if isinstance(item, dict) and any(item.values()))
    if isinstance(value, dict):
        return sum(_count_valid(item) for item in value.values())
    return 0


async def main() -> None:
    parser = argparse.ArgumentParser(description='Stress Yahoo Finance crawl candidate growth.')
    parser.add_argument('--targets', default='100,1000', help='comma-separated article targets')
    parser.add_argument('--max-pages', type=int, default=None, help='override page budget for every case')
    parser.add_argument('--max-depth', type=int, default=None, help='override max crawl depth for every case')
    parser.add_argument('--max-attempts', type=int, default=None, help='override attempt budget for every case')
    args = parser.parse_args()

    targets = tuple(int(part.strip()) for part in args.targets.split(',') if part.strip())
    cases = [
        case_for_target(
            target,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            max_attempts=args.max_attempts,
        )
        for target in targets
    ]
    records = [await run_case(case) for case in cases]
    ys.show(records, title='Yahoo Finance article candidate stress', console=Console(width=140))


if __name__ == '__main__':
    asyncio.run(main())
