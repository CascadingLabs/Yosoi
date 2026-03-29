"""Evaluate arbitrary JavaScript in the page context."""

import asyncio
import json

from yosoi import vc


async def main() -> None:
    """Evaluate various JavaScript expressions in a page context."""
    async with vc.page('https://example.com') as page:
        # Simple expression — returns a JSON string
        user_agent = await page.evaluate_js('navigator.userAgent')
        print(f'User agent: {json.loads(user_agent)}')

        # Compute something in-page
        result = await page.evaluate_js("document.querySelectorAll('p').length")
        print(f'Number of <p> tags: {json.loads(result)}')

        # Return structured data
        dims = await page.evaluate_js('JSON.stringify({w: window.innerWidth, h: window.innerHeight})')
        print(f'Viewport: {json.loads(json.loads(dims))}')

        # Modify the DOM via JS
        await page.evaluate_js("document.title = 'Modified by void_crawl'")
        print(f'New title: {await page.title()}')


if __name__ == '__main__':
    asyncio.run(main())
