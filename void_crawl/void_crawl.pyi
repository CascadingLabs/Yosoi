"""Type stubs for the void_crawl native extension module."""

from __future__ import annotations

class PooledTab:
    """A tab checked out from a BrowserPool.

    Exposes the same navigation/DOM methods as Page. When used as an
    async context manager the tab is automatically returned to the pool.

    Example::

        async with await pool.acquire() as tab:
            await tab.navigate("https://example.com")
            html = await tab.content()
    """

    use_count: int

    async def goto(self, url: str, timeout: float = 30.0) -> str | None:
        """Navigate and wait for network idle in one shot.

        Faster than navigate() + wait_for_network_idle() because the event
        listener is set up before navigation starts.

        Returns the lifecycle event name or None on timeout.
        """
        ...
    async def navigate(self, url: str) -> None: ...
    async def wait_for_navigation(self) -> None: ...
    async def content(self) -> str: ...
    async def title(self) -> str | None: ...
    async def url(self) -> str | None: ...
    async def evaluate_js(self, expression: str) -> object:
        """Evaluate JS and return result as native Python object (dict/list/str/int/float/bool/None)."""
        ...
    async def screenshot_png(self) -> bytes: ...
    async def query_selector(self, selector: str) -> str | None: ...
    async def query_selector_all(self, selector: str) -> list[str]: ...
    async def click_element(self, selector: str) -> None: ...
    async def type_into(self, selector: str, text: str) -> None: ...
    async def set_headers(self, headers: dict[str, str]) -> None: ...
    async def wait_for_stable_dom(
        self,
        timeout: float = 10.0,
        min_length: int = 5000,
        stable_checks: int = 5,
    ) -> bool:
        """Wait until DOM stabilises and exceeds min_length chars.

        Returns True if stabilised within timeout, False otherwise.
        """
        ...
    async def wait_for_network_idle(self, timeout: float = 30.0) -> str | None:
        """Event-driven wait for network idle. No polling.

        Returns the lifecycle event name ("networkIdle" or "networkAlmostIdle")
        or None if the timeout was reached.
        """
        ...
    async def __aenter__(self) -> PooledTab: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: object = None,
    ) -> bool: ...

class BrowserPool:
    """Pool of reusable browser tabs across one or more Chrome sessions.

    Example::

        async with await BrowserPool.from_env() as pool:
            async with await pool.acquire() as tab:
                await tab.navigate("https://example.com")
                html = await tab.content()
    """

    @classmethod
    async def from_env(cls) -> BrowserPool: ...
    async def warmup(self) -> None: ...
    async def acquire(self) -> PooledTab: ...
    async def release(self, tab: PooledTab) -> None: ...
    async def __aenter__(self) -> BrowserPool: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: object = None,
    ) -> bool: ...

class Page:
    """A browser page / tab. All methods are async."""

    async def goto(self, url: str, timeout: float = 30.0) -> str | None:
        """Navigate and wait for network idle in one shot.

        Faster than navigate() + wait_for_network_idle() because the event
        listener is set up before navigation starts.

        Returns the lifecycle event name or None on timeout.
        """
        ...
    async def navigate(self, url: str) -> None: ...
    async def wait_for_navigation(self) -> None: ...
    async def content(self) -> str: ...
    async def title(self) -> str | None: ...
    async def url(self) -> str | None: ...
    async def evaluate_js(self, expression: str) -> object:
        """Evaluate JS and return result as native Python object (dict/list/str/int/float/bool/None)."""
        ...
    async def screenshot_png(self) -> bytes: ...
    async def pdf_bytes(self) -> bytes: ...
    async def query_selector(self, selector: str) -> str | None: ...
    async def query_selector_all(self, selector: str) -> list[str]: ...
    async def click_element(self, selector: str) -> None: ...
    async def type_into(self, selector: str, text: str) -> None: ...
    async def set_headers(self, headers: dict[str, str]) -> None: ...
    async def wait_for_stable_dom(
        self,
        timeout: float = 10.0,
        min_length: int = 5000,
        stable_checks: int = 5,
    ) -> bool:
        """Wait until DOM stabilises and exceeds min_length chars.

        Returns True if stabilised within timeout, False otherwise.
        """
        ...
    async def wait_for_network_idle(self, timeout: float = 30.0) -> str | None:
        """Event-driven wait for network idle. No polling.

        Returns the lifecycle event name ("networkIdle" or "networkAlmostIdle")
        or None if the timeout was reached.
        """
        ...
    async def close(self) -> None: ...

class BrowserSession:
    """Browser session wrapping a Chromium instance via CDP.

    Supports ``async with`` context manager protocol.

    Example::

        async with BrowserSession() as browser:
            page = await browser.new_page("https://example.com")
            html = await page.content()
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        ws_url: str | None = None,
        stealth: bool = True,
        no_sandbox: bool = False,
        proxy: str | None = None,
        chrome_executable: str | None = None,
        extra_args: list[str] | None = None,
    ) -> None: ...
    async def launch(self) -> None: ...
    async def new_page(self, url: str) -> Page: ...
    async def version(self) -> str: ...
    async def close(self) -> None: ...
    async def __aenter__(self) -> BrowserSession: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: object = None,
    ) -> bool: ...
