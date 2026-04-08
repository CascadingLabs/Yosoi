"""Fetcher factory and exports."""

from yosoi.core.fetcher.base import HTMLFetcher
from yosoi.core.fetcher.simple import SimpleFetcher


def create_fetcher(fetcher_type: str = 'simple', **kwargs: object) -> HTMLFetcher:
    """Create an HTML fetcher."""
    if fetcher_type == 'simple':
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


__all__ = ['HTMLFetcher', 'SimpleFetcher', 'create_fetcher']
