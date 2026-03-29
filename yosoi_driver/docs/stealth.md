# Stealth & Anti-Detection

yosoi_driver includes built-in stealth capabilities to make automated Chrome sessions look like regular user traffic. Stealth is **enabled by default**.

## What Stealth Does

When `stealth=True` (the default), every new page gets the following patches applied **before** any navigation occurs:

### 1. `navigator.webdriver` Removal

Headless Chrome sets `navigator.webdriver = true`. The stealth layer deletes this property so detection scripts see `undefined` (the normal browser value).

### 2. Plugin Spoofing

Real Chrome exposes plugins like "Chrome PDF Plugin" and "Chrome PDF Viewer" in `navigator.plugins`. The stealth layer injects realistic plugin entries.

### 3. Language Headers

`navigator.languages` is set to `["en-US", "en"]` (configurable in Rust via `StealthConfig::locale`), matching a realistic `Accept-Language` header.

### 4. `window.chrome.runtime`

Many detection scripts check for the existence of `window.chrome.runtime`. The stealth layer creates a minimal stub that passes basic existence checks.

### 5. Permissions API

`navigator.permissions.query()` is patched so that querying the `"notifications"` permission returns `"denied"` instead of `"prompt"`, which is the expected state for a real browser with default settings.

### 6. Content Security Policy Bypass

CSP bypass is enabled, allowing the stealth JavaScript to be injected even on pages with strict Content Security Policy headers.

### 7. Chromiumoxide Built-in Stealth

The `enable_stealth_mode` flag in chromiumoxide applies additional low-level CDP patches.

## Usage

```python
# Stealth ON (default)
async with BrowserSession(headless=True) as session:
    page = await session.new_page("https://bot-detector.example.com")

# Stealth OFF
async with BrowserSession(headless=True, stealth=False) as session:
    page = await session.new_page("https://trusted-internal-site.com")
```

## Checking Your Fingerprint

Use JavaScript evaluation to inspect what detection scripts see:

```python
import json

page = await session.new_page("https://example.com")

fingerprint = json.loads(await page.evaluate_js("""
    JSON.stringify({
        webdriver: navigator.webdriver,
        plugins: navigator.plugins.length,
        languages: navigator.languages,
        chrome_runtime: typeof window.chrome?.runtime,
    })
"""))

print(fingerprint)
# With stealth:    {'webdriver': None, 'plugins': 3, 'languages': ['en-US', 'en'], 'chrome_runtime': 'object'}
# Without stealth: {'webdriver': True, 'plugins': 0, 'languages': [], 'chrome_runtime': 'undefined'}
```

## Limitations

- Stealth patches target **common** detection vectors. Sophisticated fingerprinting services (e.g. those analyzing WebGL rendering, canvas hashes, or TLS fingerprints) may still detect automation.
- The stealth configuration is currently set at the Rust level via `StealthConfig`. The Python API exposes a boolean toggle; fine-grained control (custom user agent, viewport size, locale) requires modifying the Rust builder or using `evaluate_js` to patch additional properties.
- Stealth is applied per-page at creation time. If you need to change stealth settings mid-session, open a new page.

## See Also

- [`examples/stealth_mode.py`](../examples/stealth_mode.py) — side-by-side comparison of stealth vs non-stealth fingerprints
