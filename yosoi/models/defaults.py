"""Built-in default scraping schemas."""

from __future__ import annotations

from pydantic import Field

from yosoi import types as ys
from yosoi.models.contract import Contract


class NewsArticle(Contract):
    """Default contract matching the original 5-field behavior."""

    headline: str = ys.Title(description='Main article title (h1/h2 in article, NOT navigation)')
    author: str = ys.Author(description='Author name (author/byline classes or links)')
    date: str = ys.Datetime(description='Publication date (time tags or date/published classes)')
    body_text: str = ys.BodyText(description='Article paragraphs (p tags in article, NOT sidebars/ads)')
    related_content: str = Field(description='Related article links (aside/sidebar sections)')


class Video(Contract):
    """Contract for video pages (YouTube-style)."""

    title: str = ys.Title(description='Video title (h1 or main heading)')
    channel: str = ys.Author(description='Channel or creator name')
    duration: str = Field(description='Video duration (e.g. "10:32")')
    views: int | None = Field(description='View count')
    description: str = ys.BodyText(description='Video description text')
    upload_date: str = ys.Datetime(description='Upload or publish date')


class Product(Contract):
    """Contract for e-commerce product pages."""

    name: str = ys.Title(description='Product name or title')
    price: float | None = ys.Price(description='Product price (including currency symbol)')
    rating: float | str = ys.Rating(description='Star rating or review score')
    reviews_count: int | None = Field(description='Number of reviews or ratings')
    description: str = ys.BodyText(description='Product description or summary')
    availability: str = Field(description='Stock status (e.g. "In Stock", "Out of Stock")')


class JobPosting(Contract):
    """Contract for job listing pages."""

    title: str = ys.Title(description='Job title or position name')
    company: str = ys.Author(description='Hiring company name')
    location: str = Field(description='Job location (city, remote, etc.)')
    salary: float | None = ys.Price(description='Salary or compensation range')
    posted_date: str = ys.Datetime(description='Date the job was posted')
    description: str = ys.BodyText(description='Job description and requirements')


BUILTIN_SCHEMAS: dict[str, type[Contract]] = {
    'NewsArticle': NewsArticle,
    'Video': Video,
    'Product': Product,
    'JobPosting': JobPosting,
}
