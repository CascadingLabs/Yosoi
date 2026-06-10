"""Live ``ys.crawl`` example — harvest ESPN article URLs under a 100-page budget.

Run:
    uv run python examples/crawl_espn_articles.py

Crawls ESPN from a few section fronts under a conservative, host-scoped policy
capped at 100 fetched pages, then surfaces the article URLs the crawler found
(ESPN articles live at ``/<sport>/story/_/id/<id>/...``). Real network run — no
fixtures, no mocks. Generic engine: the only ESPN-specific bit is the article
URL shape used to *filter* the discovered links, never the crawl itself.
"""

from __future__ import annotations

import asyncio
import re

import yosoi as ys

SEEDS = (
    'https://www.espn.com/nfl/',
    'https://www.espn.com/nba/',
    'https://www.espn.com/mlb/',
)
ARTICLE_URL = re.compile(r'/story/_/id/\d+/')


async def main() -> None:
    policy = ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(max_pages=100, max_depth=2, max_pages_per_host=100),
        scheduler=ys.SchedulerPolicy(max_workers=6, per_host_concurrency=2, politeness_delay=0.3),
        safety=ys.CrawlSafety(allowed_hosts=('www.espn.com',)),
        fetcher_type='simple',
    )
    summary = await ys.crawl_index(SEEDS, policy=policy)

    # Article URLs = discovered links + actually-fetched pages matching ESPN's article shape.
    candidates = {link.url for result in summary.results for link in result.discovered_links}
    candidates |= {result.job.url for result in summary.results}
    articles = sorted(url for url in candidates if ARTICLE_URL.search(url))

    print(f'pages fetched   : {summary.pages_fetched}')
    print(f'unique urls seen: {summary.unique_urls_seen}')
    print(f'article urls    : {len(articles)}')
    for url in articles[:100]:
        print(' ', url)


if __name__ == '__main__':
    asyncio.run(main())
