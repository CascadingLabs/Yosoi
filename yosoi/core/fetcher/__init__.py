"""Fetcher factory and exports."""

from yosoi.core.fetcher.base import HTMLFetcher
from yosoi.core.fetcher.simple import SimpleFetcher


def create_fetcher(fetcher_type: str = 'simple', **kwargs: object) -> HTMLFetcher:
    """Create an HTML fetcher.

    Args:
        fetcher_type: Type of fetcher ('simple')
        **kwargs: Additional arguments for the fetcher

    Returns:
        HTMLFetcher instance

    """
    fetchers: dict[str, type[HTMLFetcher]] = {
        'simple': SimpleFetcher,
    }

    if fetcher_type not in fetchers:
        raise ValueError(f'Unknown fetcher type: {fetcher_type}. Choose from: {list(fetchers.keys())}')

    return fetchers[fetcher_type](**kwargs)


__all__ = ['HTMLFetcher', 'SimpleFetcher', 'create_fetcher']
