"""Pydantic models for fetch and verification results."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


@dataclass
class ContentMetadata:
    """Metadata about the fetched content.

    Attributes:
        is_rss: True if the URL is rss
        requires_js: True if the URL has JS
        js_framework: If has JS, what type
        content_length: Length of the HTML

    """

    is_rss: bool = False
    requires_js: bool = False
    content_type: str = 'html'
    js_framework: str | None = None
    content_length: int = 0


@dataclass
class FetchResult:
    """Result of an HTML fetch operation.

    Attributes:
        url: URL from which the HTML is grabbed
        html: HTML content grabbed from the URL
        status_code: The website code when fetching the URL
        is_blocked: True if the URL is blocked for some reason
        block_reason: For what reason the URL is blocked
        fetch_time: Total time for the HTML to be fetched

    """

    url: str
    html: str | None = None
    status_code: int | None = None
    is_blocked: bool = False
    block_reason: str | None = None
    fetch_time: float = 0.0

    # Content metadata
    metadata: ContentMetadata = field(default_factory=ContentMetadata)

    @property
    def success(self) -> bool:
        """Whether the fetch was successful.

        Returns:
            True if the HTML was successfully fetched

        """
        return self.html is not None and not self.is_blocked

    @property
    def is_rss(self) -> bool:
        """Shortcut to check if content is RSS.

        Returns:
            True if the URL is RSS

        """
        return self.metadata.is_rss

    @property
    def requires_js(self) -> bool:
        """Shortcut to check if content requires JavaScript.

        Returns:
            True if the HTML has JS

        """
        return self.metadata.requires_js

    @property
    def should_use_heuristics(self) -> bool:
        """Whether we should skip AI and use heuristics.

        Returns:
            True if the URL is RSS or has JS, then use the heuristics

        """
        return self.is_rss or self.requires_js


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


class FieldVerificationResult(BaseModel):
    """Result of verifying a single field's selectors.

    Attributes:
        field_name: Name of the field being verified
        status: Whether verification succeeded or failed
        working_level: Which selector level worked ('primary', 'fallback', 'tertiary'), or None if all failed
        selector: The actual selector string that worked, if any
        failed_selectors: List of selectors that failed with reasons

    """

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
