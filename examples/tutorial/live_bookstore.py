"""Read real web pages and pull out the facts you want — in a few plain lines.

You describe a "book" in words. You list some real pages. Yosoi reads them and hands
you clean data. It figures out HOW to read a page once (with AI), then remembers — so
the same few lines work for five pages or five million.

Run it:
    uv run python examples/tutorial/live_bookstore.py
"""

import asyncio

import yosoi as ys


# 1) Describe what you want, in plain English.
class Book(ys.Contract):
    """A book for sale."""

    title: str = ys.Title(description='the name of the book')
    price: str = ys.Field(description='how much it costs, like £51.77')
    in_stock: str = ys.Field(description='whether it is in stock')


# 2) List some real web pages.
pages = [
    'https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html',
    'https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html',
    'https://books.toscrape.com/catalogue/soumission_998/index.html',
    'https://books.toscrape.com/catalogue/sharp-objects_997/index.html',
    'https://books.toscrape.com/catalogue/sapiens-a-brief-history-of-humankind_996/index.html',
]


# 3) Ask Yosoi to read them, then print what it found.
async def main():
    books = await ys.scrape(pages, Book, model=ys.claude_sdk())
    for page in pages:
        book = books[page][0]
        print(f'{book["title"]} — {book["price"]} — {book["in_stock"]}')


asyncio.run(main())
