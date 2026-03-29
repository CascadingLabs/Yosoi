# Architecture

## Layer Diagram

```
┌─────────────────────────────────────┐
│  Python (asyncio)                   │
│  from yosoi_driver import ...       │
├─────────────────────────────────────┤
│  PyO3 Bindings  (crates/pyo3_bindings) │
│  Bridges Rust futures ↔ Python      │
│  coroutines via pyo3-async-runtimes │
├─────────────────────────────────────┤
│  Rust Core      (crates/core)       │
│  BrowserPool, BrowserSession, Page  │
├─────────────────────────────────────┤
│  chromiumoxide 0.9                  │
│  Chrome DevTools Protocol client    │
├─────────────────────────────────────┤
│  Chrome / Chromium (long-lived)     │
└─────────────────────────────────────┘
```

## Crate Layout

```
yosoi_driver/
├── crates/
│   ├── core/                  # Pure Rust library — no Python dependency
│   │   └── src/
│   │       ├── lib.rs         # Module re-exports
│   │       ├── session.rs     # BrowserSession + builder
│   │       ├── page.rs        # Page operations + stealth application
│   │       ├── pool.rs        # BrowserPool — tab reuse + semaphore
│   │       ├── stealth.rs     # StealthConfig + JS payloads
│   │       └── error.rs       # YosoiError enum
│   └── pyo3_bindings/         # cdylib that Python imports
│       └── src/
│           └── lib.rs         # PyBrowserSession, PyPage, PyBrowserPool, module init
├── yosoi_driver.pyi           # Type stubs for IDE support
├── pyproject.toml             # maturin build config
└── Cargo.toml                 # Workspace root
```

## Core Design Decisions

### Async Bridge

The Rust core runs on **tokio**. The PyO3 bindings use [`pyo3-async-runtimes`](https://docs.rs/pyo3-async-runtimes) to convert Rust futures into Python coroutines. This means:

- Every Python method that calls into Rust is `async`.
- A tokio runtime is spun up automatically when the first coroutine enters Rust.
- Python's `asyncio.run()` drives the event loop; tokio runs underneath.

### Resource Lifecycle

Both `PyBrowserSession` and `PyPage` wrap their inner Rust objects in `Arc<Mutex<Option<T>>>`:

```
Arc  — shared ownership across Python GC + Rust tasks
  └─ Mutex  — safe concurrent access
       └─ Option<T>  — None after close(), enabling clean shutdown
```

Calling `close()` takes the inner value out of the `Option`, dropping the Rust object. Subsequent calls to any method on a closed session/page return a clear `RuntimeError("browser is closed")`.

### Stealth Application

Stealth patches are applied in `Page::apply_stealth()`, which runs **after** the CDP tab is created but **before** any user navigation:

1. `chromiumoxide::enable_stealth_mode()` (low-level CDP patches)
2. CSP bypass via `Page.setBypassCSP`
3. User-agent override via `Network.setUserAgentOverride`
4. JavaScript injection via `Page.addScriptToEvaluateOnNewDocument`

This ordering ensures the JS payload executes before any page script can observe the unpatched state.

### Error Mapping

The Rust `YosoiError` enum covers every failure mode. The PyO3 layer converts each variant to a Python `RuntimeError` with a descriptive prefix (e.g. `"NavigationFailed: timeout after 30s"`). This keeps the Python error surface simple — catch `RuntimeError` — while preserving diagnostic detail.

## Browser Pool

The `BrowserPool` provides near-instant tab reuse by keeping Chrome processes alive as long-lived daemons and recycling tabs instead of closing them.

### Design

```
┌───────────────────────────────────────────┐
│  BrowserPool                              │
│  ┌─────────┐  ┌─────────┐                │
│  │Session 0│  │Session 1│  ...            │
│  │ (9222)  │  │ (9223)  │                 │
│  └────┬────┘  └────┬────┘                │
│       │             │                     │
│  ┌────┴─────────────┴────┐                │
│  │   Ready Queue (deque) │                │
│  │  [Tab0, Tab1, Tab2..] │                │
│  └───────────────────────┘                │
│  Semaphore(permits = total tabs)          │
└───────────────────────────────────────────┘
```

### Lifecycle

1. **Warmup**: Pre-open `tabs_per_browser × browsers` blank tabs, push to the ready queue. Semaphore permits are consumed and re-added one-by-one so partial failures leave the semaphore consistent.
2. **Acquire**: Decrement semaphore (blocks if all tabs busy), pop a tab from the queue. If `use_count ≥ tab_max_uses`, hard-recycle (close + reopen).
3. **Release**: Increment `use_count`, push back to the queue, release semaphore permit. No CDP call — the next `acquire()` caller's `navigate(url)` overwrites prior page content, and stealth scripts persist across navigations.
4. **Eviction** (background): Tabs idle longer than `tab_max_idle_secs` are closed and replaced with fresh ones.

### Configuration (environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `CHROME_WS_URLS` | — | Comma-separated `ws://` or `http://` URLs. If set, connect mode (skip launching). |
| `BROWSER_COUNT` | `1` | Number of Chrome processes to launch. |
| `TABS_PER_BROWSER` | `4` | Idle tabs pre-opened per browser. |
| `TAB_MAX_USES` | `50` | Hard-recycle a tab after this many uses. |
| `TAB_MAX_IDLE_SECS` | `60` | Evict idle tabs after this many seconds. |
| `CHROME_NO_SANDBOX` | — | Set to `"1"` to pass `--no-sandbox`. |

### Docker Integration

In production, Chrome runs as a persistent daemon managed by `supervisord`:

```
supervisord
├── chrome-debug-1 (port 9222, --user-data-dir=/tmp/chrome-profile-1)
└── chrome-debug-2 (port 9223, --user-data-dir=/tmp/chrome-profile-2)
```

The pool connects via `CHROME_WS_URLS=http://localhost:9222,http://localhost:9223` instead of launching Chrome itself. Separate user-data-dirs prevent `SingletonLock` conflicts.

## Build Pipeline

```
maturin develop --release
    │
    ├─ Compiles crates/core (pure Rust)
    ├─ Compiles crates/pyo3_bindings (cdylib → yosoi_driver.so)
    └─ Installs the .so into the active virtualenv
```

`build.sh` wraps this into a single command. For CI, `maturin build --release` produces a wheel.

## Testing

**Rust integration tests** (`crates/core/tests/integration.rs`):
- Launch a real headless Chrome and exercise every API method.
- Must run with `--test-threads=1` since they share a browser process.

**Python integration tests** (in the parent Yosoi repo):
- Test `BrowserSession` and `Page` from Python via `pytest` + `pytest-asyncio`.
- Validate the full stack: Python → PyO3 → Rust → Chrome.
