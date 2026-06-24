"""Unit tests for the generic crawl link extractor (no site-specific selectors)."""

from __future__ import annotations

from yosoi.core.crawler.links import LinkExtractor, best_path_similarity, path_similarity


def test_has_crawlable_links_classifies_href_groups() -> None:
    extractor = LinkExtractor()

    assert extractor.has_crawlable_links('<a href="https://site.test/a">A</a>', base_url='https://site.test/') is True
    assert extractor.has_crawlable_links('<a href="/a">A</a>', base_url='https://site.test/') is True
    assert extractor.has_crawlable_links('<a href="mailto:x@y.test">mail</a>', base_url='https://site.test/') is False
    assert extractor.has_crawlable_links('<a href="tel:+15555555555">tel</a>', base_url='https://site.test/') is False
    assert extractor.has_crawlable_links('<a href="javascript:void(0)">js</a>', base_url='https://site.test/') is False
    assert extractor.has_crawlable_links('<a href="#section">fragment</a>', base_url='https://site.test/') is False


def test_has_crawlable_links_can_require_frontier_diversity() -> None:
    html = '<a href="/news/a">A</a><a href="/news/b">B</a><a href="/products/c">C</a>'
    shallow_html = '<a href="/news/a">A</a>'

    extractor = LinkExtractor()

    assert extractor.has_crawlable_links(html, base_url='https://site.test/', min_links=3, min_path_shapes=2) is True
    assert (
        extractor.has_crawlable_links(shallow_html, base_url='https://site.test/', min_links=3, min_path_shapes=2)
        is False
    )


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


def test_extracts_sitemap_xml_locations() -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://site.test/l1/news/articles</loc></url>'
        '<url><loc>/l2/scoretap/</loc></url>'
        '</urlset>'
    )

    links = LinkExtractor().extract(xml, base_url='https://site.test/sitemap.xml')

    assert [link.url for link in links] == ['https://site.test/l1/news/articles', 'https://site.test/l2/scoretap/']


def test_xml_extraction_does_not_expand_external_entities() -> None:
    xml = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE urlset [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<urlset><url><loc>https://site.test/&xxe;</loc></url></urlset>'
    )

    links = LinkExtractor().extract(xml, base_url='https://site.test/sitemap.xml', allowed_hosts={'site.test'})

    assert all('root:' not in link.url for link in links)


def test_extracts_robots_sitemap_links() -> None:
    robots = 'User-agent: *\nAllow: /\nSitemap: https://site.test/sitemap.xml\nSitemap: /extra-sitemap.xml\n'

    links = LinkExtractor().extract(robots, base_url='https://site.test/robots.txt', allowed_hosts={'site.test'})

    assert [link.url for link in links] == ['https://site.test/sitemap.xml', 'https://site.test/extra-sitemap.xml']
    assert all(link.text == 'sitemap' for link in links)


def test_extracts_rss_and_atom_links() -> None:
    rss = (
        '<?xml version="1.0"?>'
        '<rss><channel>'
        '<item><title>Story A</title><link>https://site.test/story-a</link></item>'
        '<item><title>Story B</title><link>/story-b</link></item>'
        '<entry><title>Story C</title><link href="/story-c" /></entry>'
        '</channel></rss>'
    )

    links = LinkExtractor().extract(rss, base_url='https://site.test/feed.xml')

    assert [link.url for link in links] == [
        'https://site.test/story-a',
        'https://site.test/story-b',
        'https://site.test/story-c',
    ]
    assert [link.text for link in links] == ['Story A', 'Story B', 'Story C']


def test_extract_filters_disallowed_hosts() -> None:
    html = '<a href="https://site.test/in">in</a><a href="https://other.test/out">out</a>'

    links = LinkExtractor().extract(html, base_url='https://site.test/', allowed_hosts={'site.test'})

    assert [link.url for link in links] == ['https://site.test/in']


def test_pagination_and_content_hint_scoring() -> None:
    html = (
        '<a href="/page/2" aria-label="Next page">Next</a>'
        '<a href="/article/why-crawlers-crawl">Why crawlers crawl</a>'
        '<a href="/article/why-crawlers-crawl.html">Document article</a>'
        '<a href="/misc">misc</a>'
    )

    links = {link.url.rsplit('/', 1)[-1]: link for link in LinkExtractor().extract(html, base_url='https://site.test/')}

    assert links['2'].is_pagination is True
    assert links['2'].score == 0.95
    assert links['why-crawlers-crawl'].score == 0.8
    assert links['why-crawlers-crawl.html'].score == 0.9
    assert links['misc'].score < 0.8


def test_extracts_simple_javascript_navigation_targets() -> None:
    html = (
        '<script>'
        'function openArticle(id) {'
        "  window.location.href = '/news/article?postData=' + encodeURIComponent(id);"
        '}'
        '</script>'
        '<a href="javascript:void(0)" onclick="openArticle(\'A-123\')">Read</a>'
    )

    links = LinkExtractor().extract(html, base_url='https://site.test/news/')

    assert [link.url for link in links] == ['https://site.test/news/article?postData=A-123']
    assert links[0].score == 0.85


def test_javascript_navigation_respects_allowed_hosts() -> None:
    html = (
        '<script>'
        'function openArticle(id) {'
        "  window.location.href = 'https://other.test/news/article?id=' + id;"
        '}'
        '</script>'
        '<button onclick="openArticle(\'A-123\')">Read</button>'
    )

    links = LinkExtractor().extract(html, base_url='https://site.test/news/', allowed_hosts={'site.test'})

    assert links == []


def test_extracts_encoded_javascript_navigation_payloads() -> None:
    html = (
        '<script>'
        'function openArticle(id) {'
        '  var hash = Math.random().toString(36);'
        "  var payload = 'v1-' + 'ID=' + encodeURIComponent(id) + '&HASH=' + hash + '-end';"
        "  window.location.href = '/news/article?postData=' + encodeURIComponent(payload);"
        '}'
        '</script>'
        '<a href="javascript:void(0)" onclick="openArticle(\'A-123\')">Read</a>'
    )

    links = LinkExtractor().extract(html, base_url='https://site.test/news/')

    assert [link.url for link in links] == ['https://site.test/news/article?postData=v1-ID%3DA-123%26HASH%3Dcrawl--end']


def test_is_pagination_tolerates_anchor_without_attributes() -> None:
    extractor = LinkExtractor()

    assert extractor._is_pagination(object(), 'Next page') is True
    assert extractor._is_pagination(object(), 'About us') is False


def test_path_similarity_collapses_dynamic_segments() -> None:
    assert (
        path_similarity(
            'https://site.test/news/articles/story-123.html',
            'https://site.test/news/articles/story-456.html',
        )
        == 1.0
    )
    assert (
        best_path_similarity(
            'https://site.test/news/articles/story-789.html',
            (
                'https://site.test/products/anvil',
                'https://site.test/news/articles/story-456.html',
            ),
        )
        == 1.0
    )


def test_path_similarity_collapses_terminal_article_slugs() -> None:
    assert (
        path_similarity(
            'https://site.test/news/markets/fed-cuts-rates',
            'https://site.test/news/markets/stocks-rally-after-close',
        )
        == 1.0
    )
    assert (
        path_similarity(
            'https://site.test/news/markets/fed-cuts-rates.html',
            'https://site.test/news/markets/stocks-rally-after-close.html',
        )
        == 1.0
    )


def test_path_similarity_ignores_hosts_but_not_route_shape() -> None:
    assert (
        path_similarity(
            'https://mirror.test/news/articles/story-123.html',
            'https://site.test/news/articles/story-456.html',
        )
        == 1.0
    )
    assert (
        path_similarity(
            'https://site.test/news/articles/story-123.html',
            'https://site.test/products/anvil',
        )
        < 0.72
    )
