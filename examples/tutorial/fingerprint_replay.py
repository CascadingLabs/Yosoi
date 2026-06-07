"""Many different web pages, ONE fingerprint — discover once, replay across them all.

Yosoi knows a page by its STRUCTURE (a "page shape"), not its address. So pages built the
same — page 1, 2, 3 of a site, or one template across a dozen subdomains — share one
fingerprint, and Yosoi learns to read that shape ONCE, then replays it across every page.
(Yahoo Finance shows this best but is bot-walled; quotes.toscrape.com is the same idea.)

    uv run python examples/tutorial/fingerprint_replay.py
"""

import asyncio

import httpx

import yosoi as ys
from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import page_shape_fp


# Describe what you want.
class Quote(ys.Contract):
    """A quotation on the page."""

    text: str = ys.Field(description='the words of the quote')
    author: str = ys.Field(description='the person who said it')


# Five different URLs — all the same kind of page.
pages = [f'https://quotes.toscrape.com/page/{n}/' for n in range(1, 6)]


# 1. Every page collapses to the SAME fingerprint: Yosoi sees one shape, not five URLs.
def show_fingerprints() -> None:
    for url in pages:
        html = httpx.get(url, timeout=15).text
        print(f'{page_shape_fp(observe_html(url, html, row_selector=""))}   {url}')


# 2. One shape → one AI discovery → the rest are free replays. Here is the real data.
async def read_quotes() -> None:
    found = await ys.scrape(pages, Quote, model=ys.claude_sdk())
    for url in pages:
        quote = found[url][0]
        print(f'{quote["text"][:58]}… — {quote["author"]}')


show_fingerprints()
print()
asyncio.run(read_quotes())
