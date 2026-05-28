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
    ROLE = 5
    VISUAL = 6


# attr/global_id are DOM-level reads at the same complexity as CSS — they are
# alternative ways to *read* (vs. ::attr() pseudo-elements or document.getElementById),
# not escalations like xpath/regex/jsonld. Mapping them to level CSS keeps them
# allowed under the default `selector_level=CSS` gate.
_STRATEGY_TO_LEVEL: dict[str, int] = {
    'css': 1,
    'xpath': 2,
    'regex': 3,
    'jsonld': 4,
    'role': 5,
    'visual': 6,
    'attr': 1,
    'global_id': 1,
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
        type: Selector strategy — ``'css'``, ``'xpath'``, ``'regex'``, ``'jsonld'``,
            ``'role'`` (accessibility role+name), ``'visual'`` (pixel coords),
            ``'attr'`` (read an HTML attribute off the card itself), or ``'global_id'``
            (look up an element by an id template interpolated with another attr).
            Defaults to ``'css'``.
        value: For css/xpath/regex/jsonld the expression. For ``attr``, the attribute
            NAME to read (e.g. ``'post-title'``). For ``global_id``, the id TEMPLATE
            with ``{id}`` (or a custom marker matching ``identity``) interpolated
            from the card's identity attribute (e.g. ``'{id}-post-rtjson-content'``).
        regex: Optional regex capture pattern. Only used when ``type='regex'``.
        role: ARIA role, for ``type='role'`` (the AX-tree selector, CAS-27).
        name: Accessible name, for ``type='role'`` — exact for actions, optional for extraction.
        nth: Disambiguates duplicate role+name matches.
        x, y: CSS-pixel coordinates, for ``type='visual'``.
        identity: The card-side attribute that supplies the substitution for ``global_id``
            templates (defaults to ``'id'``). For reddit: ``identity='thingid'`` because
            ``shreddit-comment`` exposes ``thingid="..."`` rather than ``id="..."``.

    """

    model_config = ConfigDict(json_schema_extra=_strip_level)

    type: Literal['css', 'xpath', 'regex', 'jsonld', 'role', 'visual', 'attr', 'global_id'] = 'css'
    value: str = ''  # css/xpath/regex/jsonld expression; attr name; global_id template; empty for role/visual
    regex: str | None = None
    role: str | None = None
    name: str | None = None
    nth: int = 0
    x: float | None = None
    y: float | None = None
    identity: str = 'id'  # global_id only: the card-side attr supplying the {id} substitution

    @model_validator(mode='after')
    def _require_per_type(self) -> 'SelectorEntry':
        """Each strategy needs its own fields; keeps role/visual from masquerading as css."""
        if self.type in ('css', 'xpath', 'regex', 'jsonld', 'attr', 'global_id') and not self.value:
            raise ValueError(f'{self.type} selector requires a non-empty value')
        if self.type == 'role' and not self.role:
            raise ValueError("role selector requires 'role'")
        if self.type == 'visual' and (self.x is None or self.y is None):
            raise ValueError("visual selector requires 'x' and 'y'")
        if self.type == 'global_id' and '{' not in self.value:
            raise ValueError("global_id selector requires '{id}' (or a custom marker) in the template value")
        return self

    @property
    def level(self) -> SelectorLevel:
        """Selector strategy level derived from type."""
        return SelectorLevel(_STRATEGY_TO_LEVEL[self.type])

    def key(self) -> tuple[str, str, str, int]:
        """Identity for dedup — value alone is empty for role/visual, so include role/name/coords."""
        if self.type == 'role':
            return ('role', self.role or '', self.name or '', self.nth)
        if self.type == 'visual':
            return ('visual', f'{self.x},{self.y}', '', 0)
        if self.type == 'global_id':
            return ('global_id', self.value, self.identity, 0)
        return (self.type, self.value, '', 0)


def css(value: str) -> SelectorEntry:
    """Create a CSS SelectorEntry."""
    return SelectorEntry(type='css', value=value)


def role(role: str, name: str | None = None, nth: int = 0) -> SelectorEntry:
    """Create an accessibility role+name SelectorEntry (CAS-27).

    `name` is an exact accessible name for actions (click_by_role); leave it None
    for extraction, where the role alone locates the node within a card.
    """
    return SelectorEntry(type='role', role=role, name=name, nth=nth)


def visual(x: float, y: float) -> SelectorEntry:
    """Create a visual (CSS-pixel coordinate) SelectorEntry — the click escape hatch."""
    return SelectorEntry(type='visual', x=x, y=y)


def xpath(value: str) -> SelectorEntry:
    """Create an XPath SelectorEntry."""
    return SelectorEntry(type='xpath', value=value)


def regex(value: str) -> SelectorEntry:
    """Create a regex SelectorEntry."""
    return SelectorEntry(type='regex', value=value)


def jsonld(value: str) -> SelectorEntry:
    """Create a JSON-LD SelectorEntry."""
    return SelectorEntry(type='jsonld', value=value)


def attr(name: str) -> SelectorEntry:
    """Create an attribute SelectorEntry — read an HTML attribute off the card itself.

    Use when the value lives on the card element (a custom element exposing data as
    attributes), not in any descendant's text. e.g. reddit's ``<shreddit-post
    post-title="..." score="..." author="...">`` — every value is an attribute on
    the card; the extractor reads ``card.getAttribute(name)`` rather than running
    ``card.querySelector(...)``.
    """
    return SelectorEntry(type='attr', value=name)


def global_id(template: str, identity: str = 'id') -> SelectorEntry:
    """Create a global-id SelectorEntry — resolve an element by an id template.

    Use when the data node has a stable id keyed off the card's identity attr but
    lives OUTSIDE the card's subtree (e.g. slot reassignment grafts it into a
    sibling's light DOM). The template's ``{id}`` is replaced with the card's
    ``identity`` attribute, then ``document.getElementById(resolved)`` finds the node.

    Example (reddit lazy-loaded comment bodies):

        global_id('{id}-post-rtjson-content', identity='thingid')

    For a card with ``thingid="t1_abc"`` this resolves to ``document.getElementById(
    't1_abc-post-rtjson-content')`` — finding the body element grafted into the
    PARENT comment's light DOM.
    """
    return SelectorEntry(type='global_id', value=template, identity=identity)


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
