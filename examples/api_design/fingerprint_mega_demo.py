"""One-shot fingerprint demo: contract -> live pages -> similarity evidence.

Run:
    uv run python examples/api_design/fingerprint_mega_demo.py

What it demonstrates:
1. Contract-first identity: Product and NewsArticle have stable contract fingerprints.
2. Live environment fingerprints: qscrape L1 pages use plain HTTP; L2 pages use rendered DOM.
3. "What is this similar to?": each candidate is scored against named reference pages.
4. Human-verifiable evidence: layer scores explain why reuse is proposed or refused.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import yosoi as ys
from yosoi.core.fetcher.simple import SimpleFetcher
from yosoi.core.fetcher.voiddriver import HeadlessFetcher
from yosoi.models.results import FetchResult


@dataclass(frozen=True)
class ReferencePage:
    label: str
    url: str
    contract: type[ys.Contract]
    rendered: bool


REFERENCES = (
    ReferencePage(
        'L1 Product catalog', 'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing', ys.Product, False
    ),
    ReferencePage('L1 News index', 'https://qscrape.dev/l1/news/articles', ys.NewsArticle, False),
    ReferencePage(
        'L2 Product catalog', 'https://qscrape.dev/l2/eshop/catalog?cat=Forge%20%26%20Smithing', ys.Product, True
    ),
    ReferencePage('L2 News index', 'https://qscrape.dev/l2/news/articles', ys.NewsArticle, True),
)


async def fetch_static(urls: list[str]) -> dict[str, FetchResult]:
    async with SimpleFetcher(min_delay=0, max_delay=0, randomize_headers=False) as fetcher:
        results = await asyncio.gather(*(fetcher.fetch(url) for url in urls))
    return dict(zip(urls, results, strict=True))


async def fetch_rendered(urls: list[str]) -> dict[str, FetchResult]:
    async with HeadlessFetcher(min_delay=0, max_delay=0, timeout=30) as fetcher:
        results = await asyncio.gather(*(fetcher.fetch(url) for url in urls))
    return dict(zip(urls, results, strict=True))


async def fetch_all() -> dict[str, FetchResult]:
    static_urls = [page.url for page in REFERENCES if not page.rendered]
    rendered_urls = [page.url for page in REFERENCES if page.rendered]
    static, rendered = await asyncio.gather(fetch_static(static_urls), fetch_rendered(rendered_urls))
    return {**static, **rendered}


def print_contracts() -> None:
    print('1) Contract identity')
    for contract in (ys.Product, ys.NewsArticle):
        spec = contract.to_spec()
        print(f'   {contract.__name__:<12} contract_fp={spec.fingerprint} fields={", ".join(spec.fields)}')
    print()


def print_page_inventory(results: dict[str, FetchResult]) -> None:
    print('2) Live page fingerprints')
    for page in REFERENCES:
        result = results[page.url]
        fp = ys.fingerprint(result)
        tier = 'rendered L2' if page.rendered else 'static L1'
        print(
            f'   {page.label:<20} tier={tier:<11} '
            f'skeleton_features={len(fp.skeleton):<3} semantic_features={len(fp.semantic):<3} degenerate={fp.degenerate}'
        )
    print()


def best_match(candidate: ReferencePage, fingerprints: dict[str, object]) -> tuple[ReferencePage, object]:
    best_page = REFERENCES[0]
    best_similarity = fingerprints[candidate.label].similarity(fingerprints[best_page.label])  # type: ignore[attr-defined]
    for reference in REFERENCES[1:]:
        similarity = fingerprints[candidate.label].similarity(fingerprints[reference.label])  # type: ignore[attr-defined]
        if similarity.score > best_similarity.score:
            best_page = reference
            best_similarity = similarity
    return best_page, best_similarity


def print_similarity_matrix(fingerprints: dict[str, object]) -> None:
    print('3) Similarity matrix: candidate row -> named reference column')
    label_width = 22
    print(' ' * label_width + ''.join(f'{page.label[:18]:>20}' for page in REFERENCES) + '   best match')
    for candidate in REFERENCES:
        cells = []
        for reference in REFERENCES:
            similarity = fingerprints[candidate.label].similarity(fingerprints[reference.label])  # type: ignore[attr-defined]
            cells.append(f'{similarity.score:>20.3f}')
        match, _ = best_match(candidate, fingerprints)
        print(f'{candidate.label:<{label_width}}' + ''.join(cells) + f'   {match.label}')
    print()


def print_pair_evidence(fingerprints: dict[str, object]) -> None:
    print('4) Human-verifiable evidence for key pairs')
    pairs = (
        ('same contract, L1 sibling check', 'L1 Product catalog', 'L2 Product catalog'),
        ('different contract, L1', 'L1 Product catalog', 'L1 News index'),
        ('same contract, news tier check', 'L1 News index', 'L2 News index'),
        ('different contract, L2', 'L2 Product catalog', 'L2 News index'),
    )
    for title, left, right in pairs:
        similarity = fingerprints[left].similarity(fingerprints[right])  # type: ignore[attr-defined]
        decision = 'propose reuse' if similarity.same_shape else 'refuse reuse'
        print(f'   {title}')
        print(f'      {left}  <->  {right}')
        print(f'      score={similarity.score:.3f} same_shape={similarity.same_shape} decision={decision}')
        print(
            f'      layers: skeleton={similarity.skeleton:.3f}, semantic={similarity.semantic:.3f}, '
            f'identity={similarity.identity}, ax={similarity.ax}, network={similarity.network}'
        )
    print()


def print_takeaway() -> None:
    print('5) Takeaway')
    print('   Contract fingerprint: identifies the data contract.')
    print('   Page fingerprint score: identifies whether a live page resembles a known environment.')
    print('   Later stack should move this into a generic classification module, not crawler-only code.')


async def main() -> None:
    print('Yosoi fingerprint mega demo')
    print('=' * 80)
    results = await fetch_all()
    fingerprints = {page.label: ys.fingerprint(results[page.url]) for page in REFERENCES}

    print_contracts()
    print_page_inventory(results)
    print_similarity_matrix(fingerprints)
    print_pair_evidence(fingerprints)
    print_takeaway()


if __name__ == '__main__':
    asyncio.run(main())
