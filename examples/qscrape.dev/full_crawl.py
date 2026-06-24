"""Full neutral crawl inventory for qscrape.dev.

Run:
    uv run python examples/qscrape.dev/full_crawl.py

This is intentionally crawl-only: it discovers URL inventory and neutral scrape
candidate URLs. Multi-contract scrape routing belongs in a planner/validator
layer, not in the crawler.

The browser lane is policy-configured for a local VoidCrawl Docker CDP farm.
Override with ``YOSOI_CHROME_WS_URLS`` if your endpoints differ.
"""

from __future__ import annotations

import asyncio
import os

import yosoi as ys

SEED = 'https://qscrape.dev/'
SCRAPE_TARGET_LIMIT = int(os.getenv('YOSOI_FULL_CRAWL_SCRAPE_TARGETS', '12'))
CHROME_WS_URLS = tuple(
    url.strip()
    for url in os.getenv('YOSOI_CHROME_WS_URLS', 'http://127.0.0.1:9222,http://127.0.0.1:9223').split(',')
    if url.strip()
)


async def main() -> None:
    crawl_policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            crawl=ys.CrawlPolicy(
                budget=ys.CrawlBudget(max_pages=1_000, max_depth=4, max_attempts=1_200),
                scheduler=ys.SchedulerPolicy(
                    max_workers=16,
                    per_host_concurrency=16,
                    politeness_delay=0,
                    fetch_timeout_seconds=5,
                    max_fetch_retries=1,
                ),
                safety=ys.CrawlSafety(
                    respect_robots=False,
                    allow_redirects=True,
                    allowed_hosts=('qscrape.dev',),
                    blocked_path_prefixes=('/cdn-cgi/',),
                ),
                escalation=ys.EscalationPolicy(allow_model_discovery=False, max_llm_calls=0),
                scrape_contracts=False,
                fetcher_type='auto',
            ),
        ),
        ys.Policy(
            page=ys.PagePolicy(chrome_ws_urls=CHROME_WS_URLS),
            download=ys.DownloadPolicy(allow=False, allowed_types=()),
            output=ys.OutputPolicy(quiet=False),
        ),
    )

    summary = await ys.crawl(SEED, policy=crawl_policy)
    ys.show(summary)

    scrape_targets = summary.scrape_target_urls(limit=SCRAPE_TARGET_LIMIT)
    ys.show(scrape_targets, title='Selected neutral scrape target URLs')


if __name__ == '__main__':
    asyncio.run(main())
