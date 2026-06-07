"""page_shape generalizes across Yahoo Finance subdomains/domains/paths, splits by template."""

from __future__ import annotations

import pytest

from tests.unit.generalization.yahoo_finance_fixtures import AAPL_US, PAGES
from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import page_shape_fp


def _shape(url: str, html: str) -> str:
    return page_shape_fp(observe_html(url, html, row_selector=''))


def test_quote_family_shares_one_bucket_across_subdomains_and_paths() -> None:
    quote_shapes = {_shape(p.url, p.html) for p in PAGES if p.family == 'quote'}
    # finance.yahoo.com/quote/AAPL, .../quote/MSFT, uk.finance.yahoo.com/quote/MSFT → ONE bucket.
    assert len(quote_shapes) == 1


def test_each_template_family_is_a_distinct_bucket() -> None:
    by_family: dict[str, set[str]] = {}
    for p in PAGES:
        by_family.setdefault(p.family, set()).add(_shape(p.url, p.html))
    representative = {fam: next(iter(shapes)) for fam, shapes in by_family.items()}
    # quote, news, screener are structurally different → three different buckets.
    assert len(set(representative.values())) == len(representative) == 3


def test_page_shape_is_url_independent() -> None:
    # Same HTML, wildly different URLs (TLD, subdomain, path) → identical shape.
    a = _shape('https://finance.yahoo.com/quote/AAPL', AAPL_US)
    b = _shape('https://de.finance.yahoo.com/quote/AAPL?p=AAPL&lang=de', AAPL_US)
    c = _shape('https://www.example.test/totally/different/path', AAPL_US)
    assert a == b == c


@pytest.mark.parametrize('page', PAGES, ids=lambda p: p.url)
def test_every_fixture_yields_a_real_bucket(page) -> None:
    shape = _shape(page.url, page.html)
    assert shape.startswith('s1:')
    assert not shape.endswith('degenerate')  # all fixtures are substantial pages
