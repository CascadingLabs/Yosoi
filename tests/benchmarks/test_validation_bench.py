"""CodSpeed benchmarks for contract validation, coercion, and the full replay.

Two layers are measured:

1. **Coercion / validation** — turning extracted raw dicts into validated
   contract instances. This runs the wrap-validator, semantic-type dispatch
   (Price/Datetime regex work) and pydantic core validation once per record.
2. **Full replay** — clean -> extract -> validate end to end on an L2 catalog.
   This is the canonical "cache hit, no LLM" cost: the number we ultimately
   want to drive down and protect from regression, since it sets the floor on
   how cheaply we can re-scrape a known domain.
"""

from __future__ import annotations

import pytest
from pytest_codspeed import BenchmarkFixture

from tests.benchmarks.fixtures import (
    BOOK_CONTAINER,
    BOOK_SELECTORS,
    QUIET_CONSOLE,
    BookContract,
    build_catalog_html,
)
from yosoi.core.cleaning.cleaner import HTMLCleaner
from yosoi.core.extraction.extractor import ContentExtractor

_URL = 'https://books.toscrape.com'


@pytest.mark.parametrize('n_items', [20, 200, 1000], ids=['small', 'medium', 'large'])
def test_validate_records(benchmark: BenchmarkFixture, n_items: int) -> None:
    """Coerce + validate N pre-extracted records (price regex, type dispatch)."""
    raw = [
        {
            'title': f'Book Number {i}',
            'price': f'£{10 + (i % 90)}.{i % 100:02d}',
            'rating': f'star-rating {("One", "Two", "Three", "Four", "Five")[i % 5]}',
        }
        for i in range(n_items)
    ]

    def run() -> list[BookContract]:
        return [BookContract.model_validate(item, context={'source_url': _URL}) for item in raw]

    result = benchmark(run)
    assert len(result) == n_items
    assert isinstance(result[0].price, float)


@pytest.mark.parametrize('n_items', [20, 200, 1000], ids=['l2-small', 'l2-medium', 'l2-large'])
def test_full_replay(benchmark: BenchmarkFixture, n_items: int) -> None:
    """End-to-end cache-replay CPU cost: clean -> extract -> validate, no LLM."""
    cleaner = HTMLCleaner(console=QUIET_CONSOLE)
    extractor = ContentExtractor(console=QUIET_CONSOLE, contract=BookContract)
    html = build_catalog_html(n_items)

    def replay() -> list[BookContract]:
        cleaned = cleaner.clean_html(html)
        items = extractor.extract_items(_URL, cleaned, BOOK_SELECTORS, BOOK_CONTAINER) or []
        return [BookContract.model_validate(item, context={'source_url': _URL}) for item in items]

    result = benchmark(replay)
    assert len(result) == n_items
