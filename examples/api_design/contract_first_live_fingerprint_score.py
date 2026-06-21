"""Live contract-first fingerprint scoring on qscrape.dev L1 + L2 pages.

Run:
    uv run python examples/api_design/contract_first_live_fingerprint_score.py

Figure-friendly flow:
    Contract -> seed page fingerprint -> live candidate page score -> reuse decision

L1 pages are fetched with plain HTTP. L2 pages are fetched with Yosoi's VoidCrawl-backed
HeadlessFetcher so the JavaScript-rendered DOM is fingerprinted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pydantic import Field

import yosoi as ys
from yosoi.core.fetcher.simple import SimpleFetcher
from yosoi.core.fetcher.voiddriver import HeadlessFetcher
from yosoi.models.results import FetchResult


class ProductCard(ys.Contract):
    """A product-card contract; selectors should only be reused on catalog-shaped pages."""

    name: str = ys.Title(description='Product name shown on the card')
    price: float | None = ys.Price(description='Displayed product price')
    url: str = Field(description='Product detail URL')


@dataclass(frozen=True)
class Candidate:
    label: str
    url: str


@dataclass(frozen=True)
class Environment:
    label: str
    seed_url: str
    candidates: tuple[Candidate, ...]


ENVIRONMENTS = (
    Environment(
        label='L1 static catalog environment',
        seed_url='https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing',
        candidates=(
            Candidate(
                'same contract, sibling L1 catalog', 'https://qscrape.dev/l1/eshop/catalog/?cat=Food%20%26%20Brewing'
            ),
            Candidate('different page kind, L1 news', 'https://qscrape.dev/l1/news/articles'),
        ),
    ),
    Environment(
        label='L2 rendered catalog environment',
        seed_url='https://qscrape.dev/l2/eshop/catalog?cat=Forge%20%26%20Smithing',
        candidates=(
            Candidate(
                'same contract, sibling L2 catalog', 'https://qscrape.dev/l2/eshop/catalog?cat=Food%20%26%20Brewing'
            ),
            Candidate('different page kind, L2 news', 'https://qscrape.dev/l2/news/articles'),
        ),
    ),
)


def _score_label(same_shape: bool) -> str:
    return 'propose fingerprint-tier reuse' if same_shape else 'do not reuse'


async def fetch_l1(urls: list[str]) -> dict[str, FetchResult]:
    async with SimpleFetcher(min_delay=0, max_delay=0, randomize_headers=False) as fetcher:
        results = await asyncio.gather(*(fetcher.fetch(url) for url in urls))
    return dict(zip(urls, results, strict=True))


async def fetch_l2(urls: list[str]) -> dict[str, FetchResult]:
    if not urls:
        return {}
    async with HeadlessFetcher(min_delay=0, max_delay=0, timeout=30) as fetcher:
        results = await asyncio.gather(*(fetcher.fetch(url) for url in urls))
    return dict(zip(urls, results, strict=True))


async def fetch_live_pages(urls: list[str]) -> dict[str, FetchResult]:
    l1_urls = [url for url in urls if '/l2/' not in url]
    l2_urls = [url for url in urls if '/l2/' in url]
    l1, l2 = await asyncio.gather(fetch_l1(l1_urls), fetch_l2(l2_urls))
    return {**l1, **l2}


def print_comparison(label: str, seed: FetchResult, candidate: FetchResult) -> None:
    seed_fp = ys.fingerprint(seed)
    candidate_fp = ys.fingerprint(candidate)
    similarity = seed_fp.similarity(candidate_fp)

    print(f'  {label}:')
    print(f'    candidate_url:  {candidate.url}')
    print(f'    page_score:     {similarity.score:.3f}  (0=different shape, 1=same shape)')
    print(f'    same_shape:     {similarity.same_shape}')
    print(f'    skeleton_score: {similarity.skeleton:.3f}')
    print(f'    semantic_score: {similarity.semantic:.3f}')
    print(f'    selector_reuse: {_score_label(similarity.same_shape)}')
    print()


def print_environment(environment: Environment, pages: dict[str, FetchResult]) -> None:
    seed = pages[environment.seed_url]
    print(environment.label)
    print(f'  contract:     {ProductCard.__name__}')
    print(f'  contract_fp:  {ProductCard.to_spec().fingerprint}')
    print(f'  seed_url:     {seed.url}')
    print()
    for candidate in environment.candidates:
        print_comparison(candidate.label, seed, pages[candidate.url])


def show_figure_caption() -> None:
    print('Figure caption:')
    print('  The Contract fingerprint identifies the desired data shape (ProductCard).')
    print('  Each environment has a seed page fingerprint. A live candidate page receives')
    print('  a 0..1 page_score against that seed before fingerprint-tier selector reuse.')


async def main() -> None:
    urls = [env.seed_url for env in ENVIRONMENTS]
    urls.extend(candidate.url for env in ENVIRONMENTS for candidate in env.candidates)
    pages = await fetch_live_pages(urls)

    print('Contract-first live qscrape flow:')
    print('  ProductCard contract -> L1/L2 seed fingerprints -> candidate page scores')
    print()

    for environment in ENVIRONMENTS:
        print_environment(environment, pages)

    show_figure_caption()


if __name__ == '__main__':
    asyncio.run(main())
