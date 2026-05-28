"""reddit r/ted — Contract-only, MCP-driven discovery (CAS-79).

The MCP counterpart to ``reddit_ted.py``. Same Contract; same target site;
same per-domain caching → indefinite replay. **The only difference** is the
discovery path: an OpenCode + voidcrawl-MCP agent loop tries selectors
against the live page and records what worked, instead of the static-HTML
LLM agent reasoning blind.

Why bother:

  * Static discovery needed a long rubric (RULES 1-4), HTML-cleaner attribute
    preservation, a SemanticValidator, and a feedback retry loop — all to
    compensate for the LLM never seeing the actual extracted value.
  * MCP discovery removes most of that. The agent SEES what its selector
    produced and self-corrects in real time. The rubric collapses to a short
    vocabulary doc.

This example proves the same Contract works under both modes, then defers
to the same replay machinery — first run discovers via MCP, every later run
replays from cache with zero LLM activity.

Required env:
  * ``opencode`` CLI on PATH + ``opencode auth login`` run once. The example
    spawns the server via ``ensure_opencode_server``.
  * ``voidcrawl-mcp`` on PATH (see opencode.json in this directory).

    uv run python examples/opencode_voidcrawl/reddit_ted_mcp.py
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
sys.path.insert(0, str(HERE.parent))  # examples/opencode_server.py

from opencode_server import ensure_opencode_server

OUT_DIR = HERE / '.yosoi' / 'reddit_mcp'
LISTING_URL = 'https://www.reddit.com/r/ted/top/?t=all'
TARGET_POSTS = 3


class RedditPost(ys.Contract):
    """Identical Contract to ``reddit_ted.py``; same semantic types.

    Under MCP discovery the rubric is much smaller — the agent learns by
    trying. Whether the Contract should pin a root or leave it for the agent
    to discover is the same decision as in the static case (left unset here).
    """

    title: str = ys.Title(description='Post title — the post card heading')
    author: str = ys.Author(description='Post author handle (e.g. "u/someone")')
    score: int | None = ys.Count(description='Post score / upvote count')
    comment_count: int | None = ys.Count(description='Number of comments on the post')
    permalink: str = ys.Url(description='Relative or absolute permalink URL to the post')


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # The discovery agent talks to OpenCode (which proxies the voidcrawl MCP).
    # Same OC_PROVIDER / OC_MODEL knobs as browse_and_save.py.
    async with ensure_opencode_server(cwd=str(HERE)):
        config = ys.opencode(
            extra_params={
                'provider_id': os.getenv('OC_PROVIDER', 'openai'),
                'model_id': os.getenv('OC_MODEL', 'gpt-5.4-mini'),
            }
        )

        pipeline = ys.Pipeline(
            config,
            contract=RedditPost,
            discovery_mode='mcp',  # ← the only difference vs. reddit_ted.py
        )

        async with HeadlessFetcher(no_sandbox=True, experimental_a3node=True) as fetcher:
            print(
                f'=== listing: r/ted top {TARGET_POSTS} (MCP discovery {config.extra_params}) ===',
                flush=True,
            )
            posts = [item async for item in pipeline.scrape(LISTING_URL, fetcher=fetcher)]
            posts = posts[:TARGET_POSTS]

        print('\n=== results ===', flush=True)
        for i, p in enumerate(posts, 1):
            print(
                f'  #{i} {p.get("score")} pts · {p.get("comment_count")} comments · '
                f'u/{p.get("author")} — {str(p.get("title", ""))[:80]!r}',
                flush=True,
            )

        out = OUT_DIR / 'top_posts.json'
        out.write_text(json.dumps(posts, indent=2), encoding='utf-8')
        print(f'\n  wrote {out}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
