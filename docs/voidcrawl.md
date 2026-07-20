# VoidCrawl integration

Yosoi uses [VoidCrawl](https://github.com/CascadingLabs/VoidCrawl) for every rendered-browser path. There is no Playwright, Selenium, or Puppeteer backend. Yosoi currently pins `voidcrawl==0.3.8.2`; the matching upstream documentation is at [cascadinglabs.com/voidcrawl](https://cascadinglabs.com/voidcrawl/).

## Installation

Installing Yosoi installs the pinned VoidCrawl wheel, so Rust is not required:

```bash
uv add yosoi
```

A source build is needed only when developing VoidCrawl itself. Chrome or Chromium must be available when Yosoi launches a local browser. A remote/Docker Chrome pool can instead be supplied through `CHROME_WS_URLS` or Yosoi's `chrome_ws_urls` fetcher option.

## Yosoi fetchers

Use `create_fetcher` with one of the documented fetcher names:

```python
from yosoi.core.fetcher import create_fetcher


async def fetch_rendered():
    fetcher = create_fetcher('headless', no_sandbox=True)
    async with fetcher:
        result = await fetcher.fetch('https://example.com')
        print(result.html)
```

- `headless` and `headful` use VoidCrawl directly.
- `auto` and `waterfall` begin with simple HTTP acquisition and escalate to VoidCrawl when rendering is needed.
- `simple` never launches a browser.

Yosoi owns the fetcher lifecycle. Callers should enter it as an async context manager rather than constructing or closing VoidCrawl pools behind the fetcher's back.

## Direct VoidCrawl pool API

When using VoidCrawl independently of Yosoi, use the current `BrowserPool` API:

```python
from voidcrawl import BrowserPool, PoolConfig


async def fetch_directly():
    async with BrowserPool(PoolConfig()) as pool:
        async with pool.acquire() as tab:
            response = await tab.goto(
                'https://example.com',
                capture_endpoints=True,
            )
            print(response.html)
            print(response.url, response.status_code)
            print(response.endpoints)
```

`pool.acquire()` is an async context manager and is not awaited separately. `goto()` performs navigation plus network-idle waiting and returns a `PageResponse`.

## Evidence boundary

Yosoi's VoidCrawl wrapper requests `capture_endpoints=True` when the installed API supports it. It consumes:

- response headers for the lightweight network fingerprint layer;
- sanitized `PageResponse.endpoints` for XHR/fetch structure;
- rendered DOM captured from the live tab;
- browser-computed accessibility-tree evidence;
- pre-fetched runtime values, action outputs, and downloads when explicitly configured.

VoidCrawl endpoint capture is opt-in and returns sorted, deduplicated `scheme://host/path` values with query strings, fragments, and user information removed at the source. Yosoi carries that already-sanitized evidence into fingerprints; it does not place extracted field values into fingerprints.

## Profiles, identity, and isolation

Yosoi maps its browser policy onto `BrowserConfig` and `PoolConfig`, including headless/headful mode, proxy, locale, timezone, user agent, persistent profile directory, remote Chrome endpoints, and the explicit cross-origin DOM opt-in. A persistent `user_data_dir` belongs to one Chrome process and must not be shared across a multi-browser pool.

Yosoi's acquire-once rule still applies: browser acquisition happens in the fetcher, then selector and deterministic extractor fields consume the resulting page evidence without starting another browser or request.

## Compatibility checks

The pinned API surface is guarded by `tests/unit/core/fetcher/test_voidcrawl_compat.py`. Browser integration tests under `tests/integration/` require a working Chrome installation and are separate from the default unit suite.

Related documentation:

- [VoidCrawl quickstart](https://cascadinglabs.com/voidcrawl/quickstart/)
- [VoidCrawl browser pools](https://cascadinglabs.com/voidcrawl/guides/browser-pool/)
- [VoidCrawl cookbook and `PageResponse`](https://cascadinglabs.com/voidcrawl/guides/cookbook/)
- [Yosoi fingerprinting stack](fingerprinting-stack.md)
- [Yosoi A3Node replay](a3node-replay.md)
