# Contributing to void_crawl

Thanks for contributing! This guide covers the development workflow for the Rust/PyO3 browser automation layer.

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Rust | ≥ 1.86 | [rustup.rs](https://rustup.rs) |
| Python | ≥ 3.10 | System or [mise](https://mise.jdx.dev) |
| Chrome/Chromium | Any recent | System package manager |
| maturin | ≥ 1.7 | `cargo install maturin` |
| uv | Latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

## Project layout

```
void_crawl/
├── crates/
│   ├── core/              # void_crawl_core — pure Rust CDP wrapper
│   │   ├── src/           # Library source
│   │   └── tests/         # Integration tests (require Chrome)
│   └── pyo3_bindings/     # void_crawl — PyO3 extension module
│       └── src/lib.rs     # Python class definitions
├── Cargo.toml             # Workspace root
├── pyproject.toml         # maturin build config
├── build.sh               # Build helper
└── void_crawl.pyi       # Python type stubs
```

## Development workflow

### 1. Build the extension

```bash
cd void_crawl
./build.sh
```

This runs `maturin develop --release` which compiles the Rust code and installs the Python extension into the active venv.

### 2. Run Rust tests

```bash
cargo test -p void_crawl_core -- --test-threads=1
```

Tests **must** run serially (`--test-threads=1`) because each test launches a Chromium process that uses a shared profile directory. Parallel launches cause `SingletonLock` conflicts.

### 3. Run Python tests

From the repository root:

```bash
uv run pytest tests/unit/core/fetcher/test_browser.py -v
```

### 4. Type check and lint

```bash
# Rust
cargo check --workspace
cargo clippy --workspace

# Python (from repo root)
uv run ruff check yosoi/core/fetcher/browser.py
uv run mypy yosoi/core/fetcher/browser.py
```

### 5. Full CI check

From the repo root:

```bash
uv run poe ci-check
```

## Code style

### Rust

- Follow standard Rust conventions (`rustfmt` defaults)
- Use `thiserror` for error types — every new error variant goes in `error.rs`
- Map chromiumoxide errors to `YosoiError` at the boundary, not deep inside methods
- Builders use the owned-self pattern: `.method(self) -> Self`

### Python

- Follow the project's `ruff` config (see root `pyproject.toml`)
- Single quotes, 120 char line length
- Google-style docstrings
- Never use `unittest` — always `pytest`
- Use `tenacity` for retries — never `time.sleep()` in loops

### PyO3 bindings

- Every Python-facing async method uses `pyo3_async_runtimes::tokio::future_into_py`
- The inner Rust object is wrapped in `Arc<Mutex<Option<T>>>` — `Option` for clean shutdown semantics
- Error conversion: `YosoiError` → `PyRuntimeError` via `to_py_err()`
- Keep the binding layer thin — business logic belongs in `crates/core/`

## Adding a new Page method

1. **Rust core** (`crates/core/src/page.rs`): Add the async method on `Page`
2. **PyO3 binding** (`crates/pyo3_bindings/src/lib.rs`): Add corresponding `#[pymethods]` on `PyPage`
3. **Type stub** (`void_crawl.pyi`): Add the async signature
4. **Test**: Add a Rust test in `crates/core/tests/integration.rs` and a Python test in `tests/unit/core/fetcher/test_browser.py`

## Adding a new BrowserSession option

1. Add the field to `BrowserSessionBuilder` in `session.rs`
2. Wire it through `connect_or_launch()`
3. Expose it as a kwarg on `PyBrowserSession.__init__` in the bindings
4. Update the type stub and README

## CI

The GitHub Actions workflow (`.github/workflows/CI.yaml`) runs:

- `cargo check --workspace` — Rust compilation
- `cargo test -p void_crawl_core -- --test-threads=1` — Rust integration tests

Renovate manages Cargo dependency updates in the `void-crawl-rust-deps` group.

## Commit conventions

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(driver): add cookie management to Page
fix(driver): handle Chrome SingletonLock race condition
test(driver): add stealth config integration test
```

## License

Contributions are licensed under Apache-2.0, matching the project.
