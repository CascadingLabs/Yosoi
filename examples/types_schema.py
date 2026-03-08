"""Examples of Yosoi semantic type aliases.

Three examples mirroring dynamic_schema.py but using ys.Price, ys.Title etc.
instead of raw Annotated[str, Field(...)] boilerplate:

1. E-commerce product page  — ys.Price, ys.Title, ys.Rating, ys.Url
2. Blog / news article       — ys.Title, ys.Author, ys.Datetime, ys.BodyText
3. Job listing               — ys.Title, ys.Url, with ys.Field(hint=...) overrides
"""

import os

from dotenv import load_dotenv
from pydantic import field_validator

import yosoi as ys

load_dotenv()

config = ys.LLMConfig(
    provider='groq',
    model_name='llama-3.3-70b-versatile',
    api_key=os.environ.get('GROQ_KEY', ''),
)


# ── Example 1: Product page ──────────────────────────────────────────────────
class Product(ys.Contract):
    """Scrape product data from books.toscrape.com using semantic type aliases."""

    title: ys.Title
    price: ys.Price = ys.Field(hint='Book price — always includes £ symbol')
    rating: ys.Rating = ys.Field(hint="Star rating written as a word e.g. 'Three'")
    url: ys.Url = ys.Field(hint='Canonical URL or href of this product listing')

    @field_validator('price', mode='before')
    @classmethod
    def coerce_price(cls, v: object) -> float:
        """Strip currency symbols and convert to float."""
        if isinstance(v, str):
            return float(v.replace('£', '').replace('$', '').strip())
        return float(v)  # type: ignore[arg-type]


def example_1_product():
    """Product contract using ys.Price, ys.Title, ys.Rating, ys.Url."""
    print('\n=== Example 1: Product (books.toscrape.com) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=Product)
    pipeline.process_url('https://books.toscrape.com')


# ── Example 2: Blog / news article ──────────────────────────────────────────
class BlogPost(ys.Contract):
    """Scrape a blog or news article using semantic type aliases."""

    headline: ys.Title
    author: ys.Author
    published: ys.Datetime
    body: ys.BodyText = ys.Field(hint='Main article body — exclude nav, ads, and sidebars')


def example_2_blog():
    """Blog contract using ys.Title, ys.Author, ys.Datetime, ys.BodyText."""
    print('\n=== Example 2: Blog post (quotes.toscrape.com) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=BlogPost)
    pipeline.process_url('https://quotes.toscrape.com')


# ── Example 3: Job listing with field hints ──────────────────────────────────
class JobListing(ys.Contract):
    """Scrape a job posting; all fields use ys.Field(hint=...) for AI guidance."""

    title: ys.Title = ys.Field(hint='Job title / position name in the main heading')
    company: ys.Author = ys.Field(hint='Hiring company name — often near the job title')
    location: str = ys.Field(hint='City, region, or "Remote" label')
    salary: ys.Price = ys.Field(hint='Annual or hourly salary; return 0.0 if not listed')
    apply_url: ys.Url = ys.Field(hint='Direct link to the application form or "Apply" button')


def example_3_job():
    """Job listing contract combining type aliases with ys.Field hints."""
    print('\n=== Example 3: Job listing (using type aliases + hints) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=JobListing)
    # Replace with a real job board URL to test
    pipeline.process_url('https://jobs.lever.co/anthropic')


if __name__ == '__main__':
    example_1_product()
    example_2_blog()
    example_3_job()
