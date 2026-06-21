"""Crawl qscrape.dev L2 for rendered NewsArticle candidates.

Run:
    uv run python examples/crawl_qscrape_l2_news_articles.py

This is a crawl-only live example. It starts at the qscrape.dev L2 root, uses
the auto fetcher so JavaScript-rendered pages are visible to the crawler, and
prints the NewsArticle crawl candidates. It does not run ys.scrape.
"""

import asyncio

import yosoi as ys

SEEDS = 'https://qscrape.dev/l2/'


async def main() -> None:
    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy.for_crawl(
            'crawl.conservative',
            budget=ys.CrawlBudget(max_pages=8, max_depth=2, max_attempts=16, max_pages_per_host=8),
            scheduler=ys.SchedulerPolicy(
                max_workers=4,
                per_host_concurrency=4,
                politeness_delay=0,
                fetch_timeout_seconds=60,
            ),
            safety=ys.CrawlSafety(
                respect_robots=False,  # qscrape.dev is the maintained Yosoi demo target
                allow_redirects=True,  # qscrape.dev normalizes section URLs with trailing-slash redirects
                allowed_hosts=('qscrape.dev',),
                blocked_path_prefixes=(
                    '/cdn-cgi',
                    '/l1/',
                    '/l3/',
                    '/l2/eshop',
                    '/l2/scoretap',
                    '/l2/taxes',
                ),
            ),
            target_contracts=('NewsArticle',),
            fetcher_type='auto',
        ),
        ys.Policy(output=ys.OutputPolicy(quiet=False, plain_output=False)),
    )

    summary = await ys.crawl(SEEDS, contracts=ys.NewsArticle, policy=policy)
    ys.show(summary.candidates_for(ys.NewsArticle), title='NewsArticle crawl candidates')


if __name__ == '__main__':
    asyncio.run(main())
