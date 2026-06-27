"""Cache CLI target classification helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

CacheTargetKind = Literal['contract', 'domain', 'route', 'url']


@dataclass(frozen=True)
class CacheStatusTarget:
    """One syntactically routed `yosoi cache status` target."""

    kind: CacheTargetKind
    raw: str
    value: str
    domain: str | None = None
    route: str | None = None


def _clean(value: str) -> str:
    return value.strip()


def _normalized_host(host: str) -> str:
    return host.removeprefix('www.').lower()


def _looks_like_domain(value: str) -> bool:
    if any(ch.isspace() for ch in value) or '/' in value or '@' in value:
        return False
    parsed = urlparse(f'//{value}')
    host = parsed.hostname
    if not host:
        return False
    return host == 'localhost' or '.' in host


def classify_cache_status_target(raw: str) -> CacheStatusTarget:
    """Classify a positional cache status target without guessing ambiguous names."""
    value = _clean(raw)
    if not value:
        raise ValueError('Cache status target cannot be empty.')

    if value.startswith('@'):
        if value == '@':
            raise ValueError('Contract target must include an alias, e.g. @ArticleTest.')
        return CacheStatusTarget(kind='contract', raw=raw, value=value)

    parsed = urlparse(value)
    if parsed.scheme:
        if parsed.scheme not in {'http', 'https'}:
            raise ValueError(f'Unsupported URL scheme {parsed.scheme!r}; use an http(s) URL.')
        if not parsed.hostname:
            raise ValueError(f'URL target {value!r} must include a host.')
        return CacheStatusTarget(
            kind='url',
            raw=raw,
            value=value,
            domain=_normalized_host(parsed.hostname),
            route=parsed.path or '/',
        )

    if value.startswith('/'):
        if value.startswith('//'):
            raise ValueError(f'Ambiguous schemeless URL {value!r}; use --url https:{value}.')
        return CacheStatusTarget(kind='route', raw=raw, value=value, route=value)

    if _looks_like_domain(value):
        parsed = urlparse(f'//{value}')
        return CacheStatusTarget(kind='domain', raw=raw, value=value, domain=_normalized_host(parsed.hostname or value))

    raise ValueError(
        f'Ambiguous cache status target {value!r}. Use @Contract, a domain like example.com, '
        'an http(s) URL, a route beginning with /, or explicit --contract/--domain/--url/--route.'
    )


def explicit_cache_status_target(domain: str | None, url: str | None, route: str | None) -> CacheStatusTarget | None:
    """Build a target from explicit dimension flags."""
    provided = [(name, value) for name, value in (('domain', domain), ('url', url), ('route', route)) if value]
    if not provided:
        return None
    if len(provided) > 1:
        names = ', '.join(f'--{name}' for name, _ in provided)
        raise ValueError(f'Use only one explicit cache target flag at a time; got {names}.')

    name, raw_value = provided[0]
    value = _clean(raw_value)
    if name == 'domain':
        if not value or '/' in value or value.startswith('@'):
            raise ValueError(f'Invalid --domain value {raw_value!r}.')
        parsed = urlparse(f'//{value}')
        return CacheStatusTarget(
            kind='domain', raw=raw_value, value=value, domain=_normalized_host(parsed.hostname or value)
        )
    if name == 'url':
        target = classify_cache_status_target(value)
        if target.kind != 'url':
            raise ValueError(f'Invalid --url value {raw_value!r}; URLs must include http:// or https://.')
        return target
    if not value.startswith('/') or value.startswith('//'):
        raise ValueError(f'Invalid --route value {raw_value!r}; routes must begin with /.')
    return CacheStatusTarget(kind='route', raw=raw_value, value=value, route=value)
