"""Full crawl v5: cold-start qscrape.dev crawl → generalization → scrape.

Run:
    uv run python examples/qscrape.dev/full_crawl_v5.py

This intentionally gives Yosoi only one seed and four contracts. No URL oracle,
manual exemplar list, or contrastive list is supplied. The crawl produces a
neutral fingerprint frontier; the planner fans candidate URLs into each contract;
the scrape gate then shows where cold-start routing fails. This is expected to be
noisy and is the input for v6.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from _fingerprint_plan import crawl_contract_targets

import yosoi as ys
from yosoi.models.download import DownloadRecord

SEED = 'https://qscrape.dev/'
OUT = Path(os.getenv('YOSOI_FULL_CRAWL_V5_OUTPUT_DIR') or Path(chr(46) + 'yosoi') / 'full_crawl_v5')
TOP = int(os.getenv('YOSOI_FULL_CRAWL_V5_TOP_PER_CONTRACT', '12'))
SCRAPE_TOP = int(os.getenv('YOSOI_FULL_CRAWL_V5_SCRAPE_TOP_PER_CONTRACT', '1'))
SCRAPE_FETCHER = os.getenv('YOSOI_FULL_CRAWL_V5_SCRAPE_FETCHER', 'simple')
MAX_PAGES = int(os.getenv('YOSOI_FULL_CRAWL_V5_MAX_PAGES', '1000'))
MAX_DEPTH = int(os.getenv('YOSOI_FULL_CRAWL_V5_MAX_DEPTH', '4'))
OPENROUTER_MODEL = os.getenv('YOSOI_FULL_CRAWL_V5_OPENROUTER_MODEL', 'deepseek/deepseek-chat-v3.1')
CHROME_WS_URLS = tuple(
    url.strip()
    for url in os.getenv('YOSOI_CHROME_WS_URLS', 'http://127.0.0.1:9222,http://127.0.0.1:9223').split(',')
    if url.strip()
)


class NewsArticle(ys.Contract):
    """News article record."""

    headline: str = ys.Title(description='Article headline')
    author: str | None = ys.Author(description='Article author or byline')
    date: str | None = ys.Datetime(description='Article publication date')
    category: str | None = ys.Field(description='Article category or section')
    body_text: str = ys.BodyText(description='Article body text')


class TaxInfo(ys.Contract):
    """Tax, deed, parcel, or registry record."""

    parcel_id: str = ys.Field(description='Parcel, APN, deed, or registry identifier')
    owner_name: str | None = ys.Author(description='Owner, grantee, grantor, or filer name')
    address: str | None = ys.Field(description='Property or registry address')
    tax_amount: float | None = ys.Price(description='Tax amount, fee amount, assessed value, or balance')
    status: str | None = ys.Field(description='Payment, filing, deed, or registry status')
    document: DownloadRecord | None = ys.File(
        description='Downloadable tax, deed, parcel, receipt, CSV, JSON, or PDF document',
        allowed_types=('pdf', 'csv', 'json'),
        max_bytes=5_000_000,
    )


class ScoreContract(ys.Contract):
    """Match, game, or standings row."""

    team_a: str = ys.Field(description='First team, player, or competitor name')
    team_b: str | None = ys.Field(description='Second team, player, or competitor name')
    score: str = ys.Field(description='Displayed score, result, or standing value')
    status: str | None = ys.Field(description='Match state, round, time, or final status')


class ProductContract(ys.Contract):
    """E-commerce product card or product detail."""

    name: str = ys.Title(description='Product name')
    category: str | None = ys.Field(description='Product category label')
    price: float | None = ys.Price(description='Product price as a number')
    rating: float | None = ys.Rating(as_float=True, description='Visible product rating or score')
    reviews_count: int | None = ys.Field(description='Number of reviews or ratings')
    availability: str | None = ys.Field(description='Stock or availability status')


CONTRACTS = (NewsArticle, TaxInfo, ScoreContract, ProductContract)


def _policy(*, scrape: bool) -> ys.Policy:
    fetcher = SCRAPE_FETCHER if scrape else 'auto'
    page = ys.PagePolicy(fetcher_type=fetcher, chrome_ws_urls=() if fetcher == 'simple' else CHROME_WS_URLS)
    return ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            model=ys.openrouter(OPENROUTER_MODEL) if scrape else None,
            crawl=ys.CrawlPolicy(
                budget=ys.CrawlBudget(max_pages=MAX_PAGES, max_depth=MAX_DEPTH, max_attempts=MAX_PAGES * 2),
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
            scrape=ys.ScrapePolicy(fetcher_type=fetcher, force=scrape),
            discovery=ys.DiscoveryPolicy(mode='mcp' if scrape else 'auto', lesson_cache=True),
            page=page,
            download=ys.DownloadPolicy(allow=True, allowed_types=('pdf', 'csv', 'json')),
            fingerprint=ys.FingerprintPolicy(),
            output=ys.OutputPolicy(quiet=False),
        ),
    )


async def _scrape_gate(result: Any, policy: ys.Policy) -> dict[str, Any]:
    if SCRAPE_TOP <= 0:
        return {}
    output: dict[str, Any] = {}
    for contract in CONTRACTS:
        urls = result.plan.neutral_candidate_urls(contract, limit=SCRAPE_TOP)
        output[contract.__name__] = {}
        for url in urls:
            try:
                records = await ys.scrape(
                    url,
                    contract,
                    policy=policy,
                    allow_downloads=bool(contract.file_fields()),
                    allowed_download_types=('pdf', 'csv', 'json'),
                    max_concurrency=1,
                )
            except Exception as exc:
                output[contract.__name__][url] = {'records': [], 'error': f'{type(exc).__name__}: {exc}'}
                continue
            output[contract.__name__][url] = {'records': records, 'error': None}
    path = OUT / 'scrape_gate_failures.json'
    path.write_text(json.dumps(output, indent=2, default=str) + '\n', encoding='utf-8')
    return output


async def main() -> None:
    scrape_policy = _policy(scrape=True)
    result = await crawl_contract_targets(
        SEED,
        CONTRACTS,
        crawl_policy=_policy(scrape=False),
        scrape_policy=scrape_policy,
        output_dir=OUT,
        include_query_strings=True,
        max_targets_per_contract=TOP,
        scrape_top_per_contract=0,
        scrape_max_concurrency=4,
    )
    result.scrape_results.update(await _scrape_gate(result, scrape_policy))
    ys.show(result.summary)
    ys.show(result.plan.as_rows(), title='V5 cold-start neutral fingerprint fanout')
    ys.show(
        {**result.inventory_paths, 'scrape_gate_failures': str(OUT / 'scrape_gate_failures.json')},
        title='Full crawl v5 files',
    )
    if result.scrape_results:
        ys.show(result.scrape_results, title='V5 scrape gate results')


if __name__ == '__main__':
    asyncio.run(main())
