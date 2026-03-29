"""Basic navigation: launch a browser, visit a page, read its content."""

import asyncio

from yosoi import yd


async def main() -> None:
    """Launch a headless browser, visit example.com, and print page info."""
    async with yd.page('https://example.com') as page:
        title = await page.title()
        url = await page.url()
        html = await page.content()

        print(f'Title: {title}')
        print(f'URL:   {url}')
        print(f'HTML length: {len(html)} chars')


if __name__ == '__main__':
    asyncio.run(main())
