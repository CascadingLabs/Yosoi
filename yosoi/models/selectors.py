"""Pydantic models for structured CSS selector data."""

from pydantic import BaseModel, Field


class FieldSelectors(BaseModel):
    """Selectors for a single field with fallback options.

    Attributes:
        primary: Most specific selector (uses actual classes/IDs)
        fallback: Less specific but reliable selector
        tertiary: Generic selector or None if field doesn't exist

    """

    primary: str = Field(description='Most specific selector')
    fallback: str | None = Field(default=None, description='Less specific fallback')
    tertiary: str | None = Field(default=None, description='Generic selector or None')

    def as_tuples(self) -> list[tuple[str, str | None]]:
        """Return selectors as list of (level, selector) tuples."""
        return [
            ('primary', self.primary),
            ('fallback', self.fallback),
            ('tertiary', self.tertiary),
        ]


class ScrapingConfig(BaseModel):
    """Complete set of selectors for web scraping.

    Attributes:
        headline: Selectors for main article title
        author: Selectors for author name/byline
        date: Selectors for publication date
        body_text: Selectors for article paragraphs
        related_content: Selectors for related article links

    """

    headline: FieldSelectors
    author: FieldSelectors
    date: FieldSelectors
    body_text: FieldSelectors
    related_content: FieldSelectors
