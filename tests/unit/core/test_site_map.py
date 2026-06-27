"""Tests for deterministic sitemap and subdomain mapping."""

from __future__ import annotations

import pytest

from yosoi.core.site_map import (
    MapRequest,
    _fetch_text,
    _parse_sitemap,
    _parse_subfinder_subdomains,
    _run_subfinder,
    _SubfinderRun,
    discover_site_map,
    normalize_site_url,
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


class _ContextFetcher(_FakeFetcher):
    entered = False
    exited = False

    async def __aenter__(self) -> _ContextFetcher:
        self.entered = True
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exited = True


class _ClosableFetcher(_FakeFetcher):
    closed = False

    async def close(self) -> None:
        self.closed = True


async def test_map_request_and_normalize_url_validation_edges() -> None:
    assert normalize_site_url('Example.COM/path?q=1') == 'https://example.com/path?q=1'
    with pytest.raises(ValueError, match='non-empty'):
        normalize_site_url('   ')
    with pytest.raises(ValueError, match='HTTP'):
        MapRequest(url='ftp://example.com/file')


async def test_discover_site_map_owns_context_manager_fetcher(monkeypatch) -> None:
    import yosoi.core.site_map as site_map

    fetcher = _ContextFetcher(
        {
            'https://example.com/sitemap.xml': (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://example.com/one</loc></url>'
                '</urlset>'
            )
        }
    )
    monkeypatch.setattr(site_map, 'create_fetcher', lambda *_args, **_kwargs: fetcher)

    result = await discover_site_map(MapRequest(url='example.com', include_robots=False, max_sitemaps=1))

    assert result.status == 'ok'
    assert fetcher.entered is True
    assert fetcher.exited is True


async def test_discover_site_map_owns_plain_fetcher_and_closes(monkeypatch) -> None:
    import yosoi.core.site_map as site_map

    fetcher = _ClosableFetcher({})
    monkeypatch.setattr(site_map, 'create_fetcher', lambda *_args, **_kwargs: fetcher)

    result = await discover_site_map(MapRequest(url='example.com', include_robots=False, max_sitemaps=1))

    assert result.status == 'empty'
    assert fetcher.closed is True


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


@pytest.mark.parametrize(
    ('raised', 'expected'),
    [
        (TimeoutError('slow'), 'subfinder: slow'),
        (OSError('denied'), 'subfinder: denied'),
    ],
)
async def test_discover_site_map_subdomain_mode_reports_runner_errors(raised: Exception, expected: str) -> None:
    async def runner(_request: MapRequest, _domain: str) -> _SubfinderRun:
        raise raised

    result = await discover_site_map(MapRequest(url='example.com', discover_subdomains=True), subdomain_runner=runner)

    assert result.status == 'error'
    assert result.errors == [expected]


async def test_discover_site_map_subdomain_mode_reports_nonzero_runner() -> None:
    async def runner(_request: MapRequest, _domain: str) -> _SubfinderRun:
        return _SubfinderRun(stdout='fallback detail', stderr='fatal detail', returncode=2)

    result = await discover_site_map(MapRequest(url='example.com', discover_subdomains=True), subdomain_runner=runner)

    assert result.status == 'error'
    assert result.errors == ['subfinder: fatal detail']


async def test_run_subfinder_reports_missing_binary(monkeypatch) -> None:
    import yosoi.core.site_map as site_map

    monkeypatch.setattr(site_map.shutil, 'which', lambda _binary: None)

    with pytest.raises(FileNotFoundError, match='not found on PATH'):
        await _run_subfinder(MapRequest(url='example.com', subfinder_bin='missing-subfinder'), 'example.com')


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


def test_parse_sitemap_supports_feeds_links_and_reports_bad_roots() -> None:
    feed = _parse_sitemap(
        '<feed><link href="/feed-entry"/><loc>https://example.com/from-loc</loc><link href="/feed-entry"/></feed>',
        base_url='https://example.com/feed.xml',
    )
    assert feed.urls == ('https://example.com/feed-entry', 'https://example.com/from-loc')

    unsupported = _parse_sitemap('<not-a-sitemap><loc>/x</loc></not-a-sitemap>', base_url='https://example.com/s.xml')
    assert unsupported.error == "unsupported sitemap root 'not-a-sitemap'"

    malformed = _parse_sitemap('', base_url='https://example.com/s.xml')
    assert malformed.error is not None


async def test_fetch_text_raises_for_http_errors_and_no_body() -> None:
    with pytest.raises(Exception, match='HTTP 500'):
        await _fetch_text(
            _FakeStatusFetcher({'https://example.com/sitemap.xml': ('oops', 500)}), 'https://example.com/sitemap.xml'
        )
    with pytest.raises(Exception, match='returned no text'):
        await _fetch_text(_FakeFetcher({'https://example.com/sitemap.xml': ''}), 'https://example.com/sitemap.xml')


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
