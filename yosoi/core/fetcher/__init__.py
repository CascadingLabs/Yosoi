"""Fetcher factory and exports."""

from yosoi.core.fetcher.base import HTMLFetcher
from yosoi.core.fetcher.simple import SimpleFetcher


def create_fetcher(fetcher_type: str = 'simple', **kwargs: object) -> HTMLFetcher:
    """Create an HTML fetcher.

    Args:
        fetcher_type: Type of fetcher ('simple' or 'browser')
        **kwargs: Additional arguments for the fetcher

    Returns:
        HTMLFetcher instance

    Raises:
        ValueError: If fetcher_type is unknown.
        ImportError: If 'browser' is requested but void_crawl is not installed.

    """
    fetchers: dict[str, type[HTMLFetcher]] = {
        'simple': SimpleFetcher,
    }

    # Lazy-import BrowserFetcher so yosoi works without the native extension
    if fetcher_type == 'browser':
        from yosoi.core.fetcher.browser import BrowserFetcher

        return BrowserFetcher(**kwargs)  # type: ignore[arg-type]

    if fetcher_type not in fetchers:
        raise ValueError(f'Unknown fetcher type: {fetcher_type}. Choose from: {[*fetchers, "browser"]}')

    return fetchers[fetcher_type](**kwargs)


__all__ = ['HTMLFetcher', 'SimpleFetcher', 'create_fetcher']
