"""Tests for route-template canonicalization (the page-class join key)."""

import pytest

from yosoi.generalization.canonicalize import (
    route_template,
    same_registrable_domain,
    same_route_class,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ('url', 'expected'),
    [
        ('https://qscrape.dev/', '/'),
        ('https://qscrape.dev/page/2/', '/page/{num}'),
        ('https://qscrape.dev/tag/love/page/1/', '/tag/love/page/{num}'),
        ('https://qscrape.dev/author/Albert-Einstein', '/author/albert-einstein'),
        ('https://x.com/r/ted/comments/1tmvpgl9k2x/title/', '/r/ted/comments/{id}/title'),
        ('https://x.com/products/48172', '/products/{num}'),
        ('https://x.com/u/9f8e7d6c5b4a3f2e1d0c/', '/u/{id}'),
        ('https://x.com/', '/'),
        ('https://x.com', '/'),
    ],
)
def test_route_template(url: str, expected: str) -> None:
    """Route templates collapse ids/nums but keep literal word segments."""
    assert route_template(url) == expected


def test_query_and_fragment_are_dropped() -> None:
    """Query string and fragment do not affect the template."""
    assert route_template('https://x.com/tag/love/page/1/?t=week#top') == '/tag/love/page/{num}'


def test_short_mixed_token_stays_literal() -> None:
    """A short (<8 char) mixed alnum token stays literal — conservative false-split.

    A 7-char id like 'abc1234' is NOT collapsed; only >=8-char mixed tokens (or
    20+ char hashes, or pure-numeric) become {id}. This biases toward redundant
    re-discovery (safe) over silently merging two page classes (a leak).
    """
    assert route_template('https://x.com/p/abc1234/') == '/p/abc1234'
    assert route_template('https://x.com/p/abc12345/') == '/p/{id}'


def test_distinct_slugs_stay_distinct() -> None:
    """Word slugs stay literal by design (no per-site slug guessing).

    Different tags do NOT share a template — the structural signal, not the route,
    carries same-subpath transfer. This pins that deliberate false-split choice.
    """
    a = route_template('https://qscrape.dev/tag/love/page/1/')
    b = route_template('https://qscrape.dev/tag/humor/page/2/')
    assert a == '/tag/love/page/{num}'
    assert b == '/tag/humor/page/{num}'
    assert a != b


def test_same_route_class_on_pagination() -> None:
    """Pagination indices collapse, so page/1 and page/9 share a class."""
    assert same_route_class('https://x.com/page/1/', 'https://x.com/page/9/')


def test_same_registrable_domain_is_host_exact() -> None:
    """Host comparison is exact (subdomains are distinct)."""
    assert same_registrable_domain('https://x.com/a', 'https://x.com/b')
    assert not same_registrable_domain('https://old.x.com/a', 'https://www.x.com/b')
    assert not same_registrable_domain('https://qscrape.dev/', 'https://quotes.toscrape.com/')
