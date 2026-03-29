"""BrowserPool usage examples demonstrating three patterns.

Run with: uv run python examples/pool_usage.py
"""

from __future__ import annotations

import asyncio
import time

from yosoi import yd

URLS = [
    'https://example.com',
    'https://www.iana.org/domains/reserved',
    'https://example.com',
]


async def pattern_one_shot() -> None:
    """Pattern 1: One-shot fetch via pool."""
    t0 = time.perf_counter()

    async with await yd.pool() as pool, await pool.acquire() as tab:
        await tab.navigate('https://example.com')
        title = await tab.title()
        print(f'  Title: {title}')

    elapsed = time.perf_counter() - t0
    print(f'  One-shot: {elapsed:.3f}s\n')


async def pattern_parallel() -> None:
    """Pattern 2: Parallel fetch through the pool."""
    t0 = time.perf_counter()

    async with await yd.pool() as pool:

        async def fetch(url: str) -> str:
            async with await pool.acquire() as tab:
                await tab.navigate(url)
                return await tab.content()

        results = await asyncio.gather(*[fetch(url) for url in URLS])
        for url, html in zip(URLS, results, strict=True):
            print(f'  {url}: {len(html)} chars')

    elapsed = time.perf_counter() - t0
    print(f'  Parallel ({len(URLS)} pages): {elapsed:.3f}s\n')


async def pattern_long_lived() -> None:
    """Pattern 3: Long-lived session with a dedicated tab."""
    t0 = time.perf_counter()

    async with await yd.pool() as pool, await pool.acquire() as tab:
        # Navigate to first page
        await tab.navigate('https://example.com')
        title1 = await tab.title()
        print(f'  Page 1: {title1}')

        # Navigate same tab to second page
        await tab.navigate('https://www.iana.org/domains/reserved')
        title2 = await tab.title()
        print(f'  Page 2: {title2}')

        url = await tab.url()
        print(f'  Final URL: {url}')

    elapsed = time.perf_counter() - t0
    print(f'  Long-lived session: {elapsed:.3f}s\n')


async def main() -> None:
    print('=== BrowserPool Usage Examples ===\n')

    print('Pattern 1: One-shot fetch')
    await pattern_one_shot()

    print('Pattern 2: Parallel fetch')
    await pattern_parallel()

    print('Pattern 3: Long-lived session')
    await pattern_long_lived()


if __name__ == '__main__':
    asyncio.run(main())
