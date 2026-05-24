"""Accessibility-tree helpers for DOM trigger detection.

These helpers consume raw CDP AX nodes from VoidCrawl's
``get_full_ax_tree`` API and turn them into trigger candidates. They are
pure functions so most coverage can run without a browser.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from yosoi.models.selectors import FieldSelectors

INTERACTIVE_ROLES = frozenset(
    {
        'button',
        'link',
        'menuitem',
        'tab',
        'checkbox',
        'radio',
        'switch',
        'combobox',
    }
)


@dataclass(frozen=True)
class AxTarget:
    """Replayable accessibility target for an interactive AX node."""

    role: str
    name: str
    nth: int = 0


@dataclass(frozen=True)
class AxSnapshot:
    """Compact AX metadata plus click targets discovered from raw nodes."""

    node_count: int
    named_count: int
    targets: tuple[AxTarget, ...]

    @property
    def richness(self) -> float:
        """Ratio of named nodes to total nodes."""
        if self.node_count == 0:
            return 0.0
        return self.named_count / self.node_count


def value_of(node: dict[str, Any], key: str) -> str:
    """Return a CDP AX field's wrapped string value."""
    value = node.get(key)
    if isinstance(value, dict):
        inner = value.get('value')
        return inner if isinstance(inner, str) else ''
    return value if isinstance(value, str) else ''


def is_ignored(node: dict[str, Any]) -> bool:
    """Return whether a CDP AX node is ignored."""
    return bool(node.get('ignored', False))


def snapshot(nodes: list[dict[str, Any]]) -> AxSnapshot:
    """Build a compact snapshot from raw CDP AX nodes."""
    named_count = 0
    targets: list[AxTarget] = []
    seen: dict[tuple[str, str], int] = {}

    for node in nodes:
        if is_ignored(node):
            continue

        role = value_of(node, 'role')
        name = value_of(node, 'name').strip()
        if name:
            named_count += 1
        if not name or role not in INTERACTIVE_ROLES:
            continue

        key = (role, name)
        nth = seen.get(key, 0)
        seen[key] = nth + 1
        targets.append(AxTarget(role=role, name=name, nth=nth))

    return AxSnapshot(node_count=len(nodes), named_count=named_count, targets=tuple(targets))


def find_target(
    snap: AxSnapshot,
    *,
    roles: set[str],
    names: tuple[str, ...],
    exact: bool = False,
) -> AxTarget | None:
    """Find the first AX target whose role and name match."""
    lowered = tuple(name.lower() for name in names)
    for target in snap.targets:
        if target.role not in roles:
            continue
        if not lowered or lowered == ('',):
            return target
        target_name = target.name.lower().strip()
        if exact:
            if target_name in lowered:
                return target
        elif any(name in target_name for name in lowered):
            return target
    return None


# ---------------------------------------------------------------------------
# Extraction by AX role + name (the read-side counterpart to find_target)
# ---------------------------------------------------------------------------


def descendants(node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Walk a node's subtree via ``childIds`` (so fields are scoped to their own card)."""
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


def extract_records(
    nodes: list[dict[str, Any]],
    *,
    card_role: str,
    fields: dict[str, FieldSelectors],
    skip_name_prefixes: tuple[str, ...] = (),
) -> list[dict[str, str | None]]:
    """One record per ``card_role`` node: its accessible name + each field's raw text.

    The read-side of CAS-27, on the unified selector model: each field is a
    ``FieldSelectors`` cascade; its `role` entries resolve a descendant by AX role
    (+ accessible-name substring, if set) and return that node's text. Value *parsing*
    (e.g. "4.4 stars" -> 4.4) is the caller's Yosoi coercion type, not done here.
    Fields are scoped per-card via ``childIds``; ``skip_name_prefixes`` drops ads.
    """
    by_id = {n['nodeId']: n for n in nodes if 'nodeId' in n}
    records: list[dict[str, str | None]] = []
    for node in nodes:
        if is_ignored(node) or value_of(node, 'role') != card_role:
            continue
        name = value_of(node, 'name').strip()
        if not name or any(name.startswith(p) for p in skip_name_prefixes):
            continue
        descs = list(descendants(node, by_id))
        record: dict[str, str | None] = {'name': name}
        for key, selectors in fields.items():
            record[key] = _resolve_field(selectors, descs)
        records.append(record)
    return records


def _resolve_field(selectors: FieldSelectors, descs: list[dict[str, Any]]) -> str | None:
    """Try the cascade; a `role` entry returns the first matching descendant's text.

    css/xpath entries can't be resolved against the AX tree alone, so they are
    skipped here (the cascade continues) — they'd resolve on the DOM/parsel path.
    """
    for _, entry in selectors.as_entries():
        if entry is None or entry.type != 'role':
            continue
        for d in descs:
            if value_of(d, 'role') != entry.role:
                continue
            text = value_of(d, 'name')
            if not text:
                continue
            if entry.name and entry.name.lower() not in text.lower():
                continue
            return text
    return None
