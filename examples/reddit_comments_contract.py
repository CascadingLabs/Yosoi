"""Contract-first Reddit comments scrape.

Target:
    https://www.reddit.com/r/webscraping/comments/1tqajln/i_need_help/

A deliberately small, niche thread: the full DOM fits comfortably in the
discovery context, so we can validate the contract-first flow without fighting
infinite comment loading. Bounded/sliding-window discovery context is tracked
as future work (see Linear backlog), not used here.

This example intentionally starts from contracts only. There are no pinned
selectors in the contracts; Yosoi must learn the container and field selectors
from the page.

Provider selection is deliberately a comment/uncomment block so the same file
can be run through Claude Code SDK, OpenCode, or OpenRouter API.

Run:
    uv run python examples/reddit_comments_contract.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator

import yosoi as ys

sys.path.insert(0, str(Path(__file__).parent))
from opencode_server import ensure_opencode_server

load_dotenv()

URL = 'https://www.reddit.com/r/webscraping/comments/1tqajln/i_need_help/'
FETCHER_TYPE = os.getenv('YOSOI_REDDIT_FETCHER', 'headless')


# Comment/uncomment exactly one provider while iterating.
# MODEL = ys.claude_sdk(os.getenv('CLAUDE_SDK_MODEL', 'claude-sonnet-4-5'))
# MODEL = ys.opencode(os.getenv('OPENCODE_MODEL', 'openai/gpt-5-codex-mini'))
MODEL = ys.openrouter(os.getenv('OPENROUTER_MODEL', 'openai/gpt-5-mini'))


class RedditPost(ys.Contract):
    """Thread-level metadata from the post container."""

    post_id: str | None = ys.Field(
        default=None, description='Stable Reddit post id from the post element or canonical URL'
    )
    subreddit: str | None = ys.Field(default=None, description='Subreddit name, preferably the r/... prefixed value')
    author: str | None = ys.Author(default=None, description='Original poster username from the post header')
    title: str | None = ys.Title(default=None, description='Main Reddit post title')
    body: str | None = ys.BodyText(
        default=None, description='Original post body text, excluding comments and sidebar text'
    )
    score: int | None = ys.Field(default=None, description='Post score or upvote count as a non-negative integer')
    comment_count: int | None = ys.Field(default=None, description='Total comment count as a non-negative integer')

    @field_validator('score', 'comment_count', mode='before')
    @classmethod
    def _count_or_none(cls, value: object) -> int | None:
        return _count_or_none(value)


class RedditComment(ys.Contract):
    """One Reddit comment, scoped to a single ``shreddit-comment``."""

    comment_id: str | None = ys.Field(default=None, description='Stable Reddit comment id, often a t1_* thing id')
    parent_id: str | None = ys.Field(
        default=None, description='Parent thing id when available; null for top-level comments'
    )
    depth: int | None = ys.Field(default=None, description='Comment nesting depth as an integer')
    author: str | None = ys.Author(default=None, description='Comment author username')
    body: str | None = ys.BodyText(
        default=None,
        description='Comment body text only, excluding author, score, timestamp, buttons, and child comments',
    )
    score: int | None = ys.Field(default=None, description='Comment score or points as a non-negative integer')
    created_at: str | None = ys.Datetime(default=None, description='Comment creation timestamp or timeago datetime')
    permalink: str | None = ys.Url(default=None, description='Canonical permalink for this individual comment')

    @field_validator('depth', 'score', mode='before')
    @classmethod
    def _count_or_none(cls, value: object) -> int | None:
        return _count_or_none(value)


def _count_or_none(value: object) -> int | None:
    """Coerce Reddit-ish counters like ``1.2K`` and ``42 points``."""
    if value is None:
        return None
    raw = str(value).strip().replace(',', '')
    if not raw:
        return None

    match = re.search(r'(-?\d+(?:\.\d+)?)\s*([kKmMbB]?)', raw)
    if not match:
        return None

    number = float(match.group(1))
    suffix = match.group(2).lower()
    multiplier = {'': 1, 'k': 1_000, 'm': 1_000_000, 'b': 1_000_000_000}[suffix]
    return int(number * multiplier)


@asynccontextmanager
async def _provider_context() -> AsyncIterator[None]:
    """Start OpenCode only when the selected provider needs it."""
    if MODEL.provider == 'opencode':
        async with ensure_opencode_server():
            yield
        return
    yield


async def _scrape_contract(contract: type[ys.Contract]) -> list[ys.ContentMap]:
    async with ys.Pipeline(
        MODEL,
        contract=contract,
        output_format=['json'],
        selector_level=ys.SelectorLevel.CSS,
        discovery_mode='static',
        experimental_a3node=True,
    ) as pipeline:
        return [
            item
            async for item in pipeline.scrape(
                URL,
                force=False,
                skip_verification=False,
                fetcher_type=FETCHER_TYPE,
                output_format=['json'],
            )
        ]


async def main() -> None:
    async with _provider_context():
        post = await _scrape_contract(RedditPost)
        comments = await _scrape_contract(RedditComment)

    print(f'provider={MODEL.provider}:{MODEL.model_name}')
    print(f'post_items={len(post)} comment_items={len(comments)}')
    if post:
        print(f'title={post[0].get("title")}')
    for idx, comment in enumerate(comments[:5], 1):
        author = comment.get('author') or '?'
        body = str(comment.get('body') or '').replace('\n', ' ')[:120]
        print(f'{idx:02d}. {author}: {body}')


if __name__ == '__main__':
    asyncio.run(main())
