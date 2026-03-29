"""Basic navigation: launch a browser, visit a page, read its content."""

import asyncio

from yosoi_driver import BrowserSession


async def main() -> None:
    """Launch a headless browser, visit example.com, and print page info."""
    async with BrowserSession(headless=True) as session:
        print(f'Browser version: {await session.version()}')

        page = await session.new_page('https://example.com')

        title = await page.title()
        url = await page.url()
        html = await page.content()

        print(f'Title: {title}')
        print(f'URL:   {url}')
        print(f'HTML length: {len(html)} chars')

        await page.close()


if __name__ == '__main__':
    asyncio.run(main())
