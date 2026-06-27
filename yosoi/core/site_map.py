"""Deterministic sitemap and subdomain discovery for ``ys.map``."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin, urlparse, urlunparse

import lxml.etree
from pydantic import BaseModel, Field, field_validator
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from yosoi.core.crawler.frontier import canonicalize_url
from yosoi.core.crawler.links import LinkExtractor
from yosoi.core.fetcher import create_fetcher
from yosoi.models.results import FetchResult
from yosoi.utils.exceptions import YosoiError

SitemapSource = Literal['robots', 'default', 'nested']
SitemapStatus = Literal['ok', 'missing', 'error', 'skipped']


class SiteMapFetchError(YosoiError):
    """Raised when a sitemap resource fetch should be retried."""


class SiteMapMissingError(YosoiError):
    """Raised when a sitemap resource is definitively absent."""


class MapRequest(BaseModel):
    """Canonical request for ``ys.map`` / ``yosoi map``."""

    url: str
    max_sitemaps: int = Field(default=20, ge=1)
    max_urls: int = Field(default=500, ge=1)
    max_subdomains: int = Field(default=500, ge=1)
    subfinder_bin: str = Field(default='subfinder', min_length=1)
    subfinder_timeout: int = Field(default=60, ge=1)
    include_robots: bool = True
    include_default_sitemaps: bool = True
    include_subdomains: bool = True
    discover_subdomains: bool = False

    @field_validator('url')
    @classmethod
    def _url_is_http(cls, value: str) -> str:
        normalized = normalize_site_url(value)
        parsed = urlparse(normalized)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('url must be an absolute HTTP(S) URL or hostname')
        return normalized


class MapUrl(BaseModel):
    """One URL discovered from a sitemap."""

    url: str
    host: str
    path: str
    subdomain: str | None = None
    source_sitemap: str


class MapHost(BaseModel):
    """Host inventory derived from discovered map URLs."""

    host: str
    url_count: int
    subdomain: str | None = None


class MapSitemap(BaseModel):
    """One sitemap probe and its outcome."""

    url: str
    source: SitemapSource
    status: SitemapStatus
    url_count: int = 0
    sitemap_count: int = 0
    error: str | None = None


class MapResult(BaseModel):
    """Machine-readable sitemap inventory."""

    status: Literal['ok', 'empty', 'error'] = 'ok'
    requested_url: str
    root_url: str
    root_host: str
    robots_url: str | None = None
    robots_found: bool = False
    mode: Literal['sitemap', 'subdomains'] = 'sitemap'
    sitemaps: list[MapSitemap] = Field(default_factory=list)
    urls: list[MapUrl] = Field(default_factory=list)
    hosts: list[MapHost] = Field(default_factory=list)
    subdomains: list[MapHost] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _QueuedSitemap:
    url: str
    source: SitemapSource


@dataclass(frozen=True, slots=True)
class _SubfinderRun:
    stdout: str
    stderr: str
    returncode: int


SubdomainRunner = Callable[[MapRequest, str], Awaitable[_SubfinderRun]]


def normalize_site_url(value: str) -> str:
    """Normalize a host or URL into an HTTP(S) URL."""
    raw = value.strip()
    if not raw:
        raise ValueError('url must be non-empty')
    if '://' not in raw:
        raw = f'https://{raw}'
    parsed = urlparse(raw)
    path = parsed.path or '/'
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, '', parsed.query, ''))


async def discover_site_map(
    request: MapRequest, *, fetcher: Any | None = None, subdomain_runner: SubdomainRunner | None = None
) -> MapResult:
    """Discover sitemap URLs and host inventory for a site."""
    root_url = _origin(request.url)
    root_host = _display_root_host(urlparse(root_url).hostname or '')
    robots_url = urljoin(root_url, '/robots.txt')
    if request.discover_subdomains:
        return await _discover_subdomains(request=request, root_url=root_url, runner=subdomain_runner)

    owns_fetcher = fetcher is None
    active_fetcher = fetcher or create_fetcher(
        'simple',
        min_delay=0,
        max_delay=0,
        timeout=10,
        min_content_length=1,
        randomize_headers=False,
    )

    sitemap_queue: list[_QueuedSitemap] = []
    sitemap_results: dict[str, MapSitemap] = {}
    discovered_urls: dict[str, MapUrl] = {}
    errors: list[str] = []
    robots_found = False

    try:
        if hasattr(active_fetcher, '__aenter__') and hasattr(active_fetcher, '__aexit__') and owns_fetcher:
            async with active_fetcher:
                return await _discover_with_fetcher(
                    request=request,
                    fetcher=active_fetcher,
                    root_url=root_url,
                    root_host=root_host,
                    robots_url=robots_url,
                    sitemap_queue=sitemap_queue,
                    sitemap_results=sitemap_results,
                    discovered_urls=discovered_urls,
                    errors=errors,
                    robots_found=robots_found,
                )
        return await _discover_with_fetcher(
            request=request,
            fetcher=active_fetcher,
            root_url=root_url,
            root_host=root_host,
            robots_url=robots_url,
            sitemap_queue=sitemap_queue,
            sitemap_results=sitemap_results,
            discovered_urls=discovered_urls,
            errors=errors,
            robots_found=robots_found,
        )
    finally:
        if owns_fetcher and hasattr(active_fetcher, 'close') and not hasattr(active_fetcher, '__aexit__'):
            await active_fetcher.close()


async def _discover_subdomains(
    *, request: MapRequest, root_url: str, runner: SubdomainRunner | None = None
) -> MapResult:
    root_host = _display_root_host(urlparse(root_url).hostname or '')
    discovered: dict[str, MapHost] = {}
    errors: list[str] = []
    try:
        run = await (runner or _run_subfinder)(request, root_host)
    except FileNotFoundError as exc:
        errors.append(f'subfinder: {_subfinder_install_help(request.subfinder_bin, str(exc))}')
    except TimeoutError as exc:
        errors.append(f'subfinder: {exc}')
    except OSError as exc:
        errors.append(f'subfinder: {exc}')
    else:
        if run.returncode != 0:
            detail = run.stderr.strip() or run.stdout.strip() or f'exited with code {run.returncode}'
            errors.append(f'subfinder: {detail}')
        else:
            for host in _parse_subfinder_subdomains(run.stdout, root_host=root_host, limit=request.max_subdomains):
                discovered[host] = MapHost(host=host, url_count=0, subdomain=_subdomain_for(host, root_host))
    hosts = sorted(discovered.values(), key=lambda item: item.host)
    status: Literal['ok', 'empty', 'error'] = 'ok'
    if not hosts:
        status = 'error' if errors else 'empty'
    return MapResult(
        status=status,
        mode='subdomains',
        requested_url=request.url,
        root_url=root_url,
        root_host=root_host,
        hosts=hosts,
        subdomains=hosts,
        errors=errors,
    )


async def _run_subfinder(request: MapRequest, root_host: str) -> _SubfinderRun:
    binary = shutil.which(request.subfinder_bin)
    if binary is None:
        raise FileNotFoundError(f'{request.subfinder_bin!r} was not found on PATH')
    process = await asyncio.create_subprocess_exec(
        binary,
        '-silent',
        '-d',
        root_host,
        '-timeout',
        str(request.subfinder_timeout),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=request.subfinder_timeout + 5
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise TimeoutError(f'exceeded {request.subfinder_timeout}s timeout') from None
    return _SubfinderRun(
        stdout=stdout_bytes.decode('utf-8', errors='replace'),
        stderr=stderr_bytes.decode('utf-8', errors='replace'),
        returncode=process.returncode or 0,
    )


def _subfinder_install_help(_binary: str, detail: str) -> str:
    return (
        f'{detail}. Yosoi does not install subfinder for you. Install ProjectDiscovery subfinder on this '
        'machine, then verify it with `subfinder -version`. Common options: '
        '`brew install subfinder` on macOS/Linux with Homebrew, or '
        '`go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest` with Go '
        '(ensure your Go bin directory is on PATH). If it is already installed elsewhere, pass '
        '`--subfinder-bin /path/to/subfinder`.'
    )


async def _discover_with_fetcher(
    *,
    request: MapRequest,
    fetcher: Any,
    root_url: str,
    root_host: str,
    robots_url: str,
    sitemap_queue: list[_QueuedSitemap],
    sitemap_results: dict[str, MapSitemap],
    discovered_urls: dict[str, MapUrl],
    errors: list[str],
    robots_found: bool,
) -> MapResult:
    if request.include_robots:
        robots_text = await _fetch_optional_text(fetcher, robots_url)
        if robots_text:
            robots_found = True
            for link in LinkExtractor().extract(robots_text, base_url=robots_url):
                _queue_sitemap(
                    sitemap_queue,
                    sitemap_results,
                    link.url,
                    source='robots',
                    max_sitemaps=request.max_sitemaps,
                )

    if request.include_default_sitemaps:
        for raw_path in ('/sitemap.xml', '/sitemap_index.xml'):
            _queue_sitemap(
                sitemap_queue,
                sitemap_results,
                urljoin(root_url, raw_path),
                source='default',
                max_sitemaps=request.max_sitemaps,
            )

    await _consume_sitemap_queue(
        request=request,
        fetcher=fetcher,
        queue=sitemap_queue,
        sitemap_results=sitemap_results,
        discovered_urls=discovered_urls,
        errors=errors,
        root_host=root_host,
        include_subdomains=request.include_subdomains,
    )

    hosts = _host_inventory(
        discovered_urls.values(), root_host=root_host, include_subdomains=request.include_subdomains
    )
    status: Literal['ok', 'empty', 'error'] = 'ok'
    if not discovered_urls:
        status = 'error' if errors else 'empty'
    return MapResult(
        status=status,
        requested_url=request.url,
        root_url=root_url,
        root_host=root_host,
        robots_url=robots_url if request.include_robots else None,
        robots_found=robots_found,
        sitemaps=list(sitemap_results.values()),
        urls=list(discovered_urls.values()),
        hosts=hosts,
        subdomains=[host for host in hosts if host.subdomain is not None] if request.include_subdomains else [],
        errors=errors,
    )


async def _consume_sitemap_queue(
    *,
    request: MapRequest,
    fetcher: Any,
    queue: list[_QueuedSitemap],
    sitemap_results: dict[str, MapSitemap],
    discovered_urls: dict[str, MapUrl],
    errors: list[str],
    root_host: str,
    include_subdomains: bool,
) -> None:
    cursor = 0
    while cursor < len(queue) and len(discovered_urls) < request.max_urls:
        queued = queue[cursor]
        cursor += 1
        if sitemap_results[queued.url].status != 'skipped':
            continue
        await _process_queued_sitemap(
            request=request,
            fetcher=fetcher,
            queued=queued,
            nested_insert_at=cursor,
            queue=queue,
            sitemap_results=sitemap_results,
            discovered_urls=discovered_urls,
            errors=errors,
            root_host=root_host,
            include_subdomains=include_subdomains,
        )


async def _process_queued_sitemap(
    *,
    request: MapRequest,
    fetcher: Any,
    queued: _QueuedSitemap,
    nested_insert_at: int,
    queue: list[_QueuedSitemap],
    sitemap_results: dict[str, MapSitemap],
    discovered_urls: dict[str, MapUrl],
    errors: list[str],
    root_host: str,
    include_subdomains: bool,
) -> None:
    text = await _fetch_optional_text(fetcher, queued.url)
    if not text:
        sitemap_results[queued.url] = sitemap_results[queued.url].model_copy(update={'status': 'missing'})
        return
    parsed = _parse_sitemap(text, base_url=queued.url)
    if parsed.error:
        errors.append(f'{queued.url}: {parsed.error}')
        sitemap_results[queued.url] = sitemap_results[queued.url].model_copy(
            update={'status': 'error', 'error': parsed.error}
        )
        return
    accepted_urls = _record_sitemap_urls(
        parsed.urls,
        discovered_urls=discovered_urls,
        max_urls=request.max_urls,
        root_host=root_host,
        include_subdomains=include_subdomains,
        source_sitemap=queued.url,
    )
    for offset, nested in enumerate(parsed.sitemaps):
        _queue_sitemap(
            queue,
            sitemap_results,
            nested,
            source='nested',
            max_sitemaps=request.max_sitemaps,
            insert_at=nested_insert_at + offset,
        )
    sitemap_results[queued.url] = sitemap_results[queued.url].model_copy(
        update={'status': 'ok', 'url_count': accepted_urls, 'sitemap_count': len(parsed.sitemaps)}
    )


def _record_sitemap_urls(
    urls: tuple[str, ...],
    *,
    discovered_urls: dict[str, MapUrl],
    max_urls: int,
    root_host: str,
    include_subdomains: bool,
    source_sitemap: str,
) -> int:
    accepted_urls = 0
    for url in urls:
        if len(discovered_urls) >= max_urls:
            break
        parsed_url = urlparse(url)
        host = (parsed_url.hostname or '').lower()
        if not host or url in discovered_urls:
            continue
        discovered_urls[url] = MapUrl(
            url=url,
            host=host,
            path=parsed_url.path or '/',
            subdomain=_subdomain_for(host, root_host) if include_subdomains else None,
            source_sitemap=source_sitemap,
        )
        accepted_urls += 1
    return accepted_urls


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, '/', '', '', ''))


def _display_root_host(host: str) -> str:
    return host.removeprefix('www.')


def _parse_subfinder_subdomains(text: str, *, root_host: str, limit: int) -> tuple[str, ...]:
    found: set[str] = set()
    for line in text.splitlines():
        if len(found) >= limit:
            break
        raw = line.strip()
        if not raw or raw.startswith('['):
            continue
        host = _normalize_subdomain_host(raw)
        if host is None:
            continue
        if host != root_host and host.endswith(f'.{root_host}'):
            found.add(host)
    return tuple(sorted(found))


def _normalize_subdomain_host(value: str) -> str | None:
    host = value.strip().lower().rstrip('.')
    if not host:
        return None
    if host.startswith('*.'):
        host = host[2:]
    if '*' in host or '/' in host or ' ' in host or ':' in host:
        return None
    return host


def _queue_sitemap(
    queue: list[_QueuedSitemap],
    seen: dict[str, MapSitemap],
    raw_url: str,
    *,
    source: SitemapSource,
    max_sitemaps: int | None = None,
    insert_at: int | None = None,
) -> None:
    if max_sitemaps is not None and len(seen) >= max_sitemaps:
        return
    canonical = canonicalize_url(raw_url)
    if canonical is None or canonical in seen:
        return
    seen[canonical] = MapSitemap(url=canonical, source=source, status='skipped')
    queued = _QueuedSitemap(url=canonical, source=source)
    if insert_at is None:
        queue.append(queued)
    else:
        queue.insert(insert_at, queued)


async def _fetch_optional_text(fetcher: Any, url: str) -> str | None:
    try:
        return await _fetch_text(fetcher, url)
    except (SiteMapFetchError, SiteMapMissingError):
        return None


async def _fetch_text(fetcher: Any, url: str) -> str:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.25, max=2),
        retry=retry_if_exception_type(SiteMapFetchError),
        reraise=True,
    ):
        with attempt:
            result = await fetcher.fetch(url)
            status = _result_status(result)
            if status in {404, 410}:
                raise SiteMapMissingError(f'{url} was not found')
            if status is not None and status >= 400:
                raise SiteMapFetchError(f'{url} returned HTTP {status}')
            html = _result_text(result)
            if html is not None:
                return html
            raise SiteMapFetchError(getattr(result, 'block_reason', None) or f'{url} returned no text')
    raise SiteMapFetchError(f'{url} returned no text')


def _result_text(result: object) -> str | None:
    if isinstance(result, FetchResult):
        return result.html
    if isinstance(result, Mapping):
        value = result.get('html')
        return value if isinstance(value, str) and value else None
    value = getattr(result, 'html', None)
    return value if isinstance(value, str) and value else None


def _result_status(result: object) -> int | None:
    if isinstance(result, Mapping):
        value = result.get('status_code')
        return value if isinstance(value, int) else None
    value = getattr(result, 'status_code', None)
    return value if isinstance(value, int) else None


@dataclass(frozen=True, slots=True)
class _ParsedSitemap:
    urls: tuple[str, ...] = ()
    sitemaps: tuple[str, ...] = ()
    error: str | None = None


def _parse_sitemap(text: str, *, base_url: str) -> _ParsedSitemap:
    try:
        parser = lxml.etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
        root = lxml.etree.fromstring(text.encode('utf-8', errors='ignore'), parser=parser)
    except (lxml.etree.XMLSyntaxError, ValueError, TypeError) as exc:
        return _ParsedSitemap(error=str(exc))
    if root is None:
        return _ParsedSitemap(error='empty or invalid XML')
    root_name = _local_name(root)
    if root_name == 'sitemapindex':
        return _ParsedSitemap(sitemaps=tuple(_loc_values(root, base_url=base_url)))
    if root_name in {'urlset', 'rss', 'feed'}:
        return _ParsedSitemap(urls=tuple(_loc_values(root, base_url=base_url)))
    return _ParsedSitemap(error=f'unsupported sitemap root {root_name!r}')


def _loc_values(root: Any, *, base_url: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for element in root.xpath('//*[local-name()="loc" or local-name()="link"]'):
        raw = element.get('href') if hasattr(element, 'get') else None
        raw = raw or ''.join(element.itertext()).strip()
        canonical = canonicalize_url(urljoin(base_url, raw))
        if canonical is None or canonical in seen:
            continue
        seen.add(canonical)
        values.append(canonical)
    return values


def _local_name(element: Any) -> str:
    tag = element.tag if isinstance(element.tag, str) else ''
    return tag.rsplit('}', 1)[-1].lower()


def _subdomain_for(host: str, root_host: str) -> str | None:
    comparable = host.removeprefix('www.')
    if comparable == root_host:
        return None
    suffix = f'.{root_host}'
    if comparable.endswith(suffix):
        return comparable[: -len(suffix)]
    return None


def _host_inventory(urls: Any, *, root_host: str, include_subdomains: bool) -> list[MapHost]:
    counts: dict[str, int] = {}
    for item in urls:
        counts[item.host] = counts.get(item.host, 0) + 1
    return [
        MapHost(host=host, url_count=count, subdomain=_subdomain_for(host, root_host) if include_subdomains else None)
        for host, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
