"""Benchmark: headless vs headful Chrome using a persistent instance with concurrent tabs.

Both approaches use a single persistent Chrome browser with concurrent tabs.
The only difference is whether Chrome runs with a visible window or not.

Smart content waiting: polls the DOM every 200ms and stops as soon as the
page has been stable (unchanged innerHTML size) for 3 consecutive checks,
or gives up at the upper-bound timeout. No site-specific selectors needed.
"""

import asyncio
import contextlib
import logging
import os
import shutil
import time

import zendriver as zd
from rich.console import Console

from yosoi.core.cleaning import HTMLCleaner

TEST_URLS = [
    'https://qscrape.dev/l1/news/article/?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-017%26HASH%3Dsyv327xx5lcXXXNNNXXXtR7vYw1hF3dGXXXNNNXXX',
    'https://qscrape.dev/l1/news/article/?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-019%26HASH%3Dkf4bmiee3waXXXNNNXXXtR7vYw1hF3dGXXXNNNXXX',
    'https://finance.yahoo.com/video/three-big-questions-left-musk-125600891.html',
    'https://finance.yahoo.com/news/oil-price-spike-likely-to-keep-rates-on-hold-but-deepen-divisions-among-fed-officials-this-week-090015969.html',
    'https://finance.yahoo.com/news/nvidia-gtc-2026-what-to-expect-from-nvidias-biggest-event-of-the-year-132234592.html',
]

# Upper bound in seconds — we never wait longer than this for content
CONTENT_WAIT_TIMEOUT = 8.0

# How often to re-check DOM size (seconds)
POLL_INTERVAL = 0.2

# Number of consecutive unchanged polls before we consider the page stable
STABLE_CHECKS = 3

MAX_CONCURRENT = 5

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


def url_to_label(url: str) -> str:
    """Convert a URL into a short readable label for display in results.

    Examples:
        qscrape.dev / MHH-017
        finance.yahoo.com / nvidia-gtc-2026
    """
    import re
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '')

    if 'ID%3D' in url:
        slug = url.split('ID%3D')[1].split('%26')[0]
    else:
        path_parts = [p for p in parsed.path.split('/') if p]
        raw_slug = path_parts[-1] if path_parts else 'page'
        slug = unquote(raw_slug.split('.')[0][:50])
        slug = re.sub(r'[^a-zA-Z0-9_-]', '-', slug)
        slug = re.sub(r'-+', '-', slug).strip('-')
        # Trim long numeric ID suffix from Yahoo Finance slugs (e.g. -090015969)
        slug = re.sub(r'-[0-9]{6,}$', '', slug)

    return f'{domain} / {slug}'


# ---------------------------------------------------------------------------
# Smart content wait
# ---------------------------------------------------------------------------


async def wait_for_content(tab) -> tuple[bool, float]:
    """Wait until the DOM stops changing, up to CONTENT_WAIT_TIMEOUT seconds.

    Polls innerHTML size every POLL_INTERVAL seconds. Once the size has been
    identical for STABLE_CHECKS consecutive polls, the page is considered
    stable and we proceed. Falls back to the hard timeout for pages that
    never fully settle (e.g. live tickers, infinite scroll).

    Guards every JS call against document.body being null, which can happen
    while the page is still mid-navigation.

    Returns:
        (stable, seconds_waited) — stable is False only if we hit the timeout
        without ever seeing a stable DOM.
    """
    deadline = time.time() + CONTENT_WAIT_TIMEOUT
    previous_size = 0
    stable_count = 0

    while time.time() < deadline:
        size = await tab.evaluate('document.body ? document.body.innerHTML.length : 0')
        if size > 0 and size == previous_size:
            stable_count += 1
            if stable_count >= STABLE_CHECKS:
                waited = CONTENT_WAIT_TIMEOUT - (deadline - time.time())
                return True, round(waited, 3)
        else:
            stable_count = 0
            previous_size = size

        await asyncio.sleep(POLL_INTERVAL)

    return False, CONTENT_WAIT_TIMEOUT


# ---------------------------------------------------------------------------
# Shared fetch logic (used by both approaches)
# ---------------------------------------------------------------------------


async def get_raw_html(tab) -> str:
    """Get the full rendered body HTML from a tab."""
    result = await tab.evaluate('document.body.innerHTML')
    return result.strip() if result else ''


def clean(raw_html: str) -> str:
    """Strip noise from raw HTML using HTMLCleaner."""
    return cleaner.clean_html(raw_html)


async def fetch_tab(browser, url: str, semaphore: asyncio.Semaphore, label: str) -> dict:
    """Open a new tab, enable ad blocking, wait for content, clean the HTML, close the tab.

    Args:
        browser: Active zendriver Browser instance.
        url: URL to fetch.
        semaphore: Concurrency limiter.
        label: Short label for console output (e.g. '[A headless]').

    Returns:
        Result dict with url, success, fetch_time, raw_size, cleaned_size,
        wait_time, stable, content, and error fields.
    """
    async with semaphore:
        t0 = time.time()
        tab = None
        try:
            console.print(f'\n  {label} {url[:70]}...')

            tab = await browser.get(url, new_tab=True)
            await tab.wait_for_ready_state('complete', timeout=30)

            stable, wait_time = await wait_for_content(tab)

            raw_html = await get_raw_html(tab)
            cleaned = clean(raw_html)

            result = {
                'url': url,
                'success': True,
                'fetch_time': round(time.time() - t0, 3),
                'wait_time': wait_time,
                'stable': stable,
                'raw_size': len(raw_html),
                'cleaned_size': len(cleaned),
                'content': cleaned,
                'error': None,
            }
            selector_note = '✓ stable' if stable else '✗ timeout'
            console.print(
                f'      {result["fetch_time"]}s (waited {wait_time}s {selector_note}) | '
                f'raw={result["raw_size"]:,} → cleaned={result["cleaned_size"]:,} chars'
            )
            return result

        except Exception as e:  # noqa: BLE001
            error_type = type(e).__name__
            error_msg = str(e)

            # Give the user a plain-English hint about common failures
            if 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower():
                hint = 'Page took too long to respond — try increasing CONTENT_WAIT_TIMEOUT'
            elif 'net::err_name_not_resolved' in error_msg.lower():
                hint = 'DNS lookup failed — check the URL or your network connection'
            elif 'net::err_connection_refused' in error_msg.lower():
                hint = 'Connection refused — the server may be down'
            elif 'net::err_aborted' in error_msg.lower():
                hint = 'Request aborted — the page may have redirected or closed early'
            elif 'protocol' in error_msg.lower() or 'cdp' in error_msg.lower():
                hint = 'Chrome CDP error — the tab may have crashed or been closed'
            else:
                hint = 'Unexpected error — see error field for details'

            console.print(
                f'      [red]FAILED[/red] after {round(time.time() - t0, 2)}s\n'
                f'      [dim]{error_type}: {error_msg[:120]}[/dim]\n'
                f'      [yellow]Hint: {hint}[/yellow]'
            )
            return {
                'url': url,
                'success': False,
                'fetch_time': round(time.time() - t0, 3),
                'wait_time': 0.0,
                'stable': False,
                'raw_size': 0,
                'cleaned_size': 0,
                'content': None,
                'error': f'{error_type}: {error_msg}',
                'hint': hint,
            }
        finally:
            if tab:
                with contextlib.suppress(Exception):
                    await tab.close()


# ---------------------------------------------------------------------------
# Shared browser runner
# ---------------------------------------------------------------------------


async def run_approach(chrome: str, headless: bool, label: str) -> tuple[list[dict], float]:
    """Start a persistent Chrome instance, pre-warm it, then fetch all TEST_URLS in parallel.

    Args:
        chrome: Path to Chrome binary.
        headless: Whether to run Chrome without a visible window.
        label: Short prefix for console output (e.g. '[A headless]').

    Returns:
        (results, total_wall_time)
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    start = time.time()
    browser = await zd.start(headless=headless, browser_executable_path=chrome)

    try:
        # Pre-warm: open a blank tab so Chrome fully initialises before real
        # fetches start. The first real tab otherwise pays the browser startup
        # cost, making it slower than all subsequent tabs.
        warmup = await browser.get('about:blank')
        with contextlib.suppress(Exception):
            await warmup.close()

        results = await asyncio.gather(*[fetch_tab(browser, url, semaphore, label) for url in TEST_URLS])
    finally:
        with contextlib.suppress(Exception):
            await browser.stop()

    return list(results), round(time.time() - start, 3)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run headless vs headful benchmark and report results."""
    chrome = find_chrome()
    console.print(f'\n[bold]Chrome:[/bold]          {chrome}')
    console.print(f'[bold]URLs:[/bold]            {len(TEST_URLS)}')
    console.print(
        f'[bold]Content timeout:[/bold] {CONTENT_WAIT_TIMEOUT}s (polls every {POLL_INTERVAL}s, stable after {STABLE_CHECKS} unchanged checks)'
    )
    console.print(f'[bold]Max concurrent:[/bold]  {MAX_CONCURRENT} tabs\n')

    console.rule('[bold]Approach A: Headless Chrome[/bold]')
    results_a, total_a = await run_approach(chrome, headless=True, label='[A headless]')

    console.rule('[bold]Approach B: Headful Chrome[/bold]')
    results_b, total_b = await run_approach(chrome, headless=False, label='[B headful]')

    summary = {
        'approach_a': {
            'description': f'Headless Chrome, {MAX_CONCURRENT} concurrent tabs',
            'total_time': total_a,
            'results': [{k: v for k, v in r.items() if k != 'content'} for r in results_a],
        },
        'approach_b': {
            'description': f'Headful Chrome, {MAX_CONCURRENT} concurrent tabs',
            'total_time': total_b,
            'results': [{k: v for k, v in r.items() if k != 'content'} for r in results_b],
        },
        'speedup': round(total_a / total_b, 2) if total_b > 0 else None,
    }

    console.rule('[bold]Results[/bold]')
    console.print(f'  Approach A (headless) total : {total_a}s')
    console.print(f'  Approach B (headful)  total : {total_b}s')
    if summary['speedup'] is not None:
        faster = 'headless' if total_a < total_b else 'headful'
        console.print(f'  Faster approach            : {faster} ({summary["speedup"]}x)')

    col = 52  # fixed label column width for alignment

    def print_results(results: list[dict], heading: str) -> None:
        """Print per-URL results inline with ✓/✗ in order."""
        console.print(f'\n  [bold]{heading}[/bold]')
        for result in results:
            label = url_to_label(result['url'])
            # Truncate to col width so numbers always align regardless of label length
            label_display = label[:col] if len(label) > col else label
            if result['success'] and result['raw_size']:
                reduction = round((1 - result['cleaned_size'] / result['raw_size']) * 100)
                console.print(
                    f'  [green]✓[/green] {label_display:<{col}} '
                    f'{result["raw_size"]:>10,} → {result["cleaned_size"]:>8,} chars  ({reduction}%)'
                )
            else:
                error = result.get('error', 'unknown error')
                hint = result.get('hint', '')
                console.print(f'  [red]✗[/red] {label_display}')
                console.print(f'      [dim]{error[:120]}[/dim]')
                if hint:
                    console.print(f'      [yellow]→ {hint}[/yellow]')

    print_results(results_a, 'Headless')
    print_results(results_b, 'Headful')
    console.print()


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
