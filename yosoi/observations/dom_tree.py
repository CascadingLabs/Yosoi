"""Pure rendered-DOM shape, identity, and summary primitives."""

from __future__ import annotations

import hashlib
from collections import Counter
from urllib.parse import quote, unquote

from yosoi.observations.models.dom import DomNode, DomRuntimeState, DomVisibility

_DOM_PATH_PREFIX = '/dom/node/'
_RUNTIME_FIELDS = ('value', 'checked', 'selected', 'expanded', 'pressed', 'disabled', 'focused')


def dom_locator(node_id: str) -> str:
    """Return the canonical snapshot-local path for one producer-assigned node ID."""
    return f'{_DOM_PATH_PREFIX}{quote(node_id, safe="")}'


def node_id_from_locator(path: str) -> str:
    """Decode a DOM locator path, failing closed for non-DOM paths."""
    if not path.startswith(_DOM_PATH_PREFIX) or not path[len(_DOM_PATH_PREFIX) :]:
        raise ValueError(f'not a rendered-DOM locator: {path!r}')
    return unquote(path[len(_DOM_PATH_PREFIX) :])


def dom_skeleton_signature(node: DomNode) -> str:
    """Return a content-independent shape that retains state affecting page meaning.

    IDs and ``data-*`` values are identity, not shape. Classes, ARIA attributes, visibility,
    and captured interactive state remain in the signature so completed/hidden controls are
    not merged into active/visible controls merely because their tags match.
    """
    attrs = tuple(
        (attribute.name, attribute.value)
        for attribute in node.attributes
        if attribute.name != 'id' and not attribute.name.startswith('data-')
    )
    runtime = _runtime_signature(node.runtime)
    children = tuple(dom_skeleton_signature(child) for child in node.children)
    shadow = dom_skeleton_signature(node.shadow_root) if node.shadow_root is not None else None
    material = repr((node.tag, attrs, node.visibility.value, runtime, children, shadow)).encode()
    return hashlib.blake2b(material, digest_size=8).hexdigest()


def dom_candidate_keys(node: DomNode) -> tuple[str, ...]:
    """Return durable content keys; producer node IDs are intentionally excluded."""
    keys: list[str] = []
    attributes = {attribute.name: attribute.value for attribute in node.attributes}
    if attributes.get('id'):
        keys.append(f'id={attributes["id"]}')
    keys.extend(
        f'{name}={attributes[name]}' for name in sorted(attributes) if name.startswith('data-') and attributes[name]
    )
    text = ' '.join(node.text.split())
    if text:
        digest = hashlib.blake2b(text.encode(), digest_size=8).hexdigest()
        keys.append(f'text:{digest}')
    return tuple(keys)


def assign_dom_member_keys(members: tuple[DomNode, ...]) -> tuple[str | None, ...]:
    """Choose one unique durable key per member in one repeat group."""
    candidates = [dom_candidate_keys(member) for member in members]
    frequency: Counter[str] = Counter(key for keys in candidates for key in keys)
    return tuple(next((key for key in keys if frequency[key] == 1), None) for keys in candidates)


def dom_label(node: DomNode) -> str:
    """Return a compact tag/id/class label without dropping selector-bearing attributes."""
    attributes = {attribute.name: attribute.value for attribute in node.attributes}
    label = node.tag
    if attributes.get('id'):
        label += f'#{attributes["id"]}'
    classes = attributes.get('class', '').split()
    if classes:
        label += ''.join(f'.{class_name}' for class_name in classes)
    return label


def dom_summary(node: DomNode, *, max_chars: int = 160) -> str:
    """Summarize visible/stateful facts without serializing the whole subtree."""
    parts: list[str] = [node.visibility.value]
    text = ' '.join(node.text.split())
    if text:
        parts.append(f'text="{text[:max_chars]}"')
    if node.runtime is not None:
        state = _runtime_values(node.runtime)
        if state:
            parts.append('state=' + ','.join(f'{name}={value}' for name, value in state))
    if node.geometry is not None:
        parts.append(f'box={node.geometry.width:g}x{node.geometry.height:g}')
    if node.declared_count is not None:
        parts.append(f'declared={node.declared_count}')
    if node.portal_target_id is not None:
        parts.append(f'portal→{node.portal_target_id}')
    if node.shadow_root is not None:
        parts.append('shadow-root')
    if node.children:
        hidden = sum(child.visibility is not DomVisibility.VISIBLE for child in node.children)
        suffix = f', {hidden} non-visible' if hidden else ''
        parts.append(f'children={len(node.children)}{suffix}')
    return '; '.join(parts)[:max_chars]


def dom_subtree_text(node: DomNode) -> str:
    """Return the node's whole rendered text, whitespace-collapsed.

    Crosses shadow boundaries deliberately: a member's distinguishing content is what a
    reader would see, and a shadow root is an implementation detail of where it lives.
    """
    return ' '.join(_text_fragments(node)).strip()


def _text_fragments(node: DomNode) -> list[str]:
    """Collect one node's text then its shadow and light children, in render order."""
    parts = [' '.join(node.text.split())] if node.text.strip() else []
    if node.shadow_root is not None:
        parts.extend(_text_fragments(node.shadow_root))
    for child in node.children:
        parts.extend(_text_fragments(child))
    return parts


def _runtime_signature(runtime: DomRuntimeState | None) -> tuple[tuple[str, object], ...]:
    return tuple(_runtime_values(runtime))


def _runtime_values(runtime: DomRuntimeState | None) -> tuple[tuple[str, object], ...]:
    if runtime is None:
        return ()
    values = []
    for name in _RUNTIME_FIELDS:
        value = getattr(runtime, name)
        if value is not None:
            values.append((name, value))
    return tuple(values)


__all__ = [
    'assign_dom_member_keys',
    'dom_candidate_keys',
    'dom_label',
    'dom_locator',
    'dom_skeleton_signature',
    'dom_subtree_text',
    'dom_summary',
    'node_id_from_locator',
]
