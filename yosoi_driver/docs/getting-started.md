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
# ['BrowserSession', 'Page', ...]
```

## Quick Start

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

- Every method on `Page` and `BrowserSession` is **async** — always `await` them.
- `BrowserSession` is an async context manager. Using `async with` ensures the browser process is cleaned up even if your code raises an exception.
- Stealth mode is **on by default**. Pass `stealth=False` to disable it.

## Running Examples

All examples live in the `examples/` directory and can be run directly:

```bash
uv run python examples/basic_navigation.py
uv run python examples/screenshot_and_pdf.py
uv run python examples/dom_and_interaction.py
```

## Next Steps

- [API Reference](api-reference.md) — full method signatures and return types
- [Stealth & Anti-Detection](stealth.md) — how stealth mode works and how to tune it
- [Architecture](architecture.md) — how the Rust core, PyO3 bindings, and Python layer fit together
