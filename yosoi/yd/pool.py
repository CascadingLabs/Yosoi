"""Browser tab pool with Pydantic configuration and performance modes."""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from yosoi_driver import BrowserPool


class Viewport(BaseModel, frozen=True):
    """Viewport dimensions for the browser's device metrics override.

    Common safe presets (won't trigger WAF bot detection)::

        Viewport(width=1920, height=1080)   # Full HD (default)
        Viewport(width=1366, height=768)    # Common laptop
        Viewport(width=1440, height=900)    # MacBook-like
        Viewport(width=1280, height=720)    # HD / embedded
    """

    width: int = Field(default=1920, ge=320)
    height: int = Field(default=1080, ge=240)


class PerformanceMode(str, Enum):
    """Performance presets controlling resource usage vs throughput.

    - ``full``: Maximum throughput. Multiple browsers, many tabs, full HD.
      Best for dedicated scraping servers.
    - ``balanced``: Moderate resources. Single browser, fewer tabs,
      laptop-sized viewport. Good for desktop machines running other work.
    - ``lite``: Minimal footprint. Single browser, single tab, 720p viewport.
      Designed for CI, embedded, or memory-constrained environments.
    """

    full = 'full'
    balanced = 'balanced'
    lite = 'lite'


# ── Preset defaults per mode ─────────────────────────────────────────────

_MODE_DEFAULTS: dict[PerformanceMode, dict[str, Any]] = {
    PerformanceMode.full: {
        'browsers': 2,
        'tabs_per_browser': 8,
        'viewport': Viewport(width=1920, height=1080),
    },
    PerformanceMode.balanced: {
        'browsers': 1,
        'tabs_per_browser': 4,
        'viewport': Viewport(width=1366, height=768),
    },
    PerformanceMode.lite: {
        'browsers': 1,
        'tabs_per_browser': 1,
        'viewport': Viewport(width=1280, height=720),
    },
}


class PoolConfig(BaseModel, frozen=True):
    """Configuration for a browser tab pool.

    Maps to the Rust ``PoolConfig`` and the environment variables read by
    ``BrowserPool.from_env()``.

    Use :class:`PerformanceMode` for quick presets, or override individual
    fields for full control::

        from yosoi import yd

        # Quick: performance mode preset
        async with await yd.pool(mode='balanced') as p:
            ...

        # Fine-grained control
        async with await yd.pool(
            mode='lite',
            tabs_per_browser=2,                       # override lite's default of 1
            viewport=yd.Viewport(width=1024, height=768),  # custom viewport
        ) as p:
            ...
    """

    mode: PerformanceMode = Field(default=PerformanceMode.balanced)
    browsers: int | None = Field(default=None, ge=1)
    tabs_per_browser: int | None = Field(default=None, ge=1)
    tab_max_uses: int = Field(default=50, ge=1)
    tab_max_idle_secs: int = Field(default=60, ge=0)
    viewport: Viewport | None = None
    headless: bool = True
    no_sandbox: bool = False
    ws_urls: list[str] | None = None

    @property
    def effective_browsers(self) -> int:
        """Resolved browser count: explicit value or mode default."""
        if self.browsers is not None:
            return self.browsers
        return int(_MODE_DEFAULTS[self.mode]['browsers'])

    @property
    def effective_tabs_per_browser(self) -> int:
        """Resolved tabs per browser: explicit value or mode default."""
        if self.tabs_per_browser is not None:
            return self.tabs_per_browser
        return int(_MODE_DEFAULTS[self.mode]['tabs_per_browser'])

    @property
    def effective_viewport(self) -> Viewport:
        """Resolved viewport: explicit value or mode default."""
        if self.viewport is not None:
            return self.viewport
        vp: Viewport = _MODE_DEFAULTS[self.mode]['viewport']
        return vp

    @contextmanager
    def _apply_env(self) -> Generator[None, None, None]:
        """Temporarily set environment variables from this config."""
        vp = self.effective_viewport
        overrides: dict[str, str] = {
            'BROWSER_COUNT': str(self.effective_browsers),
            'TABS_PER_BROWSER': str(self.effective_tabs_per_browser),
            'TAB_MAX_USES': str(self.tab_max_uses),
            'TAB_MAX_IDLE_SECS': str(self.tab_max_idle_secs),
            'VIEWPORT_WIDTH': str(vp.width),
            'VIEWPORT_HEIGHT': str(vp.height),
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

        # Performance mode presets
        async with await yd.pool(mode='full') as p:       # server
            ...
        async with await yd.pool(mode='balanced') as p:    # desktop
            ...
        async with await yd.pool(mode='lite') as p:        # embedded/CI
            ...

        # Fine-grained
        async with await yd.pool(
            mode='full',
            viewport=yd.Viewport(width=1440, height=900),
        ) as p:
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
