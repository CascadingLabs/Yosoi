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


def test_fingerprint_similarity_returns_zero_to_one_score() -> None:
    html = """
    <html><body><main class="catalog">
      <section class="hero"><h1>Catalog</h1><p>Intro</p></section>
      <section class="filters"><form><input name="q"><button>Go</button></form></section>
      <section class="grid"><article class="card"><h2>Hammer</h2><a href="/a">View</a><img src="x"></article></section>
      <aside class="promo"><ul><li>One</li><li>Two</li></ul></aside>
      <footer><nav><a href="/help">Help</a></nav></footer>
    </main></body></html>
    """
    left = ys.fingerprint(html)
    right = ys.fingerprint(html.replace('Hammer', 'Mallet'))

    similarity = left.similarity(right)

    assert 0.0 <= similarity.score <= 1.0
    assert similarity.score == pytest.approx(1.0)


def test_fingerprint_rejects_empty_fetch_result() -> None:
    with pytest.raises(ValueError, match=r'non-empty \.html'):
        ys.fingerprint(FetchResult(url='https://example.test', html=None))
