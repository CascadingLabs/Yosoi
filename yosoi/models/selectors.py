"""Pydantic models for structured CSS selector data."""

from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SelectorLevel(IntEnum):
    """Hierarchy of selector strategies from simplest to most complex.

    Yosoi tries selectors in ascending level order. CSS is the default and
    covers most sites. Escalation to higher levels only happens when lower
    strategies fail inline verification.

    Attributes:
        CSS: Standard CSS selector (level 1). Preferred for speed and readability.
        XPATH: XPath expression (level 2). Used when CSS cannot express the required traversal.
        REGEX: Raw regex against page HTML (level 3). Last resort for unstructured content.
        JSONLD: JSON-LD path (level 4). Extracts from embedded structured data.

    """

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
    """A single selector with its strategy type and value.

    Represents one concrete selector that Yosoi can evaluate against a page.
    Each entry carries the strategy (CSS, XPath, etc.) alongside the expression
    string. Bare strings default to CSS selectors.

    Attributes:
        type: Selector strategy — ``'css'``, ``'xpath'``, ``'regex'``, or ``'jsonld'``. Defaults to ``'css'``.
        value: The selector expression, e.g. ``'h1.article-title'`` or ``'//h1'``.
        regex: Optional regex capture pattern. Only used when ``type='regex'``.

    """

    model_config = ConfigDict(json_schema_extra=_strip_level)

    type: Literal['css', 'xpath', 'regex', 'jsonld'] = 'css'
    value: str
    regex: str | None = None

    @property
    def level(self) -> SelectorLevel:
        """Selector strategy level derived from type."""
        return SelectorLevel(_STRATEGY_TO_LEVEL[self.type])


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


_DISCOVER_SENTINEL = 'yosoi:discover'


def discover() -> SelectorEntry:
    """Sentinel: AI will discover the root for this scoped nested contract."""
    return SelectorEntry(type='css', value=_DISCOVER_SENTINEL)


def is_discover_sentinel(entry: SelectorEntry | None) -> bool:
    """Return True if *entry* is the discover sentinel."""
    return entry is not None and entry.value == _DISCOVER_SENTINEL


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
    """Container for primary, fallback, and tertiary selectors for a single contract field.

    During extraction Yosoi tries the primary selector first. If it returns no
    elements the fallback is tried, then the tertiary. Bare strings passed to
    any slot are automatically coerced to ``SelectorEntry`` instances, and
    duplicate values across slots are deduplicated.

    Attributes:
        primary: Most specific selector — uses actual classes/IDs found on the page.
        fallback: Less specific but reliable alternative if the primary breaks.
        tertiary: Generic last-resort selector, or ``None`` if the field cannot be matched.

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
