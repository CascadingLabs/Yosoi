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
│  BrowserSession, Page, Stealth      │
├─────────────────────────────────────┤
│  chromiumoxide 0.9                  │
│  Chrome DevTools Protocol client    │
├─────────────────────────────────────┤
│  Chrome / Chromium (subprocess)     │
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
│   │       ├── stealth.rs     # StealthConfig + JS payloads
│   │       └── error.rs       # YosoiError enum
│   └── pyo3_bindings/         # cdylib that Python imports
│       └── src/
│           └── lib.rs         # PyBrowserSession, PyPage, module init
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
