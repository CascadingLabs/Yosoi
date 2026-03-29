"""Browser tab pool with Pydantic configuration."""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from yosoi_driver import BrowserPool


class PoolConfig(BaseModel, frozen=True):
    """Configuration for a browser tab pool.

    Maps to the Rust ``PoolConfig`` and the environment variables read by
    ``BrowserPool.from_env()``.

    Example::

        from yosoi import yd

        cfg = yd.PoolConfig(browsers=2, tabs_per_browser=8)
        async with await yd.pool(cfg) as p:
            async with await p.acquire() as tab:
                await tab.navigate("https://example.com")
    """

    browsers: int = Field(default=1, ge=1)
    tabs_per_browser: int = Field(default=4, ge=1)
    tab_max_uses: int = Field(default=50, ge=1)
    tab_max_idle_secs: int = Field(default=60, ge=0)
    headless: bool = True
    no_sandbox: bool = False
    ws_urls: list[str] | None = None

    @contextmanager
    def _apply_env(self) -> Generator[None, None, None]:
        """Temporarily set environment variables from this config."""
        overrides: dict[str, str] = {
            'BROWSER_COUNT': str(self.browsers),
            'TABS_PER_BROWSER': str(self.tabs_per_browser),
            'TAB_MAX_USES': str(self.tab_max_uses),
            'TAB_MAX_IDLE_SECS': str(self.tab_max_idle_secs),
        }
        if not self.headless:
            overrides['CHROME_HEADLESS'] = '0'
        if self.no_sandbox:
            overrides['CHROME_NO_SANDBOX'] = '1'
        if self.ws_urls:
            overrides['CHROME_WS_URLS'] = ','.join(self.ws_urls)

        saved = {k: os.environ.get(k) for k in overrides}
        try:
            os.environ.update(overrides)
            yield
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


async def pool(config: PoolConfig | None = None, **kwargs: Any) -> BrowserPool:
    """Create a ``BrowserPool`` from Pydantic config.

    Use as an async context manager::

        from yosoi import yd

        async with await yd.pool(browsers=2) as p:
            async with await p.acquire() as tab:
                await tab.navigate("https://example.com")
                html = await tab.content()

    Args:
        config: Optional :class:`PoolConfig`. If *None*, one is built from
            ``**kwargs``.  When both are omitted the defaults (or env vars)
            are used.
        **kwargs: Forwarded to :class:`PoolConfig` when *config* is not given.

    Returns:
        A :class:`~yosoi_driver.BrowserPool` ready for ``async with``.

    Raises:
        ImportError: If ``yosoi_driver`` is not installed.

    """
    try:
        from yosoi_driver import BrowserPool as _BrowserPool
    except ImportError:
        raise ImportError('yosoi_driver is not installed. Build it with: cd yosoi_driver && ./build.sh') from None

    cfg = config or PoolConfig(**kwargs)
    with cfg._apply_env():
        return await _BrowserPool.from_env()
