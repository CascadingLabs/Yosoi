"""reddit r/ted top posts — Contract-only smoke test. ONE page, no navigation.

Scope is deliberately small: prove the discover → cache → replay loop works
end-to-end against the listing page before adding per-post comment expansion.

  * **selectors** — LLM discovery against the rendered HTML (Pipeline.scrape).
    Reddit's listing data lives on `<shreddit-post>` attributes — the LLM is
    expected to emit `attr('post-title')`, `attr('score')`, `attr('author')`,
    `attr('comment-count')`, `attr('permalink')` via the new SelectorEntry
    kinds. First run discovers, every later run replays the cached snapshot.
  * **action plan** — the fetcher's `prepare_page` hook hands the trimmed
    rendered HTML (~7 KB instead of ~340 KB) to the action-plan agent.

LLM transport: OpenRouter, GPT 5.4 mini (small + fast). Set
``OPENROUTER_API_KEY`` (or ``OPENROUTER_KEY``) in your environment. Override
the model via ``YOSOI_MODEL`` env if you want a different one.

What's NOT in this file:
  * No `css('shreddit-post')`, no `faceplate-partial[src*=more-comments]`.
  * No `ReplayPlan`, no `A3Node`, no `ExtractRecipe`, no `ExtractField.config`.
  * No per-post navigation — added back once the listing path is verified live.

    uv run python examples/opencode_voidcrawl/reddit_ted.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import yosoi as ys
from yosoi.core.fetcher.voiddriver import HeadlessFetcher

HERE = Path(__file__).parent
OUT_DIR = HERE / '.yosoi' / 'reddit'
LISTING_URL = 'https://www.reddit.com/r/ted/top/?t=all'  # sort baked into the URL
TARGET_POSTS = 3
DEFAULT_MODEL = 'openai/gpt-5.4-mini'  # small + fast; override via YOSOI_MODEL env


class RedditPost(ys.Contract):
    """One post card on a subreddit listing — multi-item via auto-discovered root.

    Pure semantic types. The LLM discovery agent picks the selectors for THIS
    site: reddit's data lives on `<shreddit-post>` attributes, so the agent is
    expected to emit `attr('post-title')` / `attr('score')` / etc. `root` is
    left unset; the agent finds the repeating card automatically.
    """

    title: str = ys.Title(description='Post title — the post card heading')
    author: str = ys.Author(description='Post author handle (e.g. "u/someone")')
    score: int | None = ys.Count(description='Post score / upvote count')
    comment_count: int | None = ys.Count(description='Number of comments on the post')
    permalink: str = ys.Url(description='Relative or absolute permalink URL to the post')


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # OpenRouter + GPT 5.4 mini is small + fast and avoids the per-run cost of
    # spawning the OpenCode server. Auth: OPENROUTER_API_KEY (or OPENROUTER_KEY)
    # in the env; the helper picks it up automatically.
    model_name = os.getenv('YOSOI_MODEL', DEFAULT_MODEL)
    config = ys.openrouter(model_name)

    listing = ys.Pipeline(config, contract=RedditPost)

    async with HeadlessFetcher(no_sandbox=True, experimental_a3node=True) as fetcher:
        print(f'=== listing: r/ted top (all time) (openrouter {model_name}) ===', flush=True)
        posts = [item async for item in listing.scrape(LISTING_URL, fetcher=fetcher)]
        posts = posts[:TARGET_POSTS]

    print('\n=== results ===', flush=True)
    for i, p in enumerate(posts, 1):
        print(
            f'  #{i} {p.get("score")} pts · {p.get("comment_count")} comments · '
            f'u/{p.get("author")} — {str(p.get("title", ""))[:80]!r}',
            flush=True,
        )
        link = p.get('permalink')
        if link:
            print(f'        permalink={link}', flush=True)

    out = OUT_DIR / 'top_posts.json'
    out.write_text(json.dumps(posts, indent=2), encoding='utf-8')
    print(f'\n  wrote {out}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
