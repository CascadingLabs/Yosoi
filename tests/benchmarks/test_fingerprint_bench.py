"""CodSpeed benchmarks for the page-fingerprint hashing path (the signal lane).

Fingerprinting is content-derived but response-INDEPENDENT: it forks off the critical path
(fetch -> extract -> return) and runs as low-priority background work. These benchmarks pin the
COST of that signal so we can prove it is cheap enough to run off-path and never has to tax
extraction latency. We measure each layer separately (the skeleton tree-walk is the dominant
term), the full ``PageFingerprint.of`` compute-once, and the read-path ``similarity`` comparison
(set Jaccard — should be near-free, since the feature sets are precomputed once).

Run locally (walltime):  uv run poe bench
"""

from __future__ import annotations

import pytest
from pytest_codspeed import BenchmarkFixture

from tests.benchmarks.fixtures import build_article_html, build_catalog_html
from yosoi.generalization.fingerprint import (
    PageFingerprint,
    page_semantics,
    page_skeleton,
    page_skeleton_fp,
)

_CATALOG_SIZES = [20, 200, 1000]
_CATALOG_IDS = ['l2-small', 'l2-medium', 'l2-large']
_ARTICLE_SIZES = [10, 100, 600]
_ARTICLE_IDS = ['l1-small', 'l1-medium', 'l1-large']


@pytest.mark.parametrize('n', _CATALOG_SIZES, ids=_CATALOG_IDS)
def test_bench_skeleton_catalog(benchmark: BenchmarkFixture, n: int) -> None:
    """The depth-D tree-walk — the dominant cost of a fingerprint."""
    html = build_catalog_html(n)
    result = benchmark(lambda: page_skeleton(html))
    assert result


@pytest.mark.parametrize('n', _CATALOG_SIZES, ids=_CATALOG_IDS)
def test_bench_fingerprint_of_catalog(benchmark: BenchmarkFixture, n: int) -> None:
    """Full compute-once (skeleton + semantics) on a repeating-item listing page."""
    html = build_catalog_html(n)
    fp = benchmark(lambda: PageFingerprint.of(html))
    assert fp.skeleton


@pytest.mark.parametrize('n', _ARTICLE_SIZES, ids=_ARTICLE_IDS)
def test_bench_fingerprint_of_article(benchmark: BenchmarkFixture, n: int) -> None:
    """Full compute-once on a single-record article page."""
    html = build_article_html(n)
    fp = benchmark(lambda: PageFingerprint.of(html))
    assert fp.skeleton


def test_bench_skeleton_fp_bucket(benchmark: BenchmarkFixture) -> None:
    """The exact-hash bucket key (mint-time index primitive)."""
    html = build_catalog_html(200)
    result = benchmark(lambda: page_skeleton_fp(html))
    assert result.startswith('t1:')


def test_bench_semantics(benchmark: BenchmarkFixture) -> None:
    """L2 landmark / heading / schema.org feature set."""
    html = build_catalog_html(200)
    result = benchmark(lambda: page_semantics(html))
    assert isinstance(result, frozenset)


def test_bench_similarity_compare(benchmark: BenchmarkFixture) -> None:
    """The read-path 'health' comparison: two PRECOMPUTED fingerprints, measure only the compare.

    This is what would run on every cache hit as a drift check — set Jaccard over the precomputed
    layer sets. It must be orders of magnitude cheaper than ``of`` for the signal lane to be free.
    """
    a = PageFingerprint.of(build_catalog_html(200))
    b = PageFingerprint.of(build_catalog_html(220))
    sim = benchmark(lambda: a.similarity(b))
    assert sim.skeleton > 0.9  # same template, slightly different row count
