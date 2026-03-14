"""Pydantic models for structured CSS selector data."""

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SelectorLevel(IntEnum):
    """Hierarchy of selector strategies from simplest to most complex."""

    CSS = 1
    XPATH = 2
    REGEX = 3
    JSONLD = 4

    # Convenience aliases
    CLEAN = 1
    STANDARD = 2
    ALL = 4


_STRATEGY_TO_LEVEL: dict[str, int] = {'css': 1, 'xpath': 2, 'regex': 3, 'jsonld': 4}


class SelectorEntry(BaseModel):
    """A single selector with its strategy and value.

    Attributes:
        strategy: Selector strategy type ('css', 'xpath', 'regex', 'jsonld')
        level: Numeric level derived from strategy (set automatically)
        value: The selector expression
        regex: Optional regex pattern (only used when strategy='regex')

    """

    strategy: Literal['css', 'xpath', 'regex', 'jsonld'] = 'css'
    level: SelectorLevel = SelectorLevel.CSS
    value: str
    regex: str | None = None

    @model_validator(mode='after')
    def _sync_level(self) -> 'SelectorEntry':
        """Sync level from strategy after validation."""
        self.level = SelectorLevel(_STRATEGY_TO_LEVEL[self.strategy])
        return self


class FieldSelectors(BaseModel):
    """Selectors for a single field with fallback options.

    Attributes:
        primary: Most specific selector (uses actual classes/IDs)
        fallback: Less specific but reliable selector
        tertiary: Generic selector or None if field doesn't exist

    """

    primary: SelectorEntry = Field(description='Most specific selector')
    fallback: SelectorEntry | None = Field(default=None, description='Less specific fallback')
    tertiary: SelectorEntry | None = Field(default=None, description='Generic selector or None')

    @field_validator('primary', mode='before')
    @classmethod
    def _coerce_primary(cls, v: object) -> object:
        """Coerce bare string to SelectorEntry."""
        if isinstance(v, str):
            return SelectorEntry(value=v)
        return v

    @field_validator('fallback', 'tertiary', mode='before')
    @classmethod
    def _coerce_optional(cls, v: object) -> object:
        """Coerce bare string to SelectorEntry for optional fields."""
        if isinstance(v, str):
            return SelectorEntry(value=v)
        return v

    @property
    def max_level(self) -> SelectorLevel:
        """Highest selector level present across all entries."""
        entries = [self.primary, self.fallback, self.tertiary]
        return max((e.level for e in entries if e is not None), default=SelectorLevel.CSS)

    def as_tuples(self) -> list[tuple[str, str | None]]:
        """Return selectors as (level_name, selector_value) tuples for backward compat."""
        return [
            ('primary', self.primary.value),
            ('fallback', self.fallback.value if self.fallback is not None else None),
            ('tertiary', self.tertiary.value if self.tertiary is not None else None),
        ]

    def as_entries(self) -> list[tuple[str, SelectorEntry | None]]:
        """Return selectors as (level_name, SelectorEntry) tuples for level-aware dispatch."""
        return [
            ('primary', self.primary),
            ('fallback', self.fallback),
            ('tertiary', self.tertiary),
        ]
