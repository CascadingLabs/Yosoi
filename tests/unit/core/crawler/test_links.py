"""Unit tests for the generic crawl link extractor (no site-specific selectors)."""

from __future__ import annotations

from yosoi.core.crawler.links import LinkExtractor


def test_extract_dedups_and_resolves_relative_links() -> None:
    html = (
        '<a href="/a">First</a>'
        '<a href="https://site.test/a">Duplicate of first</a>'
        '<a href="">empty href</a>'
        '<a href="/b">Second</a>'
    )

    links = LinkExtractor().extract(html, base_url='https://site.test/')

    assert [link.url for link in links] == ['https://site.test/a', 'https://site.test/b']


def test_extract_returns_empty_for_unparseable_input() -> None:
    assert LinkExtractor().extract(None, base_url='https://site.test/') == []  # type: ignore[arg-type]


def test_extract_filters_disallowed_hosts() -> None:
    html = '<a href="https://site.test/in">in</a><a href="https://other.test/out">out</a>'

    links = LinkExtractor().extract(html, base_url='https://site.test/', allowed_hosts={'site.test'})

    assert [link.url for link in links] == ['https://site.test/in']


def test_pagination_and_content_hint_scoring() -> None:
    html = (
        '<a href="/page/2" aria-label="Next page">Next</a>'
        '<a href="/article/why-crawlers-crawl">Why crawlers crawl</a>'
        '<a href="/misc">misc</a>'
    )

    links = {link.url.rsplit('/', 1)[-1]: link for link in LinkExtractor().extract(html, base_url='https://site.test/')}

    assert links['2'].is_pagination is True
    assert links['2'].score == 0.95
    assert links['why-crawlers-crawl'].score == 0.8
    assert links['misc'].score < 0.8
