"""Accessibility-tree helpers for DOM trigger detection.

These helpers consume raw CDP AX nodes from VoidCrawl's
``get_full_ax_tree`` API and turn them into trigger candidates. They are
pure functions so most coverage can run without a browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
