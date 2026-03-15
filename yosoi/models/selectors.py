"""Pydantic models for structured CSS selector data."""

from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SelectorLevel(IntEnum):
    """Hierarchy of selector strategies from simplest to most complex."""

    CSS = 1
    XPATH = 2
    REGEX = 3
    JSONLD = 4


_STRATEGY_TO_LEVEL: dict[str, int] = {'css': 1, 'xpath': 2, 'regex': 3, 'jsonld': 4}


def _strip_level(schema: dict[str, Any]) -> None:
    """Remove the internal ``level`` field from the JSON schema.

    ``level`` is an implementation detail synced from ``type`` — it should
    never appear in schemas sent to LLM providers (some, like Groq, reject
    schemas with unnecessary complexity).
    """
    props = schema.get('properties')
    if isinstance(props, dict):
        props.pop('level', None)
    defs = schema.get('$defs')
    if isinstance(defs, dict):
        defs.pop('SelectorLevel', None)


class SelectorEntry(BaseModel):
    """A single selector with its strategy and value.

    Attributes:
        type: Selector strategy type ('css', 'xpath', 'regex', 'jsonld')
        value: The selector expression
        regex: Optional regex pattern (only used when type='regex')

    """

    model_config = ConfigDict(json_schema_extra=_strip_level)

    type: Literal['css', 'xpath', 'regex', 'jsonld'] = 'css'
    level: SelectorLevel = Field(default=SelectorLevel.CSS, exclude=True)
    value: str
    regex: str | None = None

    @model_validator(mode='after')
    def _sync_level(self) -> 'SelectorEntry':
        """Sync level from type after validation."""
        self.level = SelectorLevel(_STRATEGY_TO_LEVEL[self.type])
        return self


def css(value: str) -> SelectorEntry:
    """Create a CSS SelectorEntry."""
    return SelectorEntry(type='css', value=value)


def xpath(value: str) -> SelectorEntry:
    """Create an XPath SelectorEntry."""
    return SelectorEntry(type='xpath', value=value)


def regex(value: str) -> SelectorEntry:
    """Create a regex SelectorEntry."""
    return SelectorEntry(type='regex', value=value)


def jsonld(value: str) -> SelectorEntry:
    """Create a JSON-LD SelectorEntry."""
    return SelectorEntry(type='jsonld', value=value)


def coerce_selector_entry(v: object) -> SelectorEntry | None:
    """Coerce a raw selector value (str, dict, or SelectorEntry) to SelectorEntry.

    Args:
        v: Raw value — None, SelectorEntry, dict, or str.

    Returns:
        A SelectorEntry instance or None if the value is empty/unrecognised.

    """
    if v is None:
        return None
    if isinstance(v, SelectorEntry):
        return v
    if isinstance(v, dict):
        return SelectorEntry.model_validate(v)
    if isinstance(v, str):
        return SelectorEntry(value=v) if v and v.upper() != 'NA' else None
    return None


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
        """Coerce bare string to SelectorEntry for optional fields; treat 'NA' as None."""
        if isinstance(v, str):
            if not v or v.upper() == 'NA':
                return None
            return SelectorEntry(value=v)
        return v

    @model_validator(mode='after')
    def _deduplicate(self) -> 'FieldSelectors':
        """Remove fallback/tertiary if their value duplicates any earlier level."""
        if self.fallback and self.fallback.value == self.primary.value:
            self.fallback = None
        if self.tertiary:
            seen = {self.primary.value}
            if self.fallback:
                seen.add(self.fallback.value)
            if self.tertiary.value in seen:
                self.tertiary = None
        return self

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
