"""Use the JS waterfall fetcher on a qscrape.dev L2 news page.

This is the L2/JS-rendering path:
- fetcher_type="waterfall" tries Simple HTTP, then headless Chrome, then
  headful Chrome when the page looks JS-rendered or blocked.
- selector_level=SelectorLevel.XPATH allows L2 selector discovery when CSS is
  not expressive enough for the rendered DOM.

Run:
    uv run python examples/js_fetcher_qscript_l2.py

Optional:
    QSCRIPT_URL="https://qscrape.dev/l2/news/?id=MHH-001" \
    YOSOI_MODEL=groq:llama-3.3-70b-versatile \
    uv run python examples/js_fetcher_qscript_l2.py
"""

from __future__ import annotations

import asyncio
import json
import os

import yosoi as ys

QSCRIPT_URL = os.getenv('QSCRIPT_URL', 'https://qscrape.dev/l2/news/?id=MHH-001')


class QscrapeL2NewsArticle(ys.Contract):
    """Article data from a JS-rendered qscrape.dev L2 page."""

    headline: str = ys.Title(description='Main article headline')
    author: str = ys.Author(description='Article author or byline')
    date: str = ys.Datetime(description='Article publication date')
    body_text: str = ys.BodyText(description='Full article body text, excluding navigation and related links')
    related_content: str = ys.Field(description='Related article links or sidebar recommendations')


async def main() -> None:
    """Scrape the qscrape L2 article through the JS waterfall fetcher."""
    config = ys.auto_config()

    items = await ys.scrape(
        QSCRIPT_URL,
        QscrapeL2NewsArticle,
        model=config,
        force=True,
        fetcher_type='waterfall',
        selector_level=ys.SelectorLevel.XPATH,
        save_formats=('json',),
        quiet=False,
    )

    print(json.dumps(items, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
