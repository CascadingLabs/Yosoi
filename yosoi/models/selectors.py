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
