"""Fetch a real-world page via BrowserPool and return cleaned HTML.

Demonstrates:
  1. Pool acquire → navigate → extract raw HTML
  2. Strip scripts, styles, nav, ads → return main article content
  3. Print a concise text summary

Run with:
  uv run python examples/pool_fetch_cleaned.py
  uv run python examples/pool_fetch_cleaned.py https://blog.google/technology/ai/
"""

from __future__ import annotations

import asyncio
import re
import sys
import time

from yosoi import yd

TARGET_URL = sys.argv[1] if len(sys.argv) > 1 else 'https://blog.google/technology/ai/'

# Tags whose entire subtree we want to remove
STRIP_TAGS = {
    'script',
    'style',
    'noscript',
    'iframe',
    'svg',
    'nav',
    'header',
    'footer',
    'aside',
}

# CSS classes / ids that typically wrap non-content
NOISE_PATTERNS = re.compile(
    r'(cookie|consent|banner|popup|modal|sidebar|social|share|related|promo|ad-|advertisement)',
    re.IGNORECASE,
)


def clean_html(raw: str) -> str:
    """Strip noise from raw HTML and return the main article content."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, 'lxml')

    # 1. Remove unwanted tags entirely
    for tag_name in STRIP_TAGS:
        for el in soup.find_all(tag_name):
            el.decompose()

    # 2. Remove elements whose class/id smells like noise
    for el in list(soup.find_all(True)):
        if el.attrs is None:
            continue
        classes = ' '.join(el.get('class', []))
        el_id = el.get('id', '')
        if NOISE_PATTERNS.search(classes) or NOISE_PATTERNS.search(el_id):
            el.decompose()

    # 3. Try to find the main content container
    article = (
        soup.find('main')
        or soup.find('article')
        or soup.find('div', class_=re.compile(r'article|story|content|body', re.I))
        or soup.body
    )

    if article is None:
        return soup.get_text(separator='\n', strip=True)

    # 4. Return cleaned HTML of the article container
    return str(article)


def extract_text(cleaned_html: str) -> str:
    """Convert cleaned HTML to plain text."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(cleaned_html, 'lxml')
    return soup.get_text(separator='\n', strip=True)


async def main() -> None:
    print(f'Target: {TARGET_URL}\n')

    t0 = time.perf_counter()

    async with yd.pool() as pool, await pool.acquire() as tab:
        await tab.navigate(TARGET_URL)

        # Wait for DOM to stabilise (min 5 000 chars, 5 consecutive polls)
        # instead of a blind sleep — prevents stubs / redirect gates.
        stabilised = await tab.wait_for_stable_dom(timeout=15.0)
        if not stabilised:
            print('Warning: DOM did not fully stabilise within timeout')

        title = await tab.title()
        current_url = await tab.url()
        raw_html = await tab.content()

    fetch_time = time.perf_counter() - t0

    print(f'Title: {title}')
    print(f'URL:   {current_url}')
    print(f'Raw HTML: {len(raw_html):,} chars')
    print(f'Fetch time: {fetch_time:.2f}s\n')

    # Clean
    t1 = time.perf_counter()
    cleaned = clean_html(raw_html)
    text = extract_text(cleaned)
    clean_time = time.perf_counter() - t1

    print(f'Cleaned HTML: {len(cleaned):,} chars')
    print(f'Plain text: {len(text):,} chars')
    print(f'Clean time: {clean_time:.3f}s\n')

    print('=' * 72)
    print('CLEANED HTML (first 3000 chars):')
    print('=' * 72)
    print(cleaned[:3000])
    print('\n...\n')

    print('=' * 72)
    print('PLAIN TEXT (first 2000 chars):')
    print('=' * 72)
    print(text[:2000])


if __name__ == '__main__':
    asyncio.run(main())
