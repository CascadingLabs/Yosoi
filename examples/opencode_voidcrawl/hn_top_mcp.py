"""Hacker News top — MCP-driven discovery variant. CAS-79 vs the structural HN case.

Static-HTML discovery struggled on HN because the cross-sibling row split
(`tr.athing` title row + next `<tr>` subline row) needs `global_id` to reach
correctly, and gpt-5.4-mini didn't internalise that even with a mechanical
detector hint surfacing the id-template pattern.

MCP-driven discovery should crack it by construction: the agent tries selectors
against the LIVE PAGE, sees what each one extracts, and only commits to
selectors that produced the right value. The cross-sibling reach is just
"try this, see what you get" instead of "guess from cleaned HTML".

Same Contract as ``hn_top.py``; only the discovery_mode flag differs.

    uv run python examples/opencode_voidcrawl/hn_top_mcp.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import yosoi as ys
from yosoi.core.fetcher.voiddriver import HeadlessFetcher

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from opencode_server import ensure_opencode_server

OUT_DIR = HERE / '.yosoi' / 'hn_mcp'
LISTING_URL = 'https://news.ycombinator.com/'
TARGET_STORIES = 5


class HNStory(ys.Contract):
    title: str = ys.Title(description='Story headline — the linked title text')
    url: str = ys.Url(description='Outbound link the title points to')
    author: str = ys.Author(description='Submitter username (the "by X" handle)')
    score: int | None = ys.Count(description='Story score in points')
    comments_count: int | None = ys.Count(description='Number of comments on the story')


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    async with ensure_opencode_server(cwd=str(HERE)):
        config = ys.opencode(
            extra_params={
                'provider_id': os.getenv('OC_PROVIDER', 'openai'),
                'model_id': os.getenv('OC_MODEL', 'gpt-5.4-mini'),
            }
        )
        pipeline = ys.Pipeline(config, contract=HNStory, discovery_mode='mcp')
        async with HeadlessFetcher(no_sandbox=True, experimental_a3node=True) as fetcher:
            print(f'=== HN top (MCP discovery {config.extra_params}) ===', flush=True)
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
