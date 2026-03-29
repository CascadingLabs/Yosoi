"""Work with multiple pages (tabs) in a single browser session."""

import asyncio

from yosoi import vc

URLS = [
    'https://example.com',
    'https://httpbin.org/html',
    'https://www.iana.org/domains/reserved',
]


async def main() -> None:
    """Open multiple tabs concurrently and print their titles."""
    async with vc.pages(*URLS) as opened:
        for page in opened:
            title = await page.title()
            url = await page.url()
            print(f'  {url}  ->  {title}')


if __name__ == '__main__':
    asyncio.run(main())
