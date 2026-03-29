# Stealth & Anti-Detection

yosoi_driver uses a **minimal-footprint** stealth strategy inspired by [zendriver](https://github.com/nicegamer7/zendriver) / [nodriver](https://github.com/nicegamer7/nodriver) — the async successor to undetected-chromedriver. Stealth is **enabled by default**.

## Philosophy: Less Is More

Most browser automation tools try to _spoof_ every fingerprint signal — fake plugins, fake WebGL, fake user-agent strings. This backfires against modern WAFs (Akamai, Cloudflare, PerimeterX) because:

1. **Spoofed values are inconsistent.** A hardcoded `Chrome/131` user-agent on a system running Chromium 146 is an instant flag. Fake WebGL renderer strings that don't match the actual GPU are trivially detected.

2. **The spoofing itself is detectable.** Each `Page.addScriptToEvaluateOnNewDocument` CDP call is a fingerprint. Overriding `navigator.plugins` with a Proxy/getter behaves differently from the real `PluginArray` prototype — detection scripts check for exactly this.

3. **The automation signal isn't in JS — it's in Chrome's launch flags.** chromiumoxide's default flags include `--enable-automation`, which tells every WAF "I'm automated" before any page loads.

yosoi_driver's approach: **don't fake anything** except the one property Chrome explicitly sets for automation (`navigator.webdriver`). Instead, launch Chrome with clean flags that don't advertise automation.

## What Changed from chromiumoxide Defaults

### Removed (toxic flags)

| Flag | Why it's bad |
|---|---|
| `--enable-automation` | Literally opts in to automation detection |
| `--disable-extensions` | Normal Chrome always has extensions support |
| `--enable-blink-features=IdleDetection` | Unusual feature that fingerprints automation |

### Added (zendriver flags)

| Flag | Purpose |
|---|---|
| `--disable-blink-features=AutomationControlled` | Removes Chrome's automation-controlled blink feature |
| `--disable-features=IsolateOrigins,site-per-process` | Disables site isolation that WAFs use for fingerprinting |
| `--no-pings` | Suppresses background pings |
| `--disable-component-update` | Prevents background update checks |
| `--disable-session-crashed-bubble` | Suppresses crash UI |
| `--disable-search-engine-choice-screen` | Suppresses search engine prompt |
| `--homepage=about:blank` | Clean startup page |

### Kept (safe defaults)

Standard flags like `--disable-background-networking`, `--disable-breakpad`, `--disable-dev-shm-usage`, `--no-first-run`, etc. are retained — they reduce noise without being automation signals.

## What the JS Stealth Layer Does

Only two patches are injected via `addScriptToEvaluateOnNewDocument`:

### 1. `navigator.webdriver` Removal

Chrome explicitly sets `navigator.webdriver = true` when connected via CDP. We delete it from the prototype chain and redefine it as `undefined`:

```javascript
delete Object.getPrototypeOf(navigator).webdriver;
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});
```

### 2. Force-Open Shadow DOMs

Cloudflare Turnstile and similar WAF challenges render inside closed shadow roots. We force all `attachShadow` calls to use `mode: 'open'` so the automation layer can interact with challenge elements:

```javascript
Element.prototype._attachShadow = Element.prototype.attachShadow;
Element.prototype.attachShadow = function(init) {
    return this._attachShadow({ ...init, mode: 'open' });
};
```

### What We Don't Patch (and why)

| Signal | Why we leave it alone |
|---|---|
| `navigator.plugins` | Real Chrome already populates this. Faking it creates detectable inconsistencies. |
| `navigator.userAgent` | We use Chrome's real UA. Hardcoding a version creates a mismatch with the actual browser. |
| WebGL vendor/renderer | The real GPU info from the system is more convincing than any fake string. |
| `window.chrome.runtime` | Real Chrome already has this. |
| `navigator.permissions` | The default behavior is already correct. |
| Canvas fingerprint | Can't be spoofed reliably without introducing detectable noise. |

## Headful vs Headless

For WAF-protected sites (Akamai, Cloudflare), **headful mode is required**. Headless Chrome has fundamental differences that sophisticated WAFs detect regardless of JS patches:

- Different rendering pipeline (no compositing)
- Missing screen/display properties
- HTTP/2 TLS fingerprint differences

```python
from yosoi import yd

# For WAF-protected sites — use headful
async with await yd.pool(headless=False) as pool:
    async with await pool.acquire() as tab:
        await tab.navigate("https://waf-protected-site.com")
        await tab.wait_for_stable_dom(timeout=15.0)
        html = await tab.content()

# For unprotected sites — headless is fine and faster
async with await yd.pool() as pool:
    async with await pool.acquire() as tab:
        await tab.navigate("https://example.com")
        html = await tab.content()
```

## DOM Stability Waiting

JS-heavy sites and WAF challenge pages don't have their content ready at page load. Instead of a blind `sleep()`, use `wait_for_stable_dom()`:

```python
async with await pool.acquire() as tab:
    await tab.navigate(url)

    # Polls every 300ms. Returns True when:
    #   - innerHTML.length >= min_length (default 5000)
    #   - Size unchanged for stable_checks consecutive polls (default 5)
    stabilised = await tab.wait_for_stable_dom(
        timeout=15.0,      # max seconds to wait
        min_length=5000,   # min chars before page is "real"
        stable_checks=5,   # consecutive stable polls required
    )

    if not stabilised:
        print("Page didn't fully render — may be a stub or redirect gate")
```

This prevents redirect gates, loading spinners, and Akamai challenge pages from being mistaken for real content.

## Disabling Stealth

```python
# Via BrowserSession
async with BrowserSession(stealth=False) as session:
    page = await session.new_page("https://trusted-site.com")

# Stealth is always on for BrowserPool (via yd.pool())
# The minimal patches have negligible overhead
```

## Real-World Results

Tested against Akamai WAF (BusinessWire) — the same site that blocks Playwright, Selenium, and even chromiumoxide with heavy stealth patches:

| Approach | Result |
|---|---|
| chromiumoxide defaults (`--enable-automation`) | 403 Access Denied |
| chromiumoxide + heavy JS spoofing + fake UA | 403 Access Denied |
| chromiumoxide + `disable_default_args` + clean flags + no UA override | **Success (600K chars)** |
| zendriver (reference) | Success |
| Plain curl | 403 Access Denied |

The lesson: **the flags matter more than the JS patches.**
