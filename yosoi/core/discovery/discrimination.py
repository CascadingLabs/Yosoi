"""Deterministic discrimination + genericity checks for discovered selectors.

Prompts are a noisy candidate GENERATOR; this module is the deterministic JUDGE — the
part that generalizes to a million pages because it depends on the DOM, not on a model
getting it right.

Two contracts that must target different things (an Ad vs an Organic result) are
*discriminated* iff their field selectors resolve to DISJOINT sets of DOM elements — NOT
iff the first extracted values happen to differ (that is luck: a generic ``a::attr(href)``
grabs the ad only because the ad is first in the DOM). The same element-set primitive is
the "generic vs fingerprinted" detector: a generic selector's element set bleeds into the
other contract's region or is far larger than the field needs; a fingerprinted one matches
exactly its region and nothing else.

All functions operate on a SINGLE parse so lxml element identities are comparable.
"""

from __future__ import annotations

from typing import Any

from parsel import Selector

from yosoi.models.selectors import SelectorEntry, coerce_selector_entry

# Fields shared by construction — never part of a discrimination comparison.
_STRUCTURAL = frozenset({'root', 'container', 'yosoi_container'})


def _strip_pseudo(css: str) -> str:
    """Drop ``::attr(...)`` / ``::text`` so we match the ELEMENT, not its attribute/text node."""
    out = css
    for marker in ('::attr(', '::text'):
        idx = out.find(marker)
        if idx != -1:
            out = out[:idx]
    return out.strip() or '*'


def _node_id(node: Any) -> str | None:
    """A STABLE identity for an lxml element — its canonical tree path.

    ``id(node)`` is NOT usable: lxml elements are transient Python proxies, so two
    retrievals of the same underlying node have different ``id()``. ``getpath`` returns a
    canonical absolute path (e.g. ``/html/body/div[2]/a``) that is stable across calls.
    """
    if isinstance(node, str):
        return None  # a text/attr node, not an element
    try:
        return str(node.getroottree().getpath(node))
    except Exception:  # noqa: BLE001
        return None


def _element_ids(sel: Selector, entry: SelectorEntry | None, root: SelectorEntry | None) -> set[str]:
    """The set of stable element identities a (root, leaf) pair resolves to under *sel*."""
    if entry is None:
        return set()
    scope = sel
    if root is not None:
        roots = sel.css(root.value) if root.type == 'css' else sel.xpath(root.value)
        if not roots:
            return set()
        scope = roots[0]
    value = _strip_pseudo(entry.value) if entry.type == 'css' else entry.value
    try:
        matches = scope.xpath(value) if entry.type == 'xpath' else scope.css(value)
    except Exception:  # noqa: BLE001 — an unparseable candidate simply matches nothing
        return set()
    return {nid for m in matches if (nid := _node_id(m.root)) is not None}


def field_element_ids(sel: Selector, slot: dict[str, Any]) -> set[str]:
    """Element identities the field's PRIMARY selector resolves to (root-scoped)."""
    primary = coerce_selector_entry(slot.get('primary'))
    root = coerce_selector_entry(slot.get('root'))
    return _element_ids(sel, primary, root)


def match_count(html: str, slot: dict[str, Any]) -> int:
    """How many elements the field's primary selector matches — a genericity signal."""
    return len(field_element_ids(Selector(text=html), slot))


def is_generic(html: str, slot: dict[str, Any], *, expected: int = 1, slack: int = 1) -> bool:
    """True when a field selector matches far more elements than the field needs.

    A single-record field whose selector matches many elements only landed on its target
    by position — it is not fingerprinted. ``expected``/``slack`` bound the allowed count.
    """
    n = match_count(html, slot)
    return n > expected + slack


def discriminated(html: str, map_a: dict[str, Any], map_b: dict[str, Any]) -> bool:
    """True iff every shared field's element sets are NON-EMPTY and DISJOINT.

    This is the deterministic answer to "did discovery discriminate these two contracts?"
    — independent of extracted values, prompts, or DOM order. Overlap on even one field
    (e.g. an ad selector that also matches organic anchors) is a hard FAIL.
    """
    sel = Selector(text=html)
    shared = (set(map_a) & set(map_b)) - _STRUCTURAL
    if not shared:
        return False
    for field in shared:
        a = field_element_ids(sel, map_a[field])
        b = field_element_ids(sel, map_b[field])
        if not a or not b or (a & b):
            return False
    return True
