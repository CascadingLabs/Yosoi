"""Fetcher factory and exports.

Lazy (PEP 562): ``HTMLFetcher`` / ``SimpleFetcher`` resolve on first access and
browser fetchers import only when selected, so nothing here forces voidcrawl (or
the simple-fetch stack) to load at import time. See ``CLAUDE.md`` ("Lazy loading").
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.core.fetcher.base import HTMLFetcher as HTMLFetcher
    from yosoi.core.fetcher.simple import SimpleFetcher as SimpleFetcher

_LAZY: dict[str, str] = {
    'HTMLFetcher': 'yosoi.core.fetcher.base',
    'SimpleFetcher': 'yosoi.core.fetcher.simple',
}

__all__ = ['HTMLFetcher', 'SimpleFetcher', 'create_fetcher']


def create_fetcher(fetcher_type: str = 'simple', **kwargs: Any) -> HTMLFetcher:
    """Create an HTML fetcher."""
    if fetcher_type == 'simple':
        from yosoi.core.fetcher.simple import SimpleFetcher

        return SimpleFetcher(**kwargs)

    # Browser fetchers: import lazily so voidcrawl is not required at startup
    if fetcher_type == 'waterfall':
        from yosoi.core.fetcher.waterfall import JSFetcher

        return JSFetcher(**kwargs)
    if fetcher_type == 'headless':
        from yosoi.core.fetcher.voiddriver import HeadlessFetcher

        return HeadlessFetcher(**kwargs)
    if fetcher_type == 'headful':
        from yosoi.core.fetcher.voiddriver import HeadfulFetcher

        return HeadfulFetcher(**kwargs)

    raise ValueError(f'Unknown fetcher type: {fetcher_type!r}. Choose from: simple, waterfall, headless, headful')


__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
