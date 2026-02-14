"""Pydantic models for structured CSS selector data."""

from pydantic import BaseModel, Field


class FieldSelectors(BaseModel):
    """Selectors for a single field with fallback options.

    Attributes:
        primary: Most specific selector (uses actual classes/IDs)
        fallback: Less specific but reliable selector
        tertiary: Generic selector or 'NA' if field doesn't exist

    """

    primary: str = Field(description='Most specific selector')
    fallback: str = Field(description='Less specific fallback')
    tertiary: str = Field(description="Generic selector or 'NA'")


# TODO Make this a dynamic class. Perhaps include a way for users to define via pydantic models?
# >> Maybe we make a custom pydantic model that can be used to define what is being scraped?
# >> This might look like YosoiContent(BaseModel):
# >>     url: str FieldSelectors
# >>     date: DATETIME FieldSelector
# >>     body_text: str
# >>     related_content: str
# >> And then we can use this to generate the ScrapingConfig dynamically?


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
