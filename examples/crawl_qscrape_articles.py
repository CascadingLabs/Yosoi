"""Crawl qscrape.dev L1, then scrape discovered news articles.

Run:
    uv run python examples/crawl_qscrape_articles.py

This is a live crawl against the maintained qscrape.dev L1 example site.
It starts at the L1 root and gives the crawler enough depth and page budget to
walk the small demo domain, find the news archive, and fetch article detail
pages. It does not pin selectors.
"""

import asyncio

import yosoi as ys

SEEDS = 'https://qscrape.dev/l1/'


async def main() -> None:
    crawl_policy = ys.Policy.for_crawl(
        'crawl.conservative',
        budget=ys.CrawlBudget(max_pages=64, max_depth=4, max_attempts=96, max_pages_per_host=64),
        scheduler=ys.SchedulerPolicy(max_workers=4, per_host_concurrency=4, politeness_delay=0),
        safety=ys.CrawlSafety(
            respect_robots=False,  # qscrape.dev is the maintained Yosoi demo target
            allow_redirects=True,  # qscrape.dev normalizes section URLs with trailing-slash redirects
            allowed_hosts=('qscrape.dev',),
            blocked_path_prefixes=('/cdn-cgi',),
        ),
        target_contracts=('NewsArticle',),
        fetcher_type='simple',
    )
    scrape_policy = ys.Policy(
        scrape=ys.ScrapePolicy(fetcher_type='simple'),
        output=ys.OutputPolicy(quiet=False, plain_output=False),
    )
    policy = ys.Policy.cascade(ys.Policy.from_env(), crawl_policy, scrape_policy)

    summary = await ys.crawl(SEEDS, contracts=ys.NewsArticle, policy=policy)
    pages = summary.urls_for(ys.NewsArticle)

    ys.show(summary.candidates_for(ys.NewsArticle), title='NewsArticle crawl candidates')
    if not pages:
        ys.show('Scrape skipped: no crawl candidates', format='plain')
        return
    if policy.model is None:
        ys.show('Scrape skipped: no model configured', format='plain')
        return

    articles = await ys.scrape(pages, ys.NewsArticle, policy=policy)
    ys.show(articles, title='NewsArticle')


if __name__ == '__main__':
    asyncio.run(main())
