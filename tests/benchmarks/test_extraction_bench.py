"""CodSpeed benchmarks for selector extraction (the parsel/CSS hot path).

On a cache hit we already hold validated selectors, so extraction is pure
parsel: parse the cleaned HTML once, then apply 3-candidate CSS selectors per
field. ``extract_items`` (multi-record catalog) re-resolves selectors *per
container*, so its cost is O(items x fields) — the most likely place for a
listing-page regression. ``extract_content_with_html`` is the single-record
path. Both are measured against pre-cleaned HTML so we isolate extraction from
cleaning.
"""

from __future__ import annotations

import pytest
from pytest_codspeed import BenchmarkFixture

from tests.benchmarks.fixtures import (
    ARTICLE_SELECTORS,
    BOOK_CONTAINER,
    BOOK_SELECTORS,
    QUIET_CONSOLE,
    ArticleContract,
    BookContract,
    build_article_html,
    build_catalog_html,
)
from yosoi.core.cleaning.cleaner import HTMLCleaner
from yosoi.core.extraction.extractor import ContentExtractor


def _clean(html: str) -> str:
    return HTMLCleaner(console=QUIET_CONSOLE).clean_html(html)


@pytest.mark.parametrize('n_items', [20, 200, 1000], ids=['l2-small', 'l2-medium', 'l2-large'])
def test_extract_items_catalog(benchmark: BenchmarkFixture, n_items: int) -> None:
    extractor = ContentExtractor(console=QUIET_CONSOLE, contract=BookContract)
    cleaned = _clean(build_catalog_html(n_items))
    result = benchmark(
        lambda: extractor.extract_items(
            'https://books.toscrape.com',
            cleaned,
            BOOK_SELECTORS,
            BOOK_CONTAINER,
        )
    )
    assert result is not None
    assert len(result) == n_items


@pytest.mark.parametrize('n_paragraphs', [10, 100, 600], ids=['l1-small', 'l1-medium', 'l1-large'])
def test_extract_content_article(benchmark: BenchmarkFixture, n_paragraphs: int) -> None:
    extractor = ContentExtractor(console=QUIET_CONSOLE, contract=ArticleContract)
    cleaned = _clean(build_article_html(n_paragraphs))
    result = benchmark(
        lambda: extractor.extract_content_with_html(
            'https://news.example.com/markets',
            cleaned,
            ARTICLE_SELECTORS,
        )
    )
    assert result is not None
    assert 'title' in result
