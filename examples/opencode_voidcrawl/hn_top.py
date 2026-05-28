"""Hacker News top — the negative case. Server-rendered HTML, no custom elements.

A counterpoint to reddit_ted.py. Where reddit pushed every selector kind we
added (``attr`` for shreddit-post attributes, the action plan for
infinite-scroll), HN should pull NONE of them: plain ``<tr class="athing">``
rows, all data either as descendant text or in ``::attr(href)`` style. If the
discovery prompt has been tuned too aggressively toward "always reach for
``attr``", this is where it shows.

Structural quirk worth noting: each story spans TWO sibling ``<tr>`` rows.
The title lives in ``tr.athing``; the subline (score, author, comment count)
lives in the immediately-following ``<tr>``. Standard scoped-CSS-under-the-card
patterns don't work cleanly across siblings — the LLM has to either:
  * pick a larger root (e.g. the ``<table>``) and use complex descendant CSS,
  * use ``tr.athing + tr`` shape selectors to reach into the subline, or
  * use the shared id pattern (story rows have ``id=N``, score spans have
    ``id="score_N"``) to correlate across the gap.

We don't care which strategy it picks — we care that whatever it picks
produces correct values for all five fields on the first run, then replays
without LLM calls on every subsequent run. Same shape as reddit_ted.py.

    uv run python examples/opencode_voidcrawl/hn_top.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import yosoi as ys
from yosoi.core.fetcher.voiddriver import HeadlessFetcher

HERE = Path(__file__).parent
OUT_DIR = HERE / '.yosoi' / 'hn'
LISTING_URL = 'https://news.ycombinator.com/'
TARGET_STORIES = 5  # HN shows 30 by default; keep the smoke test small
DEFAULT_MODEL = 'openai/gpt-5.4-mini'  # same model as reddit_ted.py for parity


class HNStory(ys.Contract):
    """One Hacker News top story.

    All fields are visible-text / standard-anchor reads — no custom elements,
    no attribute payloads. The LLM should emit pure CSS selectors here.
    """

    title: str = ys.Title(description='Story headline — the linked title text')
    url: str = ys.Url(description='Outbound link the title points to')
    author: str = ys.Author(description='Submitter username (the "by X" handle)')
    score: int | None = ys.Count(description='Story score in points')
    comments_count: int | None = ys.Count(description='Number of comments on the story')


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model_name = os.getenv('YOSOI_MODEL', DEFAULT_MODEL)
    config = ys.openrouter(model_name)

    pipeline = ys.Pipeline(config, contract=HNStory)

    async with HeadlessFetcher(no_sandbox=True, experimental_a3node=True) as fetcher:
        print(f'=== HN top (openrouter {model_name}) ===', flush=True)
        stories = [item async for item in pipeline.scrape(LISTING_URL, fetcher=fetcher)]
        stories = stories[:TARGET_STORIES]

    print('\n=== results ===', flush=True)
    for i, s in enumerate(stories, 1):
        print(
            f'  #{i} {s.get("score")} pts · {s.get("comments_count")} comments · '
            f'by {s.get("author")} — {str(s.get("title", ""))[:80]!r}',
            flush=True,
        )
        link = s.get('url')
        if link:
            print(f'        url={link}', flush=True)

    out = OUT_DIR / 'top_stories.json'
    out.write_text(json.dumps(stories, indent=2), encoding='utf-8')
    print(f'\n  wrote {out}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
