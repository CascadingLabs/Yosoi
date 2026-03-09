"""Url type for Yosoi contracts."""

from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from yosoi.types.registry import register_coercion

_TRACKING_PREFIXES = ('utm_', 'fbclid', 'gclid', '_gl', 'ref')


@register_coercion('url', description='A URL or href', require_https=True, strip_tracking=True)
def Url(v: object, config: dict[str, Any], source_url: str | None = None) -> str:
    """Configure a URL field with optional HTTPS upgrade and tracking removal.

    Example::

        class Shop(Contract):
            url: str = ys.Url(strip_tracking=True)
    """
    require_https: bool = config.get('require_https', True)
    strip_tracking: bool = config.get('strip_tracking', True)

    raw = str(v).strip()

    if raw.lower().startswith('javascript:'):
        raise ValueError(f'Extracted javascript execution link instead of valid URL: {raw!r}')

    if source_url and raw.startswith('/'):
        raw = urljoin(source_url, raw)

    if raw.startswith('//'):
        raw = f'https:{raw}'
    elif require_https and raw.startswith('http://'):
        raw = 'https://' + raw[7:]

    if strip_tracking and '?' in raw:
        parsed = urlparse(raw)
        clean_params = [
            p for p in parsed.query.split('&') if p and not any(p.startswith(t) for t in _TRACKING_PREFIXES)
        ]
        raw = urlunparse(parsed._replace(query='&'.join(clean_params))).rstrip('?')

    return raw
