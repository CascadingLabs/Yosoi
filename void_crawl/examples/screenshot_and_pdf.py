"""Capture screenshots (PNG) and PDF exports of a page."""

import asyncio
from pathlib import Path

from yosoi import vc

OUTPUT_DIR = Path('output')


async def _capture() -> None:
    """Open example.com and save a PNG screenshot and PDF export."""
    async with vc.page('https://example.com') as page:
        # PNG screenshot
        png_bytes = await page.screenshot_png()
        png_path = OUTPUT_DIR / 'example.png'
        png_path.write_bytes(png_bytes)
        print(f'Screenshot saved: {png_path} ({len(png_bytes)} bytes)')

        # PDF export (headless only)
        pdf_bytes = await page.pdf_bytes()
        pdf_path = OUTPUT_DIR / 'example.pdf'
        pdf_path.write_bytes(pdf_bytes)
        print(f'PDF saved: {pdf_path} ({len(pdf_bytes)} bytes)')


def main() -> None:
    """Capture a PNG screenshot and PDF export of example.com."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    asyncio.run(_capture())


if __name__ == '__main__':
    main()
