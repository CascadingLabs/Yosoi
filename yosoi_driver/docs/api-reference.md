# API Reference

All classes are importable from `yosoi_driver`.

```python
from yosoi_driver import BrowserSession, Page
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
| `await navigate(url)` | `None` | Navigate to a new URL in this tab. |
| `await wait_for_navigation()` | `None` | Block until the current navigation completes. |

### Content

| Method | Returns | Description |
|--------|---------|-------------|
| `await content()` | `str` | Full page HTML (equivalent to `document.documentElement.outerHTML`). |
| `await title()` | `str \| None` | The document title, or `None`. |
| `await url()` | `str \| None` | The current URL, or `None`. |

### JavaScript

| Method | Returns | Description |
|--------|---------|-------------|
| `await evaluate_js(expression)` | `str` | Evaluate a JS expression and return the result as a **JSON string**. Parse it with `json.loads()`. |

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
