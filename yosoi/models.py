"""Pydantic models for structured CSS selector data."""

from typing import Literal

from pydantic import BaseModel, Field


class SelectorFailure(BaseModel):
    """Details about why a single selector failed.

    Attributes:
        level: Which selector level ('primary', 'fallback', 'tertiary')
        selector: The CSS selector that was attempted
        reason: Why the selector failed (e.g., 'no_elements_found', 'invalid_syntax', 'na_selector')

    """

    level: str = Field(description='Selector level (primary/fallback/tertiary)')
    selector: str = Field(description='The CSS selector attempted')
    reason: str = Field(description='Why the selector failed')


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


class FieldVerificationResult(BaseModel):
    """Result of verifying a single field's selectors.

    Attributes:
        field_name: Name of the field being verified
        status: Whether verification succeeded or failed
        working_level: Which selector level worked ('primary', 'fallback', 'tertiary'), or None if all failed
        selector: The actual selector string that worked, if any
        failed_selectors: List of selectors that failed with reasons

    """

    # TODO working_level should be a list, or a global matrix maybe of working selectors?? How good can we make the verifiers w/o llms or HITL

    field_name: str = Field(description='Name of the field')
    status: Literal['verified', 'failed'] = Field(description='Verification status')
    working_level: str | None = Field(default=None, description='Which level worked')
    selector: str | None = Field(default=None, description='Selector that worked')
    failed_selectors: list[SelectorFailure] = Field(default_factory=list, description='Failed selectors with reasons')


class VerificationResult(BaseModel):
    """Complete verification result for all fields.

    Attributes:
        total_fields: Total number of fields that were checked
        verified_count: Number of fields that passed verification
        results: Per-field verification results keyed by field name

    """

    total_fields: int = Field(description='Total fields checked')
    verified_count: int = Field(description='Fields that passed')
    results: dict[str, FieldVerificationResult] = Field(default_factory=dict, description='Per-field results')

    @property
    def success(self) -> bool:
        """True if at least one field verified successfully."""
        return self.verified_count >= 1

    @property
    def verified_fields(self) -> list[str]:
        """Names of fields that passed verification."""
        return [name for name, result in self.results.items() if result.status == 'verified']


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
