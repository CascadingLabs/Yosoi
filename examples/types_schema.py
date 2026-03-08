"""Examples of Yosoi semantic type factories.

Three examples using the field-right pattern:

    price: float = ys.Price()
    title: str = ys.Title()

Plain Python type on the left, Yosoi factory on the right.

1. E-commerce product page  — ys.Price, ys.Title, ys.Rating, ys.Url
2. Blog / news article       — ys.Title, ys.Author, ys.Datetime, ys.BodyText
3. Job listing               — ys.Title, ys.Url, with ys.Field(hint=...) overrides
"""

import os

from dotenv import load_dotenv

import yosoi as ys

load_dotenv()

# Pick whichever key is available; Cerebras is tried first.
# config = ys.groq('llama-3.1-8b-instant', os.environ['GROQ_KEY'])
config = ys.openrouter('llama-3.3-70b-versatile:free', os.environ['OPENROUTER_KEY'])


# -- Example 1: Product page -------------------------------------------------
class Product(ys.Contract):
    """Scrape product data from books.toscrape.com using semantic type factories."""

    title: str = ys.Title()
    price: float = ys.Price(hint='Book price — always includes £ symbol')
    rating: str = ys.Rating(hint="Star rating written as a word e.g. 'Three'")
    url: str = ys.Url(hint='Canonical URL or href of this product listing')


def example_1_product():
    """Product contract using ys.Price, ys.Title, ys.Rating, ys.Url."""
    print('\n=== Example 1: Product (books.toscrape.com) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=Product)
    pipeline.process_url('https://books.toscrape.com')


# -- Example 2: Blog / news article ------------------------------------------
class BlogPost(ys.Contract):
    """Scrape a blog or news article using semantic type factories."""

    headline: str = ys.Title()
    author: str = ys.Author()
    published: str = ys.Datetime()
    body: str = ys.BodyText(hint='Main article body — exclude nav, ads, and sidebars')


def example_2_blog():
    """Blog contract using ys.Title, ys.Author, ys.Datetime, ys.BodyText."""
    print('\n=== Example 2: Blog post (quotes.toscrape.com) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=BlogPost)
    pipeline.process_url('https://quotes.toscrape.com')


# -- Example 3: Job listing with field hints ----------------------------------
class JobListing(ys.Contract):
    """Scrape a job posting; all fields use hint=... for AI guidance."""

    title: str = ys.Title(hint='Job title / position name in the main heading')
    company: str = ys.Author(hint='Hiring company name — often near the job title')
    location: str = ys.Field(hint='City, region, or "Remote" label')
    salary: float = ys.Price(hint='Annual or hourly salary; return 0.0 if not listed')
    apply_url: str = ys.Url(hint='Direct link to the application form or "Apply" button')


def example_3_job():
    """Job listing contract combining type factories with hints."""
    print('\n=== Example 3: Job listing (using type factories + hints) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=JobListing)
    # Replace with a real job board URL to test
    pipeline.process_url('https://jobs.lever.co/anthropic')


if __name__ == '__main__':
    example_1_product()
    example_2_blog()
    example_3_job()
