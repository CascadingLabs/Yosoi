"""Use the JS waterfall fetcher on a qscrape.dev L2 news page.

This is the L2/JS-rendering path:
- fetcher_type="waterfall" tries Simple HTTP, then headless Chrome, then
  headful Chrome when the page looks JS-rendered or blocked.
- selector_level=SelectorLevel.XPATH allows L2 selector discovery when CSS is
  not expressive enough for the rendered DOM.

Run:
    uv run python examples/qscrape.dev/l2/news/js_fetcher_qscript_l2.py

Optional:
    QSCRIPT_URL="https://qscrape.dev/l2/news/?id=MHH-001" \
    YOSOI_MODEL=groq:llama-3.3-70b-versatile \
    YOSOI_FORCE=1 \
    uv run python examples/qscrape.dev/l2/news/js_fetcher_qscript_l2.py
"""

from __future__ import annotations

import asyncio
import json
import os

import yosoi as ys

QSCRIPT_URL = os.getenv('QSCRIPT_URL', 'https://qscrape.dev/l2/news/?id=MHH-001')
FORCE_SELECTORS = os.getenv('YOSOI_FORCE', '').lower() in {'1', 'true', 'yes'}


class QscrapeL2NewsArticle(ys.Contract):
    """Article data from a JS-rendered qscrape.dev L2 page."""

    root = ys.css('div[data-fw="react"] [data-component="news-article-detail"]')

    headline: str = ys.Title(description='Main article headline')
    author: str = ys.Author(description='Article author or byline')
    date: str = ys.Datetime(description='Article publication date')
    body_text: str = ys.BodyText(description='Full article body text')
    related_content: list[str] = ys.Field(description='Related or recommended article links')


async def main() -> None:
    """Scrape the qscrape L2 article through the JS waterfall fetcher."""
    config = ys.auto_config()

    items = await ys.scrape(
        QSCRIPT_URL,
        QscrapeL2NewsArticle,
        model=config,
        force=FORCE_SELECTORS,
        fetcher_type='waterfall',
        selector_level=ys.SelectorLevel.XPATH,
        save_formats=('json',),
        quiet=False,
    )

    print(json.dumps(items, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
