"""Connect to an already-running Chrome instance via its DevTools WebSocket URL.

Start Chrome with remote debugging enabled:

    google-chrome --remote-debugging-port=9222

Then run this script to attach to it.
"""

import asyncio

from yosoi_driver import BrowserSession


async def main() -> None:
    """Connect to Chrome on port 9222 and fetch a page title."""
    session = BrowserSession(
        ws_url='http://127.0.0.1:9222',  # HTTP endpoint or ws:// URL both work
        stealth=True,
    )
    await session.launch()

    print(f'Connected to Chrome {await session.version()}')

    page = await session.new_page('https://example.com')
    print(f'Title: {await page.title()}')

    await page.close()
    await session.close()


if __name__ == '__main__':
    asyncio.run(main())
