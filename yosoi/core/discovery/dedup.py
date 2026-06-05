"""Soft duplicate-selector diagnostics — a smell, never fail-fast.

Two distinct fields (or two contracts on the same page) that resolve to the IDENTICAL
selector are a signal: either the contract intent is too weak to tell them apart, or the
model conflated them. We WARN, we never fail — a legitimately shared selector still works,
but the common "AI got it wrong" case becomes visible. See
``findings/W5-discovery-discrimination.md`` (an AdResult that latched onto the organic
selector). A field's ``root`` (its parent scope) is part of identity here, so once
field-level roots discriminate two regions, their fields are no longer "duplicates".
"""

from __future__ import annotations

from typing import Any

# Fields shared by construction (the contract/container root) — never a conflation smell.
_STRUCTURAL = frozenset({'root', 'container', 'yosoi_container'})

_Identity = tuple[Any, ...]


def _primary_identity(slot: Any) -> _Identity | None:
    """Stable identity for a field's primary selector (incl. its root scope)."""
    if not isinstance(slot, dict):
        return None
    primary = slot.get('primary')
    if not isinstance(primary, dict):
        return None
    value = primary.get('value')
    if not value or str(value).strip().upper() == 'NA':
        return None
    root = slot.get('root') if isinstance(slot.get('root'), dict) else None
    root_value = root.get('value') if root else None
    return (primary.get('type', 'css'), str(value), primary.get('name'), primary.get('nth'), root_value)


def duplicate_fields(selector_map: dict[str, Any] | None) -> dict[str, list[str]]:
    """Return ``{selector_value: [fields]}`` for selectors shared by >1 distinct field.

    Structural/container fields are excluded. A field whose primary is scoped under a
    distinct ``root`` does not collide with one under another root.
    """
    by_id: dict[_Identity, list[str]] = {}
    for field, slot in (selector_map or {}).items():
        if field in _STRUCTURAL:
            continue
        ident = _primary_identity(slot)
        if ident is None:
            continue
        by_id.setdefault(ident, []).append(field)
    return {ident[1]: fields for ident, fields in by_id.items() if len(fields) > 1}


def primary_selector_set(selector_map: dict[str, Any] | None) -> frozenset[_Identity]:
    """The set of distinct primary-selector identities (content fields only)."""
    out: set[_Identity] = set()
    for field, slot in (selector_map or {}).items():
        if field in _STRUCTURAL:
            continue
        ident = _primary_identity(slot)
        if ident is not None:
            out.add(ident)
    return frozenset(out)


def maps_collide(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    """True when two contracts' content selectors are a non-empty IDENTICAL set.

    The cross-contract smell: e.g. an ``AdResult`` and an ``OrganicResult`` discovered
    on the same page resolved to the exact same selectors — they are not being
    discriminated, so at least one is wrong.
    """
    sa, sb = primary_selector_set(a), primary_selector_set(b)
    return bool(sa) and sa == sb
