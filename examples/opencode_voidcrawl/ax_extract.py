"""Accessibility-tree selectors: extract repeating records by role + accessible name.

The thesis (CAS-27): what assistive tech sees is load-bearing and *already computed
by the browser*. A result card addressed as role="article" with an accessible name,
and a rating read from a descendant role="image" named "4.4 stars 2,980 Reviews", is
far more robust and readable than the obfuscated CSS classes (`a.hfpxzc`, `MW4etd`)
those same elements carry — those classes churn; the roles and names don't.

Works off voidcrawl's `Page.get_full_ax_tree()` — a flat list of CDP AX nodes, each
with `role`, computed `name`, `childIds`, `nodeId`. We group by walking `childIds`,
so a field is scoped to its own card (not matched by document order).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


def node_role(node: dict[str, Any]) -> str | None:
    r = node.get('role')
    return r.get('value') if isinstance(r, dict) else r


def resolve_name(node: dict[str, Any]) -> str | None:
    """CDP exposes `name` as a nested {value:{value}} struct; flatten to the string."""
    nm = node.get('name') or {}
    v = nm.get('value')
    if isinstance(v, dict):
        v = v.get('value')
    return v if isinstance(v, str) and v else None


@dataclass(frozen=True)
class AxField:
    """A field read from within a card's subtree, addressed by AX role + name pattern.

    The accessible NAME of the first descendant matching `role` (and `pattern`, if
    given) is the value. If `pattern` has a capture group, that group is returned;
    otherwise the whole accessible name is.
    """

    key: str
    role: str
    pattern: str | None = None
    _rx: re.Pattern[str] | None = field(default=None, compare=False, repr=False)

    def regex(self) -> re.Pattern[str] | None:
        return re.compile(self.pattern, re.IGNORECASE) if self.pattern else None


def _descendants(node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> Iterator[dict[str, Any]]:
    stack = list(node.get('childIds', []))
    seen: set[str] = set()
    while stack:
        cid = stack.pop()
        if cid in seen or cid not in by_id:
            continue
        seen.add(cid)
        child = by_id[cid]
        yield child
        stack.extend(child.get('childIds', []))


def extract_cards(
    nodes: list[dict[str, Any]],
    *,
    card_role: str,
    fields: list[AxField],
    skip_name_prefixes: tuple[str, ...] = (),
) -> list[dict[str, str | None]]:
    """Extract one record per `card_role` node: its accessible name + each field.

    Each record is ``{'name': <card name>, <field.key>: <value|None>, ...}``. Cards
    whose name starts with any `skip_name_prefixes` (e.g. "Ad ·") are dropped.
    """
    by_id = {n['nodeId']: n for n in nodes if 'nodeId' in n}
    records: list[dict[str, str | None]] = []
    for node in nodes:
        if node_role(node) != card_role:
            continue
        name = resolve_name(node)
        if not name or any(name.startswith(p) for p in skip_name_prefixes):
            continue
        record: dict[str, str | None] = {'name': name}
        descendants = list(_descendants(node, by_id))
        for f in fields:
            record[f.key] = _field_value(f, descendants)
        records.append(record)
    return records


def _field_value(f: AxField, descendants: list[dict[str, Any]]) -> str | None:
    rx = f.regex()
    for d in descendants:
        if node_role(d) != f.role:
            continue
        dn = resolve_name(d)
        if dn is None:
            continue
        if rx is None:
            return dn
        m = rx.search(dn)
        if m:
            return m.group(1) if m.groups() else dn
    return None
