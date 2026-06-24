"""Full crawl v6: crawl qscrape.dev once, then try to extract content from every page.

Run:
    uv run python examples/qscrape.dev/full_crawl_v6_content.py

This is intentionally small and framework-heavy: one crawl seed, four contracts,
then a scrape pass over every successfully crawled URL. We do not provide URL
oracles, manual exemplars, hardcoded selectors, or per-route routing. Lesson cache
is enabled so the first successful discovery per contract can accelerate later
pages; failures are written as data for the next framework iteration.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from full_crawl_v5 import SEED, NewsArticle, ProductContract, ScoreContract, _policy

import yosoi as ys


class TaxInfo(ys.Contract):
    """Tax, deed, parcel, or registry record content (no download lane)."""

    parcel_id: str = ys.Field(description='Parcel, APN, deed, or registry identifier')
    owner_name: str | None = ys.Author(description='Owner, grantee, grantor, or filer name')
    address: str | None = ys.Field(description='Property or registry address')
    tax_amount: float | None = ys.Price(description='Tax amount, fee amount, assessed value, or balance')
    status: str | None = ys.Field(description='Payment, filing, deed, or registry status')


CONTRACTS = (NewsArticle, TaxInfo, ScoreContract, ProductContract)

OUT = Path(os.getenv('YOSOI_FULL_CRAWL_V6_OUTPUT_DIR') or Path(chr(46) + 'yosoi') / 'full_crawl_v6_content')
URL_LIMIT = int(os.getenv('YOSOI_FULL_CRAWL_V6_URL_LIMIT', '0'))
SCRAPE_MAX_CONCURRENCY = int(os.getenv('YOSOI_FULL_CRAWL_V6_SCRAPE_MAX_CONCURRENCY', '8'))


def _crawl_urls(summary: Any) -> list[str]:
    urls = [result.job.url for result in summary.results if result.status == 'succeeded']
    return urls[:URL_LIMIT] if URL_LIMIT > 0 else urls


async def main() -> None:
    crawl_policy = _policy(scrape=False)
    scrape_policy = _policy(scrape=True)
    summary = await ys.crawl(SEED, policy=crawl_policy)
    urls = _crawl_urls(summary)
    semaphore = asyncio.Semaphore(max(1, SCRAPE_MAX_CONCURRENCY))
    output: dict[str, dict[str, Any]] = {}

    async def scrape_one(url: str, contract: type[ys.Contract]) -> None:
        async with semaphore:
            try:
                records = await ys.scrape(
                    url,
                    contract,
                    policy=scrape_policy,
                    allow_downloads=bool(contract.file_fields()),
                    allowed_download_types=('pdf', 'csv', 'json'),
                    max_concurrency=1,
                )
            except Exception as exc:
                output.setdefault(url, {})[contract.__name__] = {
                    'records': [],
                    'error': f'{type(exc).__name__}: {exc}',
                }
                return
            output.setdefault(url, {})[contract.__name__] = {'records': records, 'error': None}

    await asyncio.gather(*(scrape_one(url, contract) for url in urls for contract in CONTRACTS))
    await asyncio.to_thread(OUT.mkdir, parents=True, exist_ok=True)
    path = OUT / 'content_by_url_contract.json'
    path.write_text(json.dumps(output, indent=2, default=str) + '\n', encoding='utf-8')

    ys.show(summary)
    ys.show(
        {'urls': len(urls), 'contracts': [contract.__name__ for contract in CONTRACTS], 'content': str(path)},
        title='Full crawl v6 content files',
    )
    ys.show(output, title='V6 content extraction results')


if __name__ == '__main__':
    asyncio.run(main())
