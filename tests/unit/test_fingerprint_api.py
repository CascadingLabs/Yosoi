"""Tests for the high-level fingerprint API."""

import pytest

import yosoi as ys
from yosoi.models.results import FetchResult

_HTML = """
<html>
  <body>
    <main>
      <section class="catalog">
        <article><h2>Hammer</h2><p>$10</p></article>
        <article><h2>Anvil</h2><p>$50</p></article>
        <article><h2>Tongs</h2><p>$15</p></article>
        <article><h2>Bellows</h2><p>$30</p></article>
        <article><h2>Coal</h2><p>$5</p></article>
      </section>
    </main>
  </body>
</html>
"""


def test_fingerprint_accepts_html() -> None:
    fp = ys.fingerprint(_HTML)

    assert fp.skeleton
    assert fp.semantic


def test_fingerprint_accepts_fetch_result_layers() -> None:
    result = FetchResult(
        url='https://example.test/catalog',
        html=_HTML,
        headers={'server': 'test', 'set-cookie': 'session=abc; Path=/, bucket=1; Path=/'},
        endpoints=['https://api.example.test/products?page=1'],
    )

    fp = ys.fingerprint(result)

    assert fp.network
    assert fp.endpoints


def test_fingerprint_rejects_empty_fetch_result() -> None:
    with pytest.raises(ValueError, match=r'non-empty \.html'):
        ys.fingerprint(FetchResult(url='https://example.test', html=None))
