# API Reference

All classes are importable from `void_crawl`.

```python
from void_crawl import BrowserPool, PooledTab, BrowserSession, Page
```

---

## `BrowserPool`

Pool of reusable browser tabs spread across one or more Chrome sessions. Provides near-instant tab reuse by recycling tabs instead of closing and reopening them. No CDP call on release — the next caller's `navigate()` overwrites prior state.

### Factory

```python
pool = await BrowserPool.from_env()
```

Reads configuration from environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CHROME_WS_URLS` | — | Comma-separated URLs for connect mode. |
| `BROWSER_COUNT` | `1` | Chrome processes to launch. |
| `TABS_PER_BROWSER` | `4` | Tabs pre-opened per browser. |
| `TAB_MAX_USES` | `50` | Hard-recycle threshold. |
| `TAB_MAX_IDLE_SECS` | `60` | Idle eviction timeout. |
| `CHROME_NO_SANDBOX` | — | Set `"1"` to disable sandbox. |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `await from_env()` | `BrowserPool` | Class method. Create pool from env vars. |
| `await warmup()` | `None` | Pre-open tabs. Called automatically by `__aenter__`. |
| `await acquire()` | `PooledTab` | Check out a tab. Blocks if all tabs are busy. |
| `await release(tab)` | `None` | Return a tab to the pool. |

### Context Manager

```python
async with await BrowserPool.from_env() as pool:
    async with await pool.acquire() as tab:
        await tab.navigate("https://example.com")
        html = await tab.content()
    # tab auto-released here
# pool closed here
```

---

## `PooledTab`

A tab checked out from a `BrowserPool`. Exposes the same methods as `Page` (navigate, content, title, etc.) but must not be closed manually — return it to the pool via `release()` or the async context manager.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `use_count` | `int` | How many times this tab has been used (0 on first acquire). |

### Methods

Same as [`Page`](#page) except no `close()` — closing is handled by the pool:

| Method | Returns | Description |
|--------|---------|-------------|
| `await goto(url, timeout=30.0)` | `str \| None` | Navigate + wait for network idle in one shot. Returns `"networkIdle"`, `"networkAlmostIdle"`, or `None`. |
| `await navigate(url)` | `None` | Navigate to a URL (no waiting). |
| `await wait_for_network_idle(timeout)` | `str \| None` | Wait for network idle. |
| `await content()` | `str` | Full page HTML. |
| `await title()` | `str \| None` | Document title. |
| `await url()` | `str \| None` | Current URL. |
| `await evaluate_js(expr)` | `object` | Evaluate JS, return native Python type (dict/list/str/int/float/bool/None). |
| `await screenshot_png()` | `bytes` | Full-page PNG screenshot. |
| `await pdf_bytes()` | `bytes` | PDF of the page. |
| `await query_selector(sel)` | `str \| None` | Inner HTML of first match. |
| `await query_selector_all(sel)` | `list[str]` | Inner HTML of all matches. |
| `await click_element(sel)` | `None` | Click first matching element. |
| `await type_into(sel, text)` | `None` | Type into first matching element. |
| `await set_headers(headers)` | `None` | Set extra HTTP headers. |

### Context Manager

```python
async with await pool.acquire() as tab:
    ...  # tab auto-released on exit
```

---

## `BrowserSession`

Manages the Chrome/Chromium process lifecycle.

### Constructor

```python
BrowserSession(
    *,
    headless: bool = True,
    ws_url: str | None = None,
    stealth: bool = True,
    no_sandbox: bool = False,
    proxy: str | None = None,
    chrome_executable: str | None = None,
    extra_args: list[str] | None = None,
)
```

| Parameter | Description |
|-----------|-------------|
| `headless` | Run Chrome without a visible window. Default `True`. |
| `ws_url` | Connect to an existing Chrome instance instead of launching a new one. Accepts an `http://` endpoint (auto-resolved to `ws://`) or a direct `ws://` URL. |
| `stealth` | Apply anti-detection patches on every new page. Default `True`. |
| `no_sandbox` | Pass `--no-sandbox` to Chrome. Required in Docker / rootless containers. |
| `proxy` | Proxy server URL (e.g. `http://host:port` or `socks5://host:port`). |
| `chrome_executable` | Path to a specific Chrome binary. If omitted, `chromiumoxide` auto-detects. |
| `extra_args` | Additional CLI flags passed to Chrome. |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `await launch()` | `None` | Start the browser process (or connect to `ws_url`). Called automatically when used as a context manager. |
| `await new_page(url)` | `Page` | Open a new tab and navigate to `url`. Stealth patches are applied before navigation. |
| `await version()` | `str` | Chrome version string (e.g. `"Google Chrome/126.0.6478.126"`). |
| `await close()` | `None` | Shut down the browser process and clean up resources. |

### Context Manager

```python
async with BrowserSession() as session:
    ...  # session.launch() called on enter, session.close() on exit
```

---

## `Page`

Represents a single browser tab. Created via `BrowserSession.new_page()`.

### Navigation

| Method | Returns | Description |
|--------|---------|-------------|
| `await goto(url, timeout=30.0)` | `str \| None` | Navigate + wait for network idle in one shot. Returns `"networkIdle"`, `"networkAlmostIdle"`, or `None` on timeout. |
| `await navigate(url)` | `None` | Navigate to a new URL (no waiting). |
| `await wait_for_navigation()` | `None` | Block until the current navigation completes. |
| `await wait_for_network_idle(timeout)` | `str \| None` | Event-driven wait for network idle. |

### Content

| Method | Returns | Description |
|--------|---------|-------------|
| `await content()` | `str` | Full page HTML (equivalent to `document.documentElement.outerHTML`). |
| `await title()` | `str \| None` | The document title, or `None`. |
| `await url()` | `str \| None` | The current URL, or `None`. |

### JavaScript

| Method | Returns | Description |
|--------|---------|-------------|
| `await evaluate_js(expression)` | `object` | Evaluate a JS expression and return the result as a **native Python type** (dict, list, str, int, float, bool, or None). |

### Media Capture

| Method | Returns | Description |
|--------|---------|-------------|
| `await screenshot_png()` | `bytes` | Full-page screenshot as PNG bytes. |
| `await pdf_bytes()` | `bytes` | PDF rendering of the page (headless mode only). |

### DOM Queries

| Method | Returns | Description |
|--------|---------|-------------|
| `await query_selector(selector)` | `str \| None` | Outer HTML of the first matching element, or `None`. |
| `await query_selector_all(selector)` | `list[str]` | Outer HTML of every matching element. |

### Interaction

| Method | Returns | Description |
|--------|---------|-------------|
| `await click_element(selector)` | `None` | Click the first element matching `selector`. |
| `await type_into(selector, text)` | `None` | Focus the element matching `selector` and type `text`. |

### Network

| Method | Returns | Description |
|--------|---------|-------------|
| `await set_headers(headers)` | `None` | Set extra HTTP headers (`dict[str, str]`) for all subsequent requests from this page. |

### Cleanup

| Method | Returns | Description |
|--------|---------|-------------|
| `await close()` | `None` | Close this tab. |

---

## Error Handling

All errors surface as `RuntimeError` on the Python side. The error message includes the specific failure category from the Rust core:

| Rust Variant | When |
|-------------|------|
| `LaunchFailed` | Chrome binary not found or failed to start. |
| `ConnectionFailed` | Could not connect to the DevTools WebSocket. |
| `NavigationFailed` | A `navigate()` or `new_page()` call timed out or errored. |
| `PageError` | Generic page-level CDP error. |
| `JsEvalError` | JavaScript evaluation threw an exception. |
| `ScreenshotError` | Screenshot capture failed. |
| `PdfError` | PDF generation failed. |
| `ElementNotFound` | `click_element` / `type_into` selector matched nothing. |
| `Timeout` | Operation exceeded its deadline. |
| `BrowserClosed` | Attempted an operation after the browser was shut down. |

```python
try:
    await page.click_element("#nonexistent")
except RuntimeError as e:
    print(e)  # "ElementNotFound: ..."
```
