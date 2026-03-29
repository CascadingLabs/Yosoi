"""Single-page and multi-page shortcuts with automatic session management."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from yosoi.yd.session import SessionConfig, session

if TYPE_CHECKING:
    from yosoi_driver import Page


@asynccontextmanager
async def page(url: str, *, config: SessionConfig | None = None, **kwargs: Any) -> AsyncIterator[Page]:
    """Open a single page, managing the browser session automatically.

    Example::

        from yosoi import yd

        async with yd.page('https://example.com') as pg:
            html = await pg.content()

    Args:
        url: URL to navigate to.
        config: Optional :class:`SessionConfig`.
        **kwargs: Forwarded to :class:`SessionConfig` when *config* is not given.

    Yields:
        A :class:`~yosoi_driver.Page` that is closed on exit.

    """
    async with session(config=config, **kwargs) as browser:
        pg = await browser.new_page(url)
        try:
            yield pg
        finally:
            await pg.close()


@asynccontextmanager
async def pages(*urls: str, config: SessionConfig | None = None, **kwargs: Any) -> AsyncIterator[tuple[Page, ...]]:
    """Open multiple pages in a single shared session.

    Pages are opened concurrently via :func:`asyncio.gather`.

    Example::

        from yosoi import yd

        async with yd.pages('https://a.com', 'https://b.com') as (p1, p2):
            print(await p1.title(), await p2.title())

    Args:
        *urls: One or more URLs to open.
        config: Optional :class:`SessionConfig`.
        **kwargs: Forwarded to :class:`SessionConfig` when *config* is not given.

    Yields:
        A tuple of :class:`~yosoi_driver.Page` objects, closed on exit.

    """
    if not urls:
        raise ValueError('pages() requires at least one URL')
    async with session(config=config, **kwargs) as browser:
        opened = list(await asyncio.gather(*(browser.new_page(u) for u in urls)))
        try:
            yield tuple(opened)
        finally:
            await asyncio.gather(*(pg.close() for pg in opened), return_exceptions=True)
