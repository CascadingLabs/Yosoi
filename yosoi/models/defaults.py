"""Built-in default scraping schemas."""

from __future__ import annotations

from pydantic import Field

from yosoi.models.contract import Contract


class NewsArticle(Contract):
    """Default contract matching the original 5-field behavior."""

    headline: str = Field(description='Main article title (h1/h2 in article, NOT navigation)')
    author: str = Field(description='Author name (author/byline classes or links)')
    date: str = Field(description='Publication date (time tags or date/published classes)')
    body_text: str = Field(description='Article paragraphs (p tags in article, NOT sidebars/ads)')
    related_content: str = Field(description='Related article links (aside/sidebar sections)')


class Video(Contract):
    """Contract for video pages (YouTube-style)."""

    title: str = Field(description='Video title (h1 or main heading)')
    channel: str = Field(description='Channel or creator name')
    duration: str = Field(description='Video duration (e.g. "10:32")')
    views: str = Field(description='View count')
    description: str = Field(description='Video description text')
    upload_date: str = Field(description='Upload or publish date')


class Product(Contract):
    """Contract for e-commerce product pages."""

    name: str = Field(description='Product name or title')
    price: str = Field(description='Product price (including currency symbol)')
    rating: str = Field(description='Star rating or review score')
    reviews_count: str = Field(description='Number of reviews or ratings')
    description: str = Field(description='Product description or summary')
    availability: str = Field(description='Stock status (e.g. "In Stock", "Out of Stock")')


class JobPosting(Contract):
    """Contract for job listing pages."""

    title: str = Field(description='Job title or position name')
    company: str = Field(description='Hiring company name')
    location: str = Field(description='Job location (city, remote, etc.)')
    salary: str = Field(description='Salary or compensation range')
    posted_date: str = Field(description='Date the job was posted')
    description: str = Field(description='Job description and requirements')


BUILTIN_SCHEMAS: dict[str, type[Contract]] = {
    'NewsArticle': NewsArticle,
    'Video': Video,
    'Product': Product,
    'JobPosting': JobPosting,
}
