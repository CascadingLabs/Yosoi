"""Work with multiple pages (tabs) in a single browser session."""

import asyncio

from yosoi_driver import BrowserSession

URLS = [
    'https://example.com',
    'https://httpbin.org/html',
    'https://www.iana.org/domains/reserved',
]


async def main() -> None:
    """Open multiple tabs concurrently and print their titles."""
    async with BrowserSession(headless=True) as session:
        # Open several tabs concurrently
        pages = await asyncio.gather(*(session.new_page(url) for url in URLS))

        for page in pages:
            title = await page.title()
            url = await page.url()
            print(f'  {url}  ->  {title}')

        # Close them all
        await asyncio.gather(*(p.close() for p in pages))


if __name__ == '__main__':
    asyncio.run(main())
