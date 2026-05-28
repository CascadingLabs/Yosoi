"""reddit comments — Contract-only smoke test, closes the listing+comments story.

Counterpoint to ``reddit_ted.py`` (the listing): this targets ONE post's
permalink and extracts every public comment. Two things this proves that the
listing didn't:

  * **``global_id`` selector fires end-to-end.** Reddit's lazy-loaded comment
    bodies are grafted into a sibling's light DOM via slot reassignment —
    ``<shreddit-comment thingid="t1_abc">`` doesn't contain its own body;
    ``<div id="t1_abc-post-rtjson-content">`` lives elsewhere in the document.
    A scoped CSS query inside the card misses it. The clean answer is
    ``global_id('{id}-post-rtjson-content', identity='thingid')`` — the
    selector kind we added in Phase A but never exercised on a live target.
  * **Action plan agent on `click_until`.** The listing used scroll-based
    infinite pagination. Comments use `<faceplate-partial src=more-comments>`
    custom-element click triggers — a different action shape. The
    ActionPlanDiscoveryAgent has to emit a `click_until` over the trigger
    family with `selector_absent` termination (the structural-done assertion
    that doesn't trip on skeleton placeholders).

URL is a known post (the #1 top all-time from r/ted) so we have a stable
ground truth: the listing already told us the post has 10 comments. If we
extract ~10 comments with all three fields populated, the loop works.

    uv run python examples/opencode_voidcrawl/reddit_comments.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import yosoi as ys
from yosoi.core.fetcher.voiddriver import HeadlessFetcher

HERE = Path(__file__).parent
OUT_DIR = HERE / '.yosoi' / 'reddit_comments'
# A stable r/ted top-all-time post — pinned so the smoke test has known ground
# truth (10 comments per the listing run on 2026-05-28). Override via env if
# you want to point at a different post.
POST_URL = os.getenv(
    'REDDIT_POST_URL',
    'https://www.reddit.com/r/ted/comments/f1y61t/facebook_deleted_15m_hate_speech_posts_18m_pieces/',
)
DEFAULT_MODEL = 'openai/gpt-5.4-mini'  # same as reddit_ted.py for parity


class RedditComment(ys.Contract):
    """One public comment on a reddit post — multi-item, body via global_id.

    The body field is the focal point. `author` and `score` live on the
    `<shreddit-comment>` opening tag as attributes (RULE 1 — `attr`), but
    `body` lives OUTSIDE the comment's own subtree (RULE 2 — `global_id`).
    The system should figure both out from the cleaned HTML, without any
    site-specific hints in this file.
    """

    author: str = ys.Author(description='Comment author handle (e.g. "u/someone")')
    score: int | None = ys.Count(description='Comment score / upvote count')
    body: str = ys.BodyText(description='Comment body — the visible comment paragraph(s)')


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model_name = os.getenv('YOSOI_MODEL', DEFAULT_MODEL)
    config = ys.openrouter(model_name)

    pipeline = ys.Pipeline(config, contract=RedditComment)

    async with HeadlessFetcher(no_sandbox=True, experimental_a3node=True) as fetcher:
        print(f'=== reddit comments (openrouter {model_name}) ===', flush=True)
        print(f'    target: {POST_URL}', flush=True)
        comments = [item async for item in pipeline.scrape(POST_URL, fetcher=fetcher)]

    print(f'\n=== results ({len(comments)} comments) ===', flush=True)
    bodies_present = sum(1 for c in comments if c.get('body'))
    print(f'  bodies populated: {bodies_present}/{len(comments)}', flush=True)
    for i, c in enumerate(comments[:5], 1):
        preview = str(c.get('body') or '').replace('\n', ' ')[:90]
        print(
            f'  #{i} u/{c.get("author")} · {c.get("score")} pts — {preview!r}',
            flush=True,
        )
    if len(comments) > 5:
        print(f'  ... + {len(comments) - 5} more', flush=True)

    out = OUT_DIR / 'comments.json'
    out.write_text(json.dumps(comments, indent=2), encoding='utf-8')
    print(f'\n  wrote {out}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
