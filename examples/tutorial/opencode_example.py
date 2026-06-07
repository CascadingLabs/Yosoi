"""Drive a Yosoi scrape through OpenCode using a Codex subscription.

The ``opencode`` provider points at Codex through OpenCode, so calls bill
against your ChatGPT/Codex subscription.

Setup (one-time):
    opencode auth login            # choose OpenAI / Codex, complete OAuth

Run:
    uv run python examples/tutorial/opencode_example.py

By default this spawns its own `opencode serve` on an ephemeral port (see
opencode_server.py) — no manual server, no OPENCODE_BASE_URL needed. To
attach to an already-running server instead, set OPENCODE_BASE_URL.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from opencode_server import ensure_opencode_server
from pydantic import field_validator

import yosoi as ys

load_dotenv()


class Book(ys.Contract):
    """Scrape book data from books.toscrape.com."""

    title: str = ys.Title()
    price: float = ys.Price(description='Book price — always includes £ symbol')
    # books.toscrape encodes the rating in the element's class, so discovery
    # picks `p.star-rating::attr(class)` and extraction yields the raw class
    # string e.g. "star-rating Three". CSS can't sub-select one class token,
    # so we shape the value here — extraction's job is the attribute, the
    # contract's job is the meaning.
    rating: str = ys.Rating(description='Star rating, expressed as a word (e.g. "Three")')

    @field_validator('rating', mode='after')
    @classmethod
    def _word_from_class(cls, value: str) -> str:
        return value.replace('star-rating', '').strip() or value


async def _run() -> None:
    model = os.getenv('OPENCODE_MODEL', 'openai/gpt-5.3-codex')
    items = await ys.scrape(
        'https://books.toscrape.com',
        Book,
        model=ys.opencode(model),
        save_formats=('json',),
        quiet=False,
    )
    print(items[:1])


async def main() -> None:
    # Uses an existing OPENCODE_BASE_URL when present; otherwise it spawns and
    # owns an ephemeral OpenCode server for this run.
    async with ensure_opencode_server():
        await _run()


if __name__ == '__main__':
    asyncio.run(main())
