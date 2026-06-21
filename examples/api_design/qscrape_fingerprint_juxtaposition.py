"""Juxtapose live qscrape L1/L2 product and news page fingerprints.

Run:
    uv run python examples/api_design/qscrape_fingerprint_juxtaposition.py

Figure-friendly idea:
    same live page -> scores against named reference environments

Rows are candidate pages. Columns are reference fingerprints. The highest score is the
"what is this similar to?" classification evidence a human can inspect.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import yosoi as ys
from yosoi.core.fetcher.simple import SimpleFetcher
from yosoi.core.fetcher.voiddriver import HeadlessFetcher
from yosoi.models.results import FetchResult


@dataclass(frozen=True)
class LivePage:
    label: str
    url: str
    contract: type[ys.Contract]


PAGES = (
    LivePage('L1 product catalog', 'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing', ys.Product),
    LivePage('L1 news index', 'https://qscrape.dev/l1/news/articles', ys.NewsArticle),
    LivePage('L2 product catalog', 'https://qscrape.dev/l2/eshop/catalog?cat=Forge%20%26%20Smithing', ys.Product),
    LivePage('L2 news index', 'https://qscrape.dev/l2/news/articles', ys.NewsArticle),
)


async def fetch_l1(urls: list[str]) -> dict[str, FetchResult]:
    async with SimpleFetcher(min_delay=0, max_delay=0, randomize_headers=False) as fetcher:
        results = await asyncio.gather(*(fetcher.fetch(url) for url in urls))
    return dict(zip(urls, results, strict=True))


async def fetch_l2(urls: list[str]) -> dict[str, FetchResult]:
    async with HeadlessFetcher(min_delay=0, max_delay=0, timeout=30) as fetcher:
        results = await asyncio.gather(*(fetcher.fetch(url) for url in urls))
    return dict(zip(urls, results, strict=True))


async def fetch_pages() -> dict[str, FetchResult]:
    l1_urls = [page.url for page in PAGES if '/l2/' not in page.url]
    l2_urls = [page.url for page in PAGES if '/l2/' in page.url]
    l1, l2 = await asyncio.gather(fetch_l1(l1_urls), fetch_l2(l2_urls))
    return {**l1, **l2}


def print_reference_contracts() -> None:
    print('Reference contracts:')
    for contract in (ys.Product, ys.NewsArticle):
        print(f'  {contract.__name__}: {contract.to_spec().fingerprint}')
    print()


def print_similarity_matrix(results: dict[str, FetchResult]) -> None:
    fingerprints = {page.label: ys.fingerprint(results[page.url]) for page in PAGES}
    width = 18
    print('Fingerprint score matrix (candidate row -> reference column)')
    print(' ' * width + ''.join(f'{page.label[:17]:>18}' for page in PAGES))
    for candidate in PAGES:
        cells: list[str] = []
        best_label = ''
        best_score = -1.0
        for reference in PAGES:
            sim = fingerprints[candidate.label].similarity(fingerprints[reference.label])
            cells.append(f'{sim.score:>18.3f}')
            if sim.score > best_score:
                best_score = sim.score
                best_label = reference.label
        print(f'{candidate.label[:17]:<{width}}' + ''.join(cells) + f'   best: {best_label}')
    print()


def print_human_evidence(results: dict[str, FetchResult]) -> None:
    fingerprints = {page.label: ys.fingerprint(results[page.url]) for page in PAGES}
    examples = [
        ('same contract across render tier', 'L1 product catalog', 'L2 product catalog'),
        ('different contract on same site level', 'L1 product catalog', 'L1 news index'),
        ('same contract across render tier', 'L1 news index', 'L2 news index'),
        ('different contract on rendered tier', 'L2 product catalog', 'L2 news index'),
    ]
    print('Human-verifiable pair evidence:')
    for label, left, right in examples:
        sim = fingerprints[left].similarity(fingerprints[right])
        print(f'  {label}: {left} vs {right}')
        print(f'    score={sim.score:.3f} same_shape={sim.same_shape}')
        print(f'    skeleton={sim.skeleton:.3f} semantic={sim.semantic:.3f} identity={sim.identity}')
        print(f'    ax={sim.ax} network={sim.network} endpoint={sim.endpoint}')
    print()


async def main() -> None:
    print('Live qscrape fingerprint juxtaposition')
    print('  L1/L2 product catalogs vs L1/L2 news pages')
    print()
    results = await fetch_pages()
    print_reference_contracts()
    print_similarity_matrix(results)
    print_human_evidence(results)
    print('Figure caption: candidates are classified by nearest named reference fingerprint;')
    print('layer scores make the classification auditable instead of opaque.')


if __name__ == '__main__':
    asyncio.run(main())
