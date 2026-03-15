"""Benchmark: new Chrome per URL vs persistent Chrome instance.

Fetches real JS-rendered pages, cleans the HTML using HTMLCleaner,
and saves timing to JSON + cleaned content to .html files.

Run:
    uv run yosoi/core/fetcher/benchmark.py
"""

import asyncio
import contextlib
import logging
import os
import shutil
import time

import zendriver as zd
from rich.console import Console

# HTMLCleaner lives in cleaner.py alongside this file
from yosoi.core.cleaning import HTMLCleaner

TEST_URLS = [
    'https://qscrape.dev/l1/news/article/?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-017%26HASH%3Dsyv327xx5lcXXXNNNXXXtR7vYw1hF3dGXXXNNNXXX',
    'https://qscrape.dev/l1/news/article/?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-019%26HASH%3Dkf4bmiee3waXXXNNNXXXtR7vYw1hF3dGXXXNNNXXX',
    'https://finance.yahoo.com/video/three-big-questions-left-musk-125600891.html',
]

WAIT_FOR_LOAD = 2.0
MAX_CONCURRENT = 3

console = Console()
cleaner = HTMLCleaner(console=console)


# ---------------------------------------------------------------------------
# Chrome auto-detection
# ---------------------------------------------------------------------------

_CHROME_PATHS = [
    '/opt/google/chrome/chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/snap/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
]


def find_chrome() -> str:
    """Return the path to the first Chrome/Chromium binary found on this system."""
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        found = shutil.which(name)
        if found:
            return found
    for path in _CHROME_PATHS:
        if os.path.isfile(os.path.expandvars(path)):
            return path
    raise RuntimeError(
        'Chrome not found. Install it or set the path manually in this script.\n'
        '  Ubuntu/Debian : sudo apt install chromium-browser\n'
        '  macOS         : brew install --cask google-chrome\n'
        '  Windows       : https://www.google.com/chrome'
    )


def url_to_filename(url: str, prefix: str) -> str:
    """Convert a URL to a short safe filename with the given prefix."""
    if 'ID%3D' in url:
        name = url.split('ID%3D')[1].split('%26')[0]
    elif 'yahoo' in url:
        name = 'yahoo_finance'
    else:
        name = url.split('/')[-1][:40] or 'page'
    return f'{prefix}_{name}'


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


async def get_raw_html(tab) -> str:
    """Get the full rendered body HTML from a tab."""
    result = await tab.evaluate('document.body.innerHTML')
    return result.strip() if result else ''


def clean(raw_html: str) -> str:
    """Strip noise from raw HTML using HTMLCleaner."""
    return cleaner.clean_html(raw_html)


# ---------------------------------------------------------------------------
# Approach A — new Chrome per URL
# ---------------------------------------------------------------------------


async def fetch_new_browser(url: str, chrome: str) -> dict:
    """Fetch a URL by starting a fresh Chrome instance, then stop it when done."""
    start = time.time()
    browser = None
    try:
        browser = await zd.start(headless=True, browser_executable_path=chrome)
        tab = await browser.get(url)
        await tab.wait_for_ready_state('complete', timeout=30)
        await asyncio.sleep(WAIT_FOR_LOAD)

        raw_html = await get_raw_html(tab)
        cleaned = clean(raw_html)

        return {
            'url': url,
            'success': True,
            'fetch_time': round(time.time() - start, 3),
            'raw_size': len(raw_html),
            'cleaned_size': len(cleaned),
            'content': cleaned,
            'error': None,
        }
    except OSError as e:
        return {
            'url': url,
            'success': False,
            'fetch_time': round(time.time() - start, 3),
            'raw_size': 0,
            'cleaned_size': 0,
            'content': None,
            'error': str(e),
        }
    finally:
        if browser:
            with contextlib.suppress(Exception):
                await browser.stop()


async def run_approach_a(chrome: str) -> tuple[list[dict], float]:
    """Fetch all TEST_URLS sequentially, starting a new Chrome instance per URL."""
    results = []
    start = time.time()
    for url in TEST_URLS:
        console.print(f'\n  [A] {url[:70]}...')
        result = await fetch_new_browser(url, chrome)
        if result['success']:
            console.print(
                f'      {result["fetch_time"]}s | raw={result["raw_size"]:,} → cleaned={result["cleaned_size"]:,} chars'
            )
        else:
            console.print(f'      FAILED: {result["error"]}')
        results.append(result)
    return results, round(time.time() - start, 3)


# ---------------------------------------------------------------------------
# Approach B — persistent Chrome, concurrent tabs
# ---------------------------------------------------------------------------


async def run_approach_b(chrome: str) -> tuple[list[dict], float]:
    """Fetch all TEST_URLS using one persistent Chrome instance with concurrent tabs."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    results: list[dict | None] = [None] * len(TEST_URLS)

    start = time.time()
    browser = await zd.start(headless=True, browser_executable_path=chrome)

    async def fetch_one(i: int, url: str):
        async with semaphore:
            t0 = time.time()
            tab = None
            try:
                console.print(f'\n  [B] {url[:70]}...')
                tab = await browser.get(url, new_tab=True)
                await tab.wait_for_ready_state('complete', timeout=30)
                await asyncio.sleep(WAIT_FOR_LOAD)

                raw_html = await get_raw_html(tab)
                cleaned = clean(raw_html)

                results[i] = {
                    'url': url,
                    'success': True,
                    'fetch_time': round(time.time() - t0, 3),
                    'raw_size': len(raw_html),
                    'cleaned_size': len(cleaned),
                    'content': cleaned,
                    'error': None,
                }
                r = results[i]
                console.print(f'      {r["fetch_time"]}s | raw={r["raw_size"]:,} → cleaned={r["cleaned_size"]:,} chars')
            except OSError as e:
                results[i] = {
                    'url': url,
                    'success': False,
                    'fetch_time': round(time.time() - t0, 3),
                    'raw_size': 0,
                    'cleaned_size': 0,
                    'content': None,
                    'error': str(e),
                }
                console.print(f'      FAILED: {e}')
            finally:
                if tab:
                    with contextlib.suppress(Exception):
                        await tab.close()

    try:
        await asyncio.gather(*[fetch_one(i, url) for i, url in enumerate(TEST_URLS)])
    finally:
        with contextlib.suppress(Exception):
            await browser.stop()

    return results, round(time.time() - start, 3)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    """Run both benchmark approaches and save results to disk."""
    chrome = find_chrome()
    console.print(f'\n[bold]Chrome:[/bold] {chrome}')
    console.print(f'[bold]URLs:[/bold]   {len(TEST_URLS)}\n')

    console.rule('[bold]Approach A: New Chrome per URL[/bold]')
    results_a, total_a = await run_approach_a(chrome)

    console.rule('[bold]Approach B: Persistent Chrome[/bold]')
    results_b, total_b = await run_approach_b(chrome)

    # --- Timing summary JSON (no content) ---
    summary = {
        'chrome': chrome,
        'wait_for_load': WAIT_FOR_LOAD,
        'max_concurrent': MAX_CONCURRENT,
        'approach_a': {
            'description': 'New Chrome instance per URL (sequential)',
            'total_time': total_a,
            'results': [{k: v for k, v in r.items() if k != 'content'} for r in results_a],
        },
        'approach_b': {
            'description': f'Persistent Chrome, {MAX_CONCURRENT} concurrent tabs',
            'total_time': total_b,
            'results': [{k: v for k, v in r.items() if k != 'content'} for r in results_b],
        },
        'speedup': round(total_a / total_b, 2) if total_b > 0 else None,
    }

    # --- Cleaned content files ---
    saved = []
    for prefix, results in [('a', results_a), ('b', results_b)]:
        for result in results:
            if result['content']:
                fname = url_to_filename(result['url'], prefix)
                saved.append((fname, result['raw_size'], result['cleaned_size']))

    console.rule('[bold]Results[/bold]')
    console.print(f'  Approach A total : {total_a}s')
    console.print(f'  Approach B total : {total_b}s')
    console.print(f'  Speedup          : {summary["speedup"]}x')
    for fname, raw, cleaned in saved:
        reduction = round((1 - cleaned / raw) * 100) if raw > 0 else 0
        console.print(f'  Content : {fname}  ({raw:,} → {cleaned:,} chars, {reduction}% reduction)')
    console.print()
    console.print(
        "For heavy SPAs like Yahoo Finance, the WAIT_FOR_LOAD value is really a 'how much of the page do you want'."
    )
    console.print('If we change the time to be longer then we have more content, but also more noise.')
    console.print('The reason A and B may be different is the <main> tag was replaced later in the load time.')
    console.print("Also sometimes the Yahoo Finance website won't load in time to be scraped.")
    console.print()


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
