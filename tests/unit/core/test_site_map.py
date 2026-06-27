"""Tests for deterministic sitemap and subdomain mapping."""

from __future__ import annotations

from yosoi.core.site_map import (
    MapRequest,
    _parse_subfinder_subdomains,
    _SubfinderRun,
    discover_site_map,
)


class _FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> object:
        self.calls.append(url)
        return {'html': self.pages.get(url), 'status_code': 200 if url in self.pages else 404}


class _FakeStatusFetcher:
    def __init__(self, pages: dict[str, tuple[str, int]]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> object:
        self.calls.append(url)
        html, status = self.pages.get(url, ('missing', 404))
        return {'html': html, 'status_code': status}


async def test_discover_site_map_reads_robots_nested_sitemaps_and_subdomains() -> None:
    fetcher = _FakeFetcher(
        {
            'https://example.com/robots.txt': 'User-agent: *\nSitemap: https://example.com/sitemap-index.xml\n',
            'https://example.com/sitemap-index.xml': (
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<sitemap><loc>https://example.com/news-sitemap.xml</loc></sitemap>'
                '<sitemap><loc>https://cdn.example.com/cdn-sitemap.xml</loc></sitemap>'
                '</sitemapindex>'
            ),
            'https://example.com/news-sitemap.xml': (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://example.com/news/one</loc></url>'
                '<url><loc>https://blog.example.com/post/two</loc></url>'
                '</urlset>'
            ),
            'https://cdn.example.com/cdn-sitemap.xml': (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://cdn.example.com/assets/three</loc></url>'
                '</urlset>'
            ),
        }
    )

    result = await discover_site_map(MapRequest(url='example.com', include_default_sitemaps=False), fetcher=fetcher)

    assert result.status == 'ok'
    assert result.root_host == 'example.com'
    assert result.robots_found is True
    assert [item.url for item in result.urls] == [
        'https://example.com/news/one',
        'https://blog.example.com/post/two',
        'https://cdn.example.com/assets/three',
    ]
    assert [(host.host, host.url_count, host.subdomain) for host in result.hosts] == [
        ('blog.example.com', 1, 'blog'),
        ('cdn.example.com', 1, 'cdn'),
        ('example.com', 1, None),
    ]
    assert [item.url for item in result.sitemaps] == [
        'https://example.com/sitemap-index.xml',
        'https://example.com/news-sitemap.xml',
        'https://cdn.example.com/cdn-sitemap.xml',
    ]


async def test_discover_site_map_subdomain_mode_uses_subfinder_runner() -> None:
    async def runner(request: MapRequest, domain: str) -> _SubfinderRun:
        assert domain == 'example.com'
        assert request.subfinder_timeout == 9
        return _SubfinderRun(
            stdout=('api.example.com\nblog.example.com\nexample.com\nother.test\nshop.example.com.\n'),
            stderr='',
            returncode=0,
        )

    result = await discover_site_map(
        MapRequest(url='example.com', discover_subdomains=True, max_subdomains=2, subfinder_timeout=9),
        subdomain_runner=runner,
    )

    assert result.mode == 'subdomains'
    assert result.urls == []
    assert result.sitemaps == []
    assert [(host.host, host.subdomain) for host in result.subdomains] == [
        ('api.example.com', 'api'),
        ('blog.example.com', 'blog'),
    ]
    assert result.hosts == result.subdomains


async def test_discover_site_map_subdomain_mode_reports_subfinder_install_help() -> None:
    async def runner(_request: MapRequest, _domain: str) -> _SubfinderRun:
        raise FileNotFoundError("'subfinder' was not found on PATH")

    result = await discover_site_map(
        MapRequest(url='example.com', discover_subdomains=True),
        subdomain_runner=runner,
    )

    assert result.status == 'error'
    assert result.subdomains == []
    message = result.errors[0]
    assert 'Yosoi does not install subfinder for you' in message
    assert 'go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest' in message
    assert '--subfinder-bin /path/to/subfinder' in message


def test_parse_subfinder_subdomains_ignores_logs_apex_and_invalid_hosts() -> None:
    stdout = (
        '[INF] Enumerating subdomains for example.com\n'
        '*.cdn.example.com\n'
        'api.example.com\n'
        'example.com\n'
        'http://bad.example.com\n'
        'bad host.example.com\n'
        'other.test\n'
        'API.EXAMPLE.COM.\n'
    )

    hosts = _parse_subfinder_subdomains(stdout, root_host='example.com', limit=10)

    assert hosts == ('api.example.com', 'cdn.example.com')


async def test_discover_site_map_reports_empty_when_no_sitemaps_are_found() -> None:
    result = await discover_site_map(
        MapRequest(url='https://empty.test', include_robots=False, include_default_sitemaps=False),
        fetcher=_FakeFetcher({}),
    )

    assert result.status == 'empty'
    assert result.urls == []
    assert result.robots_url is None


async def test_discover_site_map_honors_small_sitemap_cap() -> None:
    fetcher = _FakeFetcher(
        {
            'https://example.com/sitemap.xml': (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://example.com/one</loc></url>'
                '</urlset>'
            ),
            'https://example.com/sitemap_index.xml': (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://example.com/two</loc></url>'
                '</urlset>'
            ),
        }
    )

    result = await discover_site_map(
        MapRequest(url='https://example.com', include_robots=False, max_sitemaps=1),
        fetcher=fetcher,
    )

    assert result.status == 'ok'
    assert [item.url for item in result.sitemaps] == ['https://example.com/sitemap.xml']
    assert [item.url for item in result.urls] == ['https://example.com/one']
    assert fetcher.calls == ['https://example.com/sitemap.xml']


async def test_discover_site_map_does_not_retry_definitive_missing_sitemaps() -> None:
    fetcher = _FakeStatusFetcher({})

    result = await discover_site_map(
        MapRequest(url='https://empty.test', include_robots=False, include_default_sitemaps=True, max_sitemaps=1),
        fetcher=fetcher,
    )

    assert result.status == 'empty'
    assert fetcher.calls == ['https://empty.test/sitemap.xml']
    assert result.sitemaps[0].status == 'missing'


async def test_discover_site_map_treats_404_body_as_missing_not_xml_error() -> None:
    result = await discover_site_map(
        MapRequest(url='https://empty.test', include_robots=False, include_default_sitemaps=True, max_sitemaps=1),
        fetcher=_FakeStatusFetcher({'https://empty.test/sitemap.xml': ('missing', 404)}),
    )

    assert result.status == 'empty'
    assert result.sitemaps[0].status == 'missing'
    assert result.errors == []


async def test_discover_site_map_honors_url_cap_across_nested_sitemaps() -> None:
    fetcher = _FakeFetcher(
        {
            'https://example.com/sitemap.xml': (
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<sitemap><loc>https://example.com/a.xml</loc></sitemap>'
                '<sitemap><loc>https://example.com/b.xml</loc></sitemap>'
                '</sitemapindex>'
            ),
            'https://example.com/a.xml': (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://example.com/one</loc></url>'
                '<url><loc>https://example.com/two</loc></url>'
                '</urlset>'
            ),
            'https://example.com/b.xml': (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://example.com/three</loc></url>'
                '</urlset>'
            ),
        }
    )

    result = await discover_site_map(
        MapRequest(url='https://example.com', include_robots=False, max_sitemaps=3, max_urls=2),
        fetcher=fetcher,
    )

    assert [item.url for item in result.urls] == ['https://example.com/one', 'https://example.com/two']
    assert fetcher.calls == ['https://example.com/sitemap.xml', 'https://example.com/a.xml']
