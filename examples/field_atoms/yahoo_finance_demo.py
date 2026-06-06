"""LIVE Yahoo Finance, the Yosoi way — discover once in-context, replay across tickers.

You describe a stock quote in plain English. Yosoi renders the JS page, and an LLM
discovers the selectors IN CONTEXT — it reads the real rendered DOM, learns how to read
that page once, caches it, and replays across every other ticker. No hardcoded selectors,
no mocks: the only thing written by hand is the description of what a quote IS.

    uv run python examples/field_atoms/yahoo_finance_demo.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys


class Quote(ys.Contract):
    """A stock quote on a Yahoo Finance page."""

    name: str = ys.Field(description='the company name, e.g. Apple Inc.')
    price: str = ys.Field(description='the current share price, a number')


TICKERS = ['AAPL', 'MSFT', 'NVDA']
PAGES = [f'https://finance.yahoo.com/quote/{t}' for t in TICKERS]


async def main() -> None:
    # JS-rendered tier; the LLM discovers selectors on the first ticker and Yosoi replays
    # them on the rest — same template, one discovery.
    results = await ys.scrape(PAGES, Quote, model=ys.claude_sdk(), fetcher_type='headless')
    print()
    for url in PAGES:
        q = (results[url] or [{}])[0]
        print(f'  {q.get("name", "?"):<28} {q.get("price", "?")}')
    print('\n  Discovered once (in-context), replayed across every ticker — real Yahoo, real render.')


if __name__ == '__main__':
    asyncio.run(main())
