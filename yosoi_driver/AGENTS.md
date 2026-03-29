# yosoi_driver — Rust CDP Browser Bindings

## What this is
A Rust workspace providing CDP (Chrome DevTools Protocol) browser automation for Yosoi, exposed to Python via PyO3. Replaces zendriver/Playwright with a permissively-licensed (MIT/Apache-2) stack.

## Architecture
```
yosoi_driver/
├── crates/
│   ├── core/              # Pure Rust async CDP wrapper (chromiumoxide)
│   │   └── src/
│   │       ├── lib.rs     # Re-exports
│   │       ├── session.rs # BrowserSession — launch/connect/close
│   │       ├── page.rs    # Page — navigate, content, JS eval, screenshot, DOM queries
│   │       ├── stealth.rs # StealthConfig — anti-detection patches
│   │       └── error.rs   # YosoiError enum
│   └── pyo3_bindings/     # PyO3 extension module (cdylib)
│       └── src/lib.rs     # PyBrowserSession + PyPage pyclass structs
├── pyproject.toml         # maturin build config
└── build.sh               # Quick build: maturin develop --release
```

## Key commands
- `cargo check` — type-check the Rust code
- `cargo test -p yosoi_driver_core -- --test-threads=1` — run Rust integration tests (serial, requires Chromium)
- `./build.sh` — build and install the Python extension into the current venv
- From the root: `uv run pytest tests/unit/core/fetcher/test_browser.py -v` — Python integration tests

## Python integration
- `yosoi.core.fetcher.browser.BrowserFetcher` implements `HTMLFetcher` using `yosoi_driver`
- Registered as `create_fetcher('browser')` — lazy import, no hard dependency
- Type stubs at `yosoi_driver.pyi`

## Dependencies (all MIT/Apache-2)
- `chromiumoxide` 0.9 — CDP client
- `tokio` — async runtime
- `pyo3` 0.28 + `pyo3-async-runtimes` 0.28 — Python bridge
- `thiserror` — error types
- `reqwest` — HTTP (for WebSocket URL resolution)
- Rust edition 2024 / MSRV 1.86
