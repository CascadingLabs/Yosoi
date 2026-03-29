"""Use yosoi_driver with Chrome running headful inside Docker.

This example connects to Chrome instances running in the Docker headful
container (Sway + wayvnc + GPU-accelerated Chrome). You can watch
everything Chrome does by opening a VNC client to localhost:5900.

Setup (run this first in a separate terminal):

    ./docker/run-headful.sh          # auto-detects your GPU
    # or: ./docker/run-headful.sh --gpu amd

Then run this script:

    uv run python yosoi_driver/examples/docker_headful.py

Watch Chrome live in your browser:
    Open http://localhost:6080 and click Connect.
    (Or use a VNC client on localhost:5900 for lower latency.)

What you'll see:
    - Chrome navigating to Wikipedia
    - The page fully rendering with images, CSS, layout
    - A screenshot being captured
    - Chrome navigating to a second URL
    - Everything happens in real time
"""

import asyncio
import os

from yosoi_driver import BrowserPool


async def main() -> None:
    """Connect to Docker headful Chrome and demonstrate navigation, DOM queries, screenshots."""
    # ── Connect to Docker Chrome ─────────────────────────────────────
    # The headful Docker container runs Chrome on ports 19222 and 19223.
    # These are different from the default 9222/9223 to avoid conflicts
    # with any Chrome you might be running natively.
    os.environ['CHROME_WS_URLS'] = 'http://localhost:19222,http://localhost:19223'
    os.environ['TABS_PER_BROWSER'] = '2'

    async with await BrowserPool.from_env() as pool:
        # ── Basic navigation ─────────────────────────────────────────
        # Open a tab and navigate. If you have a VNC client open on
        # localhost:5900, you'll see Chrome loading this page right now.
        async with await pool.acquire() as tab:
            # goto() combines navigate + wait-for-network-idle in one shot.
            # It sets up the CDP event listener BEFORE starting navigation,
            # so it never misses an early networkIdle event.
            event = await tab.goto(
                'https://en.wikipedia.org/wiki/Web_scraping',
                timeout=30.0,
            )
            print(f'Wait event: {event}')
            # "networkIdle" = 0 in-flight requests for 500ms (best signal)
            # "networkAlmostIdle" = ≤2 in-flight requests (fallback)
            # None = timeout reached

            title = await tab.title()
            html = await tab.content()
            print(f'Title: {title}')
            print(f'HTML: {len(html):,} chars')

            # ── DOM queries ──────────────────────────────────────────
            # query_selector_all uses a single JS eval that returns all
            # results at once — no N serial CDP round-trips.
            headings = await tab.query_selector_all('#toc li a')
            print(f'Table of contents entries: {len(headings)}')
            for h in headings[:5]:
                # Each entry is an <a> tag innerHTML like "1.2 Legal issues"
                print(f'  - {h}')

            # ── Screenshot ───────────────────────────────────────────
            # Full-page PNG. In VNC you'll see the page exactly as it
            # looks in the screenshot.
            png_bytes = await tab.screenshot_png()
            import anyio

            await anyio.Path('/tmp/docker_headful_screenshot.png').write_bytes(png_bytes)
            print(f'Screenshot: {len(png_bytes):,} bytes -> /tmp/docker_headful_screenshot.png')

            # ── JavaScript evaluation ────────────────────────────────
            # Returns native Python types (dict, list, int, etc.),
            # not JSON strings.
            link_count = await tab.evaluate_js('document.querySelectorAll("a").length')
            print(f'Links on page: {link_count}')  # an int, not "123"

        # ── Parallel fetch ───────────────────────────────────────────
        # Watch VNC — you'll see both tabs loading simultaneously.
        print('\nParallel fetch (watch both tabs in VNC!)...')

        async def fetch(url: str) -> tuple[str, int]:
            async with await pool.acquire() as tab:
                await tab.goto(url)
                t = await tab.title()
                length = len(await tab.content())
                return t or '(no title)', length

        results = await asyncio.gather(
            fetch('https://en.wikipedia.org/wiki/Web_scraping'),
            fetch('https://en.wikipedia.org/wiki/Rust_(programming_language)'),
        )
        for title, length in results:
            print(f'  {title}: {length:,} chars')

    print('\nDone! The Docker container is still running.')
    print('Connect VNC to localhost:5900 to see the Chrome windows.')
    print('Stop with: docker compose -f docker/docker-compose.headful.yml --profile amd down')


if __name__ == '__main__':
    asyncio.run(main())
