# yosoi_driver

**CDP browser automation for [Yosoi](https://github.com/CascadingLabs/Yosoi)** — a Rust-native Chrome DevTools Protocol client exposed to Python via PyO3.

`yosoi_driver` replaces Playwright/Selenium/Zendriver with a permissively-licensed (MIT/Apache-2.0) stack for rendering JavaScript-heavy pages during selector discovery.

## Architecture

```
yosoi_driver/
├── crates/
│   ├── core/              # Pure Rust async CDP wrapper (chromiumoxide 0.9)
│   │   └── src/
│   │       ├── session.rs # BrowserSession — launch / connect / close
│   │       ├── page.rs    # Page — navigate, content, JS eval, screenshot, DOM
│   │       ├── stealth.rs # StealthConfig — anti-detection patches
│   │       └── error.rs   # YosoiError enum
│   └── pyo3_bindings/     # PyO3 0.28 extension module (cdylib)
│       └── src/lib.rs     # BrowserSession + Page → Python classes
├── pyproject.toml         # maturin build config
├── build.sh               # Quick build: maturin develop --release
└── yosoi_driver.pyi       # Python type stubs
```

### How it works

1. **Rust core** (`yosoi_driver_core`) wraps [chromiumoxide](https://github.com/mattsse/chromiumoxide) into a clean async API: `BrowserSession` manages the browser lifecycle, `Page` wraps individual tabs with navigation, JS evaluation, screenshots, and DOM queries.

2. **PyO3 bindings** bridge Rust async → Python asyncio via [`pyo3-async-runtimes`](https://github.com/PyO3/pyo3-async-runtimes). A shared Tokio runtime handles all CDP I/O; `future_into_py` converts each Rust future into a Python awaitable.

3. **Python integration** — `yosoi.core.fetcher.browser.BrowserFetcher` implements yosoi's `HTMLFetcher` ABC, registered as `create_fetcher('browser')`. It lazy-imports `yosoi_driver` so the main package works without the native extension.

### Anti-detection (Stealth)

`StealthConfig` applies multiple layers to avoid bot detection:

| Layer | What it does |
|---|---|
| chromiumoxide `enable_stealth_mode()` | Patches `navigator.webdriver`, `navigator.plugins`, Chrome runtime checks |
| `Page.addScriptToEvaluateOnNewDocument` | Custom JS injection before every page load |
| `Emulation.setUserAgentOverride` | Realistic UA + platform + Accept-Language |
| `Emulation.setDeviceMetricsOverride` | 1920×1080 viewport, device scale factor 1.0 |
| `Page.setBypassCSP` | Allows injected JS to run despite CSP |
| Chrome flags | `--disable-blink-features=AutomationControlled`, `--disable-infobars` |

Use `StealthConfig::chrome_like()` (default) for a realistic Chrome fingerprint, or `StealthConfig::none()` for raw headless.

## Requirements

- **Rust** ≥ 1.86 (edition 2024)
- **Python** ≥ 3.10
- **Chrome/Chromium** installed on the system
- **maturin** ≥ 1.7 (`cargo install maturin`)

## Quick start

```bash
# Build and install into your venv
cd yosoi_driver
./build.sh

# Or manually:
maturin develop --release --manifest-path crates/pyo3_bindings/Cargo.toml
```

### Python usage

```python
import asyncio
from yosoi_driver import BrowserSession

async def main():
    async with BrowserSession(headless=True) as browser:
        page = await browser.new_page("https://example.com")
        html = await page.content()
        print(html)
        title = await page.title()
        print(f"Title: {title}")
        await page.close()

asyncio.run(main())
```

### Via yosoi's fetcher interface

```python
from yosoi.core.fetcher import create_fetcher

async def scrape():
    fetcher = create_fetcher("browser", no_sandbox=True)
    async with fetcher:
        result = await fetcher.fetch("https://example.com")
        print(result.html)
```

### Rust usage

```rust
use yosoi_driver_core::BrowserSession;

#[tokio::main]
async fn main() -> yosoi_driver_core::Result<()> {
    let session = BrowserSession::builder()
        .headless()
        .no_sandbox()
        .launch()
        .await?;

    let page = session.new_page("https://example.com").await?;
    let html = page.content().await?;
    println!("{}", html);

    page.close().await?;
    session.close().await?;
    Ok(())
}
```

## API Reference

### `BrowserSession` (Python)

```python
BrowserSession(
    *,
    headless: bool = True,       # Headless or visible browser
    ws_url: str | None = None,   # Connect to existing Chrome (ws:// or http://)
    stealth: bool = True,        # Enable anti-detection
    no_sandbox: bool = False,    # Disable Chrome sandbox (containers/CI)
    proxy: str | None = None,    # Proxy URL (e.g. "http://proxy:8080")
    chrome_executable: str | None = None,  # Custom Chrome binary path
    extra_args: list[str] | None = None,   # Additional Chrome flags
)
```

**Methods** (all async):
- `launch()` — Launch browser (called automatically by `async with`)
- `new_page(url: str) -> Page` — Open a new tab and navigate
- `version() -> str` — Browser version string
- `close()` — Shut down the browser

### `Page` (Python)

**Methods** (all async):
- `navigate(url: str)` — Navigate to a new URL
- `wait_for_navigation()` — Wait for current navigation to complete
- `content() -> str` — Full page HTML
- `title() -> str | None` — Page title
- `url() -> str | None` — Current URL
- `evaluate_js(expression: str) -> str` — Evaluate JS, returns JSON string
- `screenshot_png() -> bytes` — Full-page PNG screenshot
- `pdf_bytes() -> bytes` — PDF of the page
- `query_selector(selector: str) -> str | None` — Inner HTML of first match
- `query_selector_all(selector: str) -> list[str]` — Inner HTML of all matches
- `click_element(selector: str)` — Click first matching element
- `type_into(selector: str, text: str)` — Type text into first matching element
- `set_headers(headers: dict[str, str])` — Set extra HTTP headers
- `close()` — Close this tab

### `BrowserSession` (Rust)

```rust
// Builder pattern
BrowserSession::builder()
    .headless()              // or .headful() or .remote_debug("ws://...")
    .no_sandbox()
    .stealth(StealthConfig::chrome_like())
    .proxy("http://proxy:8080")
    .chrome_executable("/usr/bin/chromium")
    .arg("--disable-gpu")
    .launch()
    .await?;

// Convenience constructors
BrowserSession::launch_headless().await?;
BrowserSession::launch_headful().await?;
BrowserSession::connect("ws://localhost:9222").await?;
```

## Testing

```bash
# Rust integration tests (must run serially due to Chrome singleton lock)
cargo test -p yosoi_driver_core -- --test-threads=1

# Python integration tests (from repo root)
uv run pytest tests/unit/core/fetcher/test_browser.py -v

# Full yosoi test suite (verify no regressions)
uv run poe ci-check
```

## Dependencies

All dependencies are MIT or Apache-2.0 licensed — no AGPL exposure.

| Crate | Version | Purpose |
|---|---|---|
| `chromiumoxide` | 0.9 | CDP client, browser management |
| `tokio` | 1.x | Async runtime |
| `pyo3` | 0.28 | Rust ↔ Python bindings |
| `pyo3-async-runtimes` | 0.28 | Tokio ↔ asyncio bridge |
| `thiserror` | 2.x | Error derive macros |
| `serde` / `serde_json` | 1.x | Serialization |
| `reqwest` | 0.12 | HTTP (WebSocket URL resolution) |
| `futures` | 0.3 | Stream utilities (Handler loop) |

## License

Apache-2.0
