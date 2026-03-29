"""Demonstrate stealth vs non-stealth browser sessions.

Stealth mode (enabled by default) patches common bot-detection signals:
  - navigator.webdriver is removed
  - navigator.plugins is populated
  - navigator.languages is set realistically
  - window.chrome.runtime is spoofed
  - navigator.permissions.query behaves like a real browser
"""

import asyncio
import json

from yosoi_driver import BrowserSession

DETECTION_JS = """
JSON.stringify({
    webdriver: navigator.webdriver,
    plugins_count: navigator.plugins.length,
    languages: navigator.languages,
    has_chrome_runtime: typeof window.chrome !== 'undefined'
        && typeof window.chrome.runtime !== 'undefined',
})
"""


async def check_fingerprint(label: str, session: BrowserSession) -> None:
    """Print bot-detection fingerprint signals for the given session."""
    page = await session.new_page('https://example.com')
    raw = await page.evaluate_js(DETECTION_JS)
    fingerprint = json.loads(json.loads(raw))
    print(f'\n[{label}]')
    for key, value in fingerprint.items():
        print(f'  {key}: {value}')
    await page.close()


async def main() -> None:
    """Compare fingerprints with stealth enabled vs disabled."""
    # Stealth ON (default)
    async with BrowserSession(headless=True, stealth=True) as stealth:
        await check_fingerprint('stealth=True', stealth)

    # Stealth OFF
    async with BrowserSession(headless=True, stealth=False) as bare:
        await check_fingerprint('stealth=False', bare)


if __name__ == '__main__':
    asyncio.run(main())
