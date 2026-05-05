"""End-to-end preprocessor tests + spike success-condition harness.

The CAS-18 success criterion is *binary*: median ``tokens_out / tokens_in``
across the fixture set must be below 0.7. We assert it here as part of the
unit suite so a regression flips CI red. Also covers the non-regression
condition by running the full pipeline through the public API and checking
selector-relevant content survives.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest
from parsel import Selector

from yosoi.core.cleaning.cleaner import HTMLCleaner
from yosoi.core.cleaning.preprocess import HTMLPreprocessor

FIXTURE_DIR = Path(__file__).parents[4] / 'data' / 'preprocess'
FIXTURES = sorted(p for p in FIXTURE_DIR.glob('*.html'))


def test_fixture_set_is_5_to_10_pages() -> None:
    """Sanity check: the spike requires 5-10 representative fixtures."""
    n = len(FIXTURES)
    assert 5 <= n <= 10, f'found {n}: {[p.name for p in FIXTURES]}'


@pytest.fixture
def preprocessor() -> HTMLPreprocessor:
    return HTMLPreprocessor()


@pytest.fixture
def cleaner() -> HTMLCleaner:
    from rich.console import Console

    return HTMLCleaner(console=Console(quiet=True))


@pytest.mark.parametrize('fixture_path', FIXTURES, ids=lambda p: p.name)
def test_preprocess_reduces_tokens(fixture_path: Path, preprocessor: HTMLPreprocessor) -> None:
    """Each fixture must shrink and report the expected tier label.

    Preprocess runs on RAW HTML — when ``use_experimental_preprocess`` is on
    it replaces ``HTMLCleaner.clean_html``, so ``tokens_in`` is the raw page
    and ``tokens_out`` is what the LLM sees.
    """
    raw = fixture_path.read_text()
    result = preprocessor.preprocess(raw)
    assert result.tokens_out <= result.tokens_in, fixture_path.name
    assert result.tier_applied == 'tier1+tier2'


def test_median_token_reduction_meets_spike_target(preprocessor: HTMLPreprocessor) -> None:
    """CAS-18 success condition #1: median ratio < 0.7 across fixtures."""
    ratios: list[float] = []
    for path in FIXTURES:
        raw = path.read_text()
        result = preprocessor.preprocess(raw)
        ratios.append(result.reduction_ratio)
    median_ratio = statistics.median(ratios)
    assert median_ratio < 0.7, f'median ratio {median_ratio:.3f} >= 0.7 across {ratios}'


def test_preprocess_idempotent(preprocessor: HTMLPreprocessor) -> None:
    """A second pass over the output must not shrink it further (much)."""
    raw = (FIXTURE_DIR / 'wordpress_article.html').read_text()
    once = preprocessor.preprocess(raw).html
    twice = preprocessor.preprocess(once).html
    # Allow tiny serialization differences but the byte size should not drop > 5%.
    assert len(twice) >= len(once) * 0.95


def test_preprocess_handles_empty_input(preprocessor: HTMLPreprocessor) -> None:
    result = preprocessor.preprocess('')
    assert result.tokens_in == 0
    assert result.tier_applied == 'none'
    assert result.transform_count == 0


def test_preprocess_handles_fragment(preprocessor: HTMLPreprocessor) -> None:
    """Snippets without a root element are wrapped, never crash."""
    result = preprocessor.preprocess('<p>hello</p><p>world</p>')
    assert 'hello' in result.html
    assert 'world' in result.html


# ---------------------------------------------------------------------------
# Non-regression: selector-relevant content survives.
# ---------------------------------------------------------------------------


def test_preserves_text_content_for_known_selectors(preprocessor: HTMLPreprocessor) -> None:
    """A discoverable selector against the post-preprocess HTML still resolves
    to the same text the source page contained.
    """
    raw = (FIXTURE_DIR / 'wordpress_article.html').read_text()
    out = preprocessor.preprocess(raw).html
    sel = Selector(text=out)
    headlines = sel.css('h1.entry-title::text').getall()
    assert headlines, 'headline class lost'
    assert 'Why Async Python Matters' in headlines[0]
    bylines = sel.css('.author-name::text').getall()
    assert bylines, 'author class lost'
    assert 'Andrew B.' in bylines[0]


def test_preserves_jsonld_structured_data(preprocessor: HTMLPreprocessor) -> None:
    raw = (FIXTURE_DIR / 'react_app.html').read_text()
    out = preprocessor.preprocess(raw).html
    assert 'NewsArticle' in out
    assert 'Jane Reporter' in out


def test_caps_huge_hydration_json(preprocessor: HTMLPreprocessor) -> None:
    """Next.js fixture's ``__NEXT_DATA__`` exceeds the 50KB cap; verify trim."""
    raw = (FIXTURE_DIR / 'next_js_product.html').read_text()
    result = preprocessor.preprocess(raw)
    assert result.per_transform['cap_hydration_json'] >= 1
    assert 'yosoi:elided' in result.html
