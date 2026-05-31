"""Drive a Yosoi scrape through the packaged Claude Agent SDK transport.

The ``claude-sdk`` provider uses your Claude CLI subscription instead of a
per-token Anthropic API key.

Run:
    uv run python examples/claude_sdk_example.py
"""

from __future__ import annotations

import asyncio

from pydantic import field_validator

import yosoi as ys


class Book(ys.Contract):
    """Scrape book data from books.toscrape.com."""

    title: str = ys.Title()
    price: float = ys.Price(description='Book price — always includes £ symbol')
    # Rating is encoded in the element's class (e.g. "star-rating Three") —
    # discovery picks `::attr(class)`, then we shape the value to the word.
    rating: str = ys.Rating(description="Star rating in the element's class attribute, e.g. class='star-rating Three'")

    @field_validator('rating', mode='after')
    @classmethod
    def _word_from_class(cls, value: str) -> str:
        return value.replace('star-rating', '').strip() or value


async def main() -> None:
    items = await ys.scrape(
        'https://books.toscrape.com',
        Book,
        model=ys.claude_sdk('claude-opus-4-7'),
        save_formats=('json',),
        quiet=False,
    )
    print(items[:1])


if __name__ == '__main__':
    asyncio.run(main())
