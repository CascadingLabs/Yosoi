# Getting Started

## Prerequisites

| Requirement | Minimum Version |
|-------------|----------------|
| Python | 3.10+ |
| Rust | 1.86+ |
| Chrome / Chromium | Any recent version |
| maturin | 1.7+ |
| uv | latest |

## Installation

### From the Yosoi workspace (development)

```bash
cd yosoi_driver
./build.sh
```

This runs `maturin develop --release` which compiles the Rust extension and installs it into the active virtualenv.

### Verify the install

```python
import yosoi_driver
print(dir(yosoi_driver))
# ['BrowserPool', 'BrowserSession', 'Page', 'PooledTab', ...]
```

## Quick Start — BrowserPool (recommended)

The pool pre-opens tabs and recycles them, giving near-instant page loads after the first warmup:

```python
import asyncio
from yosoi_driver import BrowserPool

async def main():
    async with await BrowserPool.from_env() as pool:
        async with await pool.acquire() as tab:
            await tab.navigate("https://example.com")
            print(await tab.title())   # "Example Domain"
            print(len(await tab.content()))

asyncio.run(main())
```

**Key points:**

- `BrowserPool.from_env()` reads `BROWSER_COUNT`, `TABS_PER_BROWSER`, etc. from env vars.
- `pool.acquire()` returns a `PooledTab` — use it like a `Page`. The context manager auto-releases it back to the pool.
- Tabs are recycled (navigated to `about:blank`) rather than closed, making subsequent acquires near-instant.

## Quick Start — BrowserSession (low-level)

For direct browser control without pooling:

```python
import asyncio
from yosoi_driver import BrowserSession

async def main():
    async with BrowserSession(headless=True) as session:
        page = await session.new_page("https://example.com")
        print(await page.title())   # "Example Domain"
        print(len(await page.content()))
        await page.close()

asyncio.run(main())
```

**Key points:**

- Every method on `Page`, `PooledTab`, and `BrowserSession` is **async** — always `await` them.
- Both `BrowserPool` and `BrowserSession` are async context managers that ensure clean shutdown.
- Stealth mode is **on by default**. Pass `stealth=False` to disable it.

## Docker

For production, Chrome runs as a persistent daemon in Docker with pre-warmed profiles:

```bash
cd docker
docker compose up -d
```

The pool connects to Chrome via `CHROME_WS_URLS` instead of launching it:

```bash
export CHROME_WS_URLS="http://localhost:9222,http://localhost:9223"
uv run python examples/pool_usage.py
```

## Running Examples

All examples live in the `examples/` directory and can be run directly:

```bash
uv run python examples/pool_usage.py           # Pool patterns with timing
uv run python examples/basic_navigation.py
uv run python examples/screenshot_and_pdf.py
uv run python examples/dom_and_interaction.py
```

## Next Steps

- [API Reference](api-reference.md) — full method signatures and return types
- [Stealth & Anti-Detection](stealth.md) — how stealth mode works and how to tune it
- [Architecture](architecture.md) — how the Rust core, PyO3 bindings, and Python layer fit together
