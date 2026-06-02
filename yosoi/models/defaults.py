"""Built-in default scraping schemas."""

from __future__ import annotations

from pydantic import Field

from yosoi import types as ys
from yosoi.models.contract import Contract


class NewsArticle(Contract):
    """Default contract matching the original 5-field behavior."""

    headline: str = ys.Title(description='The main headline of the article')
    author: str = ys.Author(description='The name of the article author or byline')
    date: str = ys.Datetime(description='The publication date of the article')
    body_text: str = ys.BodyText(description='The main body text of the article')
    related_content: str = ys.RelatedContent(description='Links to related or recommended articles')


class Video(Contract):
    """Contract for video pages (YouTube-style)."""

    title: str = ys.Title(description='The title of the video')
    channel: str = ys.Author(description='Channel or creator name')
    duration: str = Field(description='Video duration (e.g. "10:32")')
    views: int | None = Field(description='View count')
    description: str = ys.BodyText(description='Video description text')
    upload_date: str = ys.Datetime(description='Upload or publish date')


class Product(Contract):
    """Contract for e-commerce product pages."""

    name: str = ys.Title(description='Product name or title')
    price: float | None = ys.Price(description='Product price (including currency symbol)')
    rating: float | None = ys.Rating(as_float=True, description='Star rating or review score (numeric, e.g. 4.2)')
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
