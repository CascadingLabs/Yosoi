"""Pydantic models for structured CSS selector data."""

from __future__ import annotations

import json
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
        ATTR: Attribute-addressed selector (level 5). Names the target attribute explicitly.
        GLOBAL_ID: ID-template selector (level 6). Resolves related nodes by shared ID tokens.
        ROLE: Accessibility-tree role/name selector (level 7). Stable target for rendered UIs.
        VISUAL: Coordinate/visual target (level 8). Degraded replay-only fallback.

    """

    CSS = 1
    XPATH = 2
    REGEX = 3
    JSONLD = 4
    ATTR = 5
    GLOBAL_ID = 6
    ROLE = 7
    VISUAL = 8


SelectorKind = Literal['css', 'xpath', 'regex', 'jsonld', 'attr', 'global_id', 'role', 'visual']

_STRATEGY_TO_LEVEL: dict[str, int] = {
    'css': 1,
    'xpath': 2,
    'regex': 3,
    'jsonld': 4,
    'attr': 5,
    'global_id': 6,
    'role': 7,
    'visual': 8,
}


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
        type: Selector strategy — ``'css'``, ``'xpath'``, ``'regex'``,
            ``'jsonld'``, ``'attr'``, ``'global_id'``, ``'role'``, or
            ``'visual'``. Defaults to ``'css'``.
        value: The selector expression, e.g. ``'h1.article-title'`` or ``'//h1'``.
        regex: Optional regex capture pattern. Only used when ``type='regex'``.
        name: Optional role accessible-name substring or attribute/global-id token.
        nth: Optional zero-based occurrence index for role/visual targets.
        x: Optional visual target x-coordinate.
        y: Optional visual target y-coordinate.

    """

    model_config = ConfigDict(json_schema_extra=_strip_level)

    type: SelectorKind = 'css'
    value: str = ''
    regex: str | None = None
    name: str | None = None
    nth: int | None = None
    x: float | None = None
    y: float | None = None

    @model_validator(mode='after')
    def _validate_payload(self) -> SelectorEntry:
        """Require enough payload to evaluate each selector kind."""
        if self.type == 'visual':
            if self.x is None or self.y is None:
                raise ValueError('visual selectors require x and y')
            return self

        if not self.value:
            raise ValueError(f'{self.type} selectors require value')

        if self.type in {'attr', 'global_id', 'role'} and not self.name:
            raise ValueError(f'{self.type} selectors require name')

        return self

    @property
    def level(self) -> SelectorLevel:
        """Selector strategy level derived from type."""
        return SelectorLevel(_STRATEGY_TO_LEVEL[self.type])

    def key(self) -> tuple[object, ...]:
        """Return a stable identity tuple for deduping action/extraction targets."""
        return (self.type, self.value, self.name, self.nth, self.x, self.y, self.regex)

    def text(self) -> Any:
        """Create a typed extractor plan returning text scoped to this selector."""
        from yosoi.types.field import extractor_plan_field

        return extractor_plan_field(self, operation='text')

    def attr(self, name: str) -> Any:
        """Create a typed extractor plan returning one attribute from matching nodes."""
        if not name:
            raise ValueError('extractor attribute name must not be empty')
        from yosoi.types.field import extractor_plan_field

        return extractor_plan_field(self, operation='attribute', attribute=name)


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


def attr(value: str, name: str) -> SelectorEntry:
    """Create an attribute-addressed SelectorEntry."""
    return SelectorEntry(type='attr', value=value, name=name)


def global_id(value: str, name: str) -> SelectorEntry:
    """Create an ID-template SelectorEntry."""
    return SelectorEntry(type='global_id', value=value, name=name)


def role(value: str, name: str, nth: int = 0) -> SelectorEntry:
    """Create an accessibility-tree role/name SelectorEntry."""
    return SelectorEntry(type='role', value=value, name=name, nth=nth)


def visual(x: float, y: float, value: str = '') -> SelectorEntry:
    """Create a degraded visual target SelectorEntry."""
    return SelectorEntry(type='visual', value=value, x=x, y=y)


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
        if not v or v.upper() == 'NA':
            return None
        stripped = v.strip()
        if stripped.startswith('{'):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(parsed, dict):
                    return SelectorEntry.model_validate(parsed)
        return SelectorEntry(value=v)
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
    root: SelectorEntry | None = Field(
        default=None,
        description=(
            'Optional PARENT scope this field resolves under. When set, primary/fallback/'
            'tertiary are evaluated RELATIVE to the element matched by root — pinning the '
            'field to one region of the page (e.g. a sponsored ad block vs the organic '
            'results list) so the leaf selector can stay simple and sturdy.'
        ),
    )

    @field_validator('primary', mode='before')
    @classmethod
    def _coerce_primary(cls, v: object) -> object:
        """Coerce bare/JSON selector strings to SelectorEntry; keep primary 'NA' sentinel valid."""
        if isinstance(v, str):
            if v.upper() == 'NA':
                return SelectorEntry(value='NA')
            return coerce_selector_entry(v) or v
        return v

    @field_validator('fallback', 'tertiary', 'root', mode='before')
    @classmethod
    def _coerce_optional(cls, v: object) -> object:
        """Coerce bare/JSON selector strings to SelectorEntry; treat 'NA' as None."""
        if isinstance(v, str):
            return coerce_selector_entry(v)
        return v

    @model_validator(mode='after')
    def _deduplicate(self) -> FieldSelectors:
        """Remove fallback/tertiary if their value duplicates any earlier level."""
        if self.fallback and self.fallback.key() == self.primary.key():
            self.fallback = None
        if self.tertiary:
            seen = {self.primary.key()}
            if self.fallback:
                seen.add(self.fallback.key())
            if self.tertiary.key() in seen:
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
