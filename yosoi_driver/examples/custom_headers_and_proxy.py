"""Set custom HTTP headers and use a proxy server."""

import asyncio

from yosoi_driver import BrowserSession


async def custom_headers() -> None:
    """Inject custom HTTP headers into every request from a page."""
    async with BrowserSession(headless=True) as session:
        page = await session.new_page('about:blank')

        await page.set_headers(
            {
                'Accept-Language': 'ja-JP,ja;q=0.9',
                'X-Custom-Token': 'my-secret-token',
            }
        )

        # Subsequent navigations will include these headers
        await page.navigate('https://httpbin.org/headers')
        content = await page.content()
        print('Response with custom headers:')
        print(content[:500])

        await page.close()


async def with_proxy() -> None:
    """Launch a browser that routes traffic through a proxy.

    Requires a running proxy (e.g. `mitmproxy` on port 8080).
    Uncomment and adjust the proxy URL to try it out.
    """
    # async with BrowserSession(
    #     headless=True,
    #     proxy="http://127.0.0.1:8080",
    # ) as session:
    #     page = await session.new_page("https://httpbin.org/ip")
    #     print(await page.content())
    #     await page.close()
    print('Proxy example is commented out — set a real proxy URL to run it.')


async def main() -> None:
    """Run the custom headers and proxy demos."""
    await custom_headers()
    await with_proxy()


if __name__ == '__main__':
    asyncio.run(main())
