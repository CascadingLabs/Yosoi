"""LIVE Yahoo Finance, the Yosoi way — discover once in-context, replay across tickers.

You describe a stock quote in plain English. Yosoi renders the JS page, and an LLM
discovers the selectors IN CONTEXT on the FIRST ticker — it reads the real rendered DOM,
learns how to read that page once, caches it, and replays across every other ticker with
ZERO further LLM calls. No hardcoded selectors, no mocks.

(Done in two steps — learn one, replay the rest — so the discovery can't race itself; one
concurrent ``scrape`` of all tickers from cold could discover several times before the
cache warms.)

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
    # 1. Teach Yosoi ONCE — the LLM discovers selectors in-context on the first ticker.
    learned = await ys.scrape(PAGES[0], Quote, model=ys.claude_sdk(), fetcher_type='headless')
    # 2. Replay across every other ticker — same template, zero further LLM discovery.
    replayed = await ys.scrape(PAGES[1:], Quote, model=ys.claude_sdk(), fetcher_type='headless')

    print()
    q0 = (learned or [{}])[0]
    print(f'  {q0.get("name", "?"):<26} {q0.get("price", "?"):>8}   (discovered)')
    for url in PAGES[1:]:
        q = (replayed[url] or [{}])[0]
        print(f'  {q.get("name", "?"):<26} {q.get("price", "?"):>8}   (replayed — 0 LLM)')
    print('\n  One in-context discovery, replayed across every ticker. Real Yahoo, real render.')


if __name__ == '__main__':
    asyncio.run(main())
