"""Single browser session with Pydantic configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from yosoi.yd._import import require_driver

if TYPE_CHECKING:
    from yosoi_driver import BrowserSession


class SessionConfig(BaseModel, frozen=True):
    """Configuration for a single browser session.

    Maps to the ``BrowserSession`` constructor parameters.

    Example::

        from yosoi import yd

        async with yd.session(headless=False, stealth=True) as browser:
            page = await browser.new_page("https://example.com")
            html = await page.content()
    """

    headless: bool = Field(default=True)
    ws_url: str | None = Field(default=None)
    stealth: bool = Field(default=True)
    no_sandbox: bool = Field(default=False)
    proxy: str | None = Field(default=None)
    chrome_executable: str | None = Field(default=None)
    extra_args: list[str] | None = Field(default=None)


def session(config: SessionConfig | None = None, **kwargs: Any) -> BrowserSession:
    """Create a ``BrowserSession`` from Pydantic config.

    Use as an async context manager::

        from yosoi import yd

        async with yd.session(headless=False) as browser:
            page = await browser.new_page("https://example.com")
            html = await page.content()

    Args:
        config: Optional :class:`SessionConfig`.  If *None*, one is built
            from ``**kwargs``.
        **kwargs: Forwarded to :class:`SessionConfig` when *config* is not
            given.

    Returns:
        A :class:`~yosoi_driver.BrowserSession` ready for ``async with``.

    Raises:
        ImportError: If ``yosoi_driver`` is not installed.

    """
    _driver = require_driver()
    _BrowserSession: type[BrowserSession] = _driver.BrowserSession
    cfg = config or SessionConfig(**kwargs)
    return _BrowserSession(
        headless=cfg.headless,
        ws_url=cfg.ws_url,
        stealth=cfg.stealth,
        no_sandbox=cfg.no_sandbox,
        proxy=cfg.proxy,
        chrome_executable=cfg.chrome_executable,
        extra_args=cfg.extra_args,
    )
