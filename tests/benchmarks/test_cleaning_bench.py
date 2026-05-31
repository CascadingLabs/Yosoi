"""CodSpeed benchmarks for HTML cleaning (the pre-extraction CPU cost).

``HTMLCleaner.clean_html`` runs on every fetch before extraction. It is the
single biggest pure-compute step on the replay path: it parses the full DOM
once with lxml, mutates it in place to strip noise, dedups list/table runs, and
collapses whitespace. Cost scales with raw HTML size, so we sweep L1 (article)
and L2 (catalog) shapes across sizes to catch both per-byte regressions and
super-linear blowups in the pruning passes.
"""

from __future__ import annotations

import pytest
from pytest_codspeed import BenchmarkFixture

from tests.benchmarks.fixtures import QUIET_CONSOLE, build_article_html, build_catalog_html
from yosoi.core.cleaning.cleaner import HTMLCleaner


@pytest.mark.parametrize('n_items', [20, 200, 1000], ids=['l2-small', 'l2-medium', 'l2-large'])
def test_clean_catalog(benchmark: BenchmarkFixture, n_items: int) -> None:
    cleaner = HTMLCleaner(console=QUIET_CONSOLE)
    html = build_catalog_html(n_items)
    result = benchmark(lambda: cleaner.clean_html(html))
    assert 'product_pod' in result
    # Noise must actually be gone, else we are benchmarking the wrong thing.
    assert '<script' not in result
    assert '<svg' not in result


@pytest.mark.parametrize('n_paragraphs', [10, 100, 600], ids=['l1-small', 'l1-medium', 'l1-large'])
def test_clean_article(benchmark: BenchmarkFixture, n_paragraphs: int) -> None:
    cleaner = HTMLCleaner(console=QUIET_CONSOLE)
    html = build_article_html(n_paragraphs)
    result = benchmark(lambda: cleaner.clean_html(html))
    assert 'headline' in result
    assert '<header' not in result
    assert '<footer' not in result
