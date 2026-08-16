"""Pure accessibility-tree shape, identity, and summary primitives.

The AX counterparts of `dom_tree.py`, deliberately the same set: a census, ancestry, sibling
counts, durable steps, a shape signature, member keys, region coverage, and conditional facts.
Identity itself is not defined here — `anchoring.py` owns that for every modality, and this
module only states what an AX node's *attributes* are so the shared recipe can be applied to
them.

Resolution lives here too (`resolve_ax_address`, `ax_region_members`), for the same reason the
rendered-DOM resolver lives beside its own primitives: the inspector dispatches to a modality,
it does not know one.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from urllib.parse import quote, unquote

from yosoi.observations import anchoring
from yosoi.observations.index.addressing import AddressSegment, ObservationAddress, ObservationAddressError
from yosoi.observations.models.ax import AxCapability, AxNode, AxSnapshot
from yosoi.observations.models.view import RegionCoverage

_AX_PATH_PREFIX = '/ax/node/'
AX_STEP_VALUE_RESERVED = frozenset((*anchoring.LOCATOR_RESERVED, '/'))
"""Characters the AX relative-step parser cannot round-trip inside a quoted value."""

SET_SIZE_PROPERTY = 'setsize'
"""The property a container uses to declare how many members its collection really has.

The AX counterpart of `aria-rowcount`/`data-total-count` on the DOM side, and the browser has
already computed it from `aria-setsize`, so a virtualised list states its own true total.
"""

LEVEL_PROPERTY = 'level'
"""Heading/treeitem depth. Part of SHAPE, not state: `h2` and `h3` are different structures."""

DEFAULT_PROPERTY_VALUES = {
    'focusable': 'true',
    'invalid': 'false',
    'required': 'false',
    'disabled': 'false',
    'readonly': 'false',
    'atomic': 'false',
    'busy': 'false',
    'live': 'off',
    'relevant': 'additions text',
    'multiselectable': 'false',
    'multiline': 'false',
    'editable': 'plaintext',
}
"""Property values a summary omits, declared once on the root entry instead of on every line.

`focusable=true` on every control and `invalid=false` on every field are the modality's
background, and restating the background is what the DOM reducer measured at 3.7% of its whole
index. A property whose value DEPARTS from this table is printed — `focusable=false` on a button
is a finding, and it is the same fact as its own absence only if a reader was told the rule.
"""


def ax_locator(node_id: str) -> str:
    """Return the canonical snapshot-local path for one producer-assigned AX node id."""
    return f'{_AX_PATH_PREFIX}{quote(node_id, safe="")}'


def node_id_from_locator(path: str) -> str:
    """Decode an AX locator path, failing closed for non-AX paths."""
    if not path.startswith(_AX_PATH_PREFIX) or not path[len(_AX_PATH_PREFIX) :]:
        raise ValueError(f'not an accessibility-tree locator: {path!r}')
    return unquote(path[len(_AX_PATH_PREFIX) :])


def ax_children(node: AxNode, by_id: dict[str, AxNode]) -> tuple[AxNode, ...]:
    """Return a node's children in producer order. Relations are edges, never children."""
    return tuple(by_id[child_id] for child_id in node.child_ids)


def walk_ax(snapshot: AxSnapshot) -> Iterator[AxNode]:
    """Yield every node of one snapshot in tree order, ignored nodes included."""
    by_id = snapshot.by_id
    stack = [snapshot.root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(ax_children(node, by_id)))


def ax_attributes(node: AxNode) -> list[tuple[str, str]]:
    """Return one AX node's own properties as ordered attributes, for the shared anchor tiers.

    Order is the whole decision here, because `anchoring.structural_keys` uses exactly one
    positional tier — "whatever the author wrote first" — and AX offers no `id`, no `data-*`,
    and no `class`. So the first pair is the node's most identifying fact.

    The accessible NAME is that fact. It is what a reader recognises, what `click_by_role`
    matches on, and what survives a re-render; the role is the node's shape and is shared by
    every sibling of the same kind, so leading with it would make almost every anchor
    non-unique and refuse almost every identity — the measured failure the rendered-DOM
    modality already had. An unnamed node leads with its role and usually earns nothing, which
    is the honest outcome.
    """
    attributes: list[tuple[str, str]] = []
    name = ' '.join(node.name.split())
    if name:
        attributes.append(('name', name))
    if node.role:
        attributes.append(('role', node.role))
    attributes.extend((prop.name, prop.value) for prop in node.properties)
    return attributes


def ax_anchor_census(snapshot: AxSnapshot) -> dict[str, int]:
    """Count anchor keys across a whole AX snapshot, so uniqueness is checked not assumed."""
    return anchoring.build_census((node.role, ax_attributes(node)) for node in walk_ax(snapshot))


def ax_nearest_anchor(node: AxNode, by_id: dict[str, AxNode], census: dict[str, int]) -> tuple[AxNode, str] | None:
    """Return the nearest ancestor-or-self carrying a snapshot-unique key, and that key."""
    current: AxNode | None = node
    while current is not None:
        key = anchoring.usable_anchor(current.role, ax_attributes(current), census)
        if key is not None:
            return current, key
        current = by_id.get(current.parent_id) if current.parent_id is not None else None
    return None


@dataclass(frozen=True, slots=True)
class AxSiblingIndex:
    """Counts over one parent's children, so a durable step costs attributes, not siblings."""

    roles: Counter[str]
    keyed: Counter[tuple[str, str, str]]
    """Counts of `(role, attribute name, attribute value)`; uniqueness must hold among
    same-role siblings, since that is what the emitted step `./role[@name="value"]` selects."""


def ax_sibling_index(children: Sequence[AxNode]) -> AxSiblingIndex:
    """Build the per-parent counts a durable AX step decision needs."""
    roles: Counter[str] = Counter()
    keyed: Counter[tuple[str, str, str]] = Counter()
    for child in children:
        roles[child.role] += 1
        for name, value in ax_attributes(child):
            keyed[(child.role, name, value)] += 1
    return AxSiblingIndex(roles=roles, keyed=keyed)


def ax_step(node: AxNode, index: AxSiblingIndex) -> str | None:
    """Return a relative step selecting `node` among its siblings, or None if none is durable.

    Two content-addressed forms only, mirroring `dom_step`: `./role` when the role is unique
    among its siblings, and `./role[@name="value"]` when one attribute makes it so. A step that
    would need a sibling position is refused — `./button[3]` is a positional guess wearing a
    durable address's clothes.
    """
    if not node.role or not anchoring.SAFE_TAG.fullmatch(node.role):
        return None
    if index.roles.get(node.role) == 1:
        return f'./{node.role}'
    for name, value in ax_attributes(node):
        if any(character in value for character in AX_STEP_VALUE_RESERVED):
            continue
        if index.keyed.get((node.role, name, value)) == 1:
            return f'./{node.role}[@{name}="{value}"]'
    return None


def ax_shape_signature(node: AxNode, by_id: dict[str, AxNode], cache: dict[str, str] | None = None) -> str:
    """Return the node's SHAPE — the equivalence a repeat region collapses on.

    Shape is role, the *names* of the states the node carries, its level, its ignored band, and
    the shapes of its children. The accessible name, the value, the description, and every
    property VALUE are excluded, because those are discriminants: they tell one member of a run
    from another, which is what the region summary, the member variants, and `expand` are for.

    This is the mistake the rendered-DOM pruner paid for and documented: with attribute values in
    the signature, nine near-identical product cards produced nine distinct signatures and
    collapsed into nothing. Twelve checkboxes that differ only in `checked` are the same case.

    `ignored` is in the shape and is not a state. It is which BAND the node is in — inside the
    accessibility tree or excluded from it — and an `aria-hidden` button among live buttons is a
    different kind of thing, not a differently-configured one. Keeping bands apart is what makes
    the excluded one visible in the index instead of averaged into a region's tally.

    `level` is in the shape for the same reason a tag is: a heading level is structure. Two
    headings at different levels are not two states of one heading.
    """
    signatures = cache if cache is not None else {}
    pending: list[tuple[AxNode, bool]] = [(node, False)]
    while pending:
        current, expanded = pending.pop()
        if current.node_id in signatures:
            continue
        children = ax_children(current, by_id)
        if not expanded:
            pending.append((current, True))
            pending.extend((child, False) for child in reversed(children) if child.node_id not in signatures)
            continue
        values = {prop.name: prop.value for prop in current.properties}
        material = repr(
            (
                current.role,
                current.state_names,
                values.get(LEVEL_PROPERTY),
                current.ignored,
                tuple(signatures[child.node_id] for child in children),
            )
        ).encode()
        signatures[current.node_id] = hashlib.blake2b(material, digest_size=8).hexdigest()
    return signatures[node.node_id]


def ax_naming_census(snapshot: AxSnapshot) -> dict[tuple[str, str], int]:
    """Count `(role, accessible name)` pairs, which is what an executable target is keyed on."""
    counts: Counter[tuple[str, str]] = Counter()
    for node in walk_ax(snapshot):
        counts[(node.role, ' '.join(node.name.split()))] += 1
    return dict(counts)


def ax_label(node: AxNode, *, nth: int = 0) -> str:
    """Return `role "name"` — the compact label, and a directly executable target.

    Deliberately the exact shape VoidCrawl's `click_by_role(role, name, nth)` takes, so an
    address in this index is already an action: reading the overview and acting on it need no
    translation step, and no CSS selector has to be invented for a control the page never gave
    one. `nth` is appended only when the `(role, name)` pair repeats in the snapshot, because
    that is the only case where it changes what gets clicked.
    """
    name = ' '.join(node.name.split())
    label = f'{node.role or "unknown"}'
    if name:
        label += f' "{name}"'
    if nth:
        label += f' #{nth}'
    return label


def deviating_properties(node: AxNode) -> list[tuple[str, str]]:
    """Return the node's properties whose values depart from the declared defaults.

    A property whose value is empty is dropped too. The browser reports `valuetext` with no text
    on a numeric spinbutton, and `valuetext=` states nothing a reader can act on while costing a
    line on every such control.
    """
    return [
        (prop.name, prop.value)
        for prop in node.properties
        if prop.value and DEFAULT_PROPERTY_VALUES.get(prop.name) != prop.value
    ]


def ax_relation_text(node: AxNode, by_id: dict[str, AxNode]) -> str:
    """Render a node's cross-hierarchy edges as facts, with what they point at.

    An unresolvable target is reported rather than dropped: `labelledby→(unresolved "missing-id")`
    is an accessibility defect, and an edge silently omitted for having no AX node to point at is
    that defect erased.
    """
    parts: list[str] = []
    for relation in node.relations:
        target = by_id.get(relation.target_node_id) if relation.target_node_id is not None else None
        if target is not None:
            parts.append(f'{relation.kind.value}→{ax_label(target)}')
        elif relation.target_text:
            parts.append(f'{relation.kind.value}→(unresolved "{relation.target_text}")')
        else:
            parts.append(f'{relation.kind.value}→(unresolved dom node {relation.target_backend_dom_node_id})')
    return ', '.join(parts)


def ax_summary(node: AxNode, by_id: dict[str, AxNode], *, max_chars: int = 160) -> str:
    """Summarize what DEVIATES for one AX node, stating its band and its relationships.

    `ignoredReasons` is printed first when present, because it is usually the finding: a control
    that exists, is addressable, and is not in the accessibility tree, together with the
    browser's own explanation of why.
    """
    parts: list[str] = []
    if node.ignored:
        # `labelFor` and `ariaHiddenElement` carry a bare `true` or an unrenderable node
        # reference; the reason NAME is the finding, and `ariaHiddenElement=true` only pads it.
        reasons = ', '.join(
            reason.name if reason.value in {'', 'true'} else f'{reason.name}={reason.value}'
            for reason in node.ignored_reasons
        )
        parts.append(f'ignored[{reasons or "no reason reported"}]')
    value = ' '.join(node.value.split())
    if value:
        parts.append(f'value="{value[:max_chars]}"')
    description = ' '.join(node.description.split())
    if description:
        parts.append(f'description="{description[:max_chars]}"')
    states = deviating_properties(node)
    if states:
        parts.append('state[' + ', '.join(f'{name}={value}' for name, value in states) + ']')
    relations = ax_relation_text(node, by_id)
    if relations:
        parts.append(relations)
    if node.child_ids:
        ignored_children = sum(by_id[child].ignored for child in node.child_ids)
        suffix = f', {ignored_children} ignored' if ignored_children else ''
        parts.append(f'children={len(node.child_ids)}{suffix}')
    # A node that deviates in nothing would otherwise summarise to the empty string, which reads
    # as "nothing here" for a node that may hold a whole labelled subtree.
    return ('; '.join(parts) or ax_subtree_text(node, by_id))[:max_chars]


def ax_member_summary(node: AxNode, by_id: dict[str, AxNode], *, max_chars: int = 160) -> str:
    """Summarise one expanded region member, carrying what tells it apart from its siblings."""
    content = ax_subtree_text(node, by_id)
    base = ax_summary(node, by_id, max_chars=max_chars)
    if not content or content in base:
        return base[:max_chars]
    return f'{base}; content="{content}"'[:max_chars]


def ax_subtree_text(node: AxNode, by_id: dict[str, AxNode]) -> str:
    """Return the accessible names and values in this node's subtree, in tree order.

    Adjacent repeats are collapsed. An AX tree restates the same string at every level of its own
    text shell — a `tab` computes the name "Production" from a `StaticText` child that holds
    "Production" and an `InlineTextBox` grandchild that holds it again — so the naive join reads
    `"Production Production Production"` and spends a region's whole sample budget saying one
    word three times.
    """
    parts: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        for field in (current.name, current.value):
            text = ' '.join(field.split())
            if text and text != (parts[-1] if parts else None):
                parts.append(text)
        stack.extend(reversed(ax_children(current, by_id)))
    return ' '.join(parts).strip()


def ax_candidate_keys(node: AxNode, by_id: dict[str, AxNode]) -> tuple[str, ...]:
    """Return durable member keys for one node; producer node ids are excluded on purpose.

    Own name first, then own value, then a digest of the subtree's accessible text. The last tier
    is not a luxury: a `listitem` is very often unnamed while the link inside it is named, and
    without it every member of an ordinary AX list would be addressable only by position.
    """
    keys: list[str] = []
    name = ' '.join(node.name.split())
    if name:
        keys.append(f'name={name}')
    value = ' '.join(node.value.split())
    if value:
        keys.append(f'value={value}')
    text = ax_subtree_text(node, by_id)
    if text:
        keys.append(f'text:{hashlib.blake2b(text.encode(), digest_size=8).hexdigest()}')
    return tuple(dict.fromkeys(keys))


def assign_ax_member_keys(members: Sequence[AxNode], by_id: dict[str, AxNode]) -> tuple[str | None, ...]:
    """Choose one unique durable key per member of one repeat group, or None for a member."""
    candidates = [ax_candidate_keys(member, by_id) for member in members]
    frequency: Counter[str] = Counter(key for keys in candidates for key in keys)
    return tuple(next((key for key in keys if frequency[key] == 1), None) for keys in candidates)


def matches_ax_key(node: AxNode, key: str, by_id: dict[str, AxNode]) -> bool:
    """Return whether one member key names this node."""
    return key in ax_candidate_keys(node, by_id)


def ax_region_coverage(container: AxNode, members: Sequence[AxNode]) -> RegionCoverage:
    """State how much of a repeat region one capture actually observed.

    `setsize` describes the container's whole collection, so it can only be compared against
    members that ARE the container's whole collection — the same rule `dom_region_coverage`
    states, for the same reason: a run of 20 rows beside a header row is 20 of something the
    declaration never counted.
    """
    declared: int | None = None
    if len(members) == len(container.child_ids):
        for prop in container.properties:
            if prop.name == SET_SIZE_PROPERTY and prop.value.lstrip('-').isdigit():
                candidate = int(prop.value)
                declared = candidate if candidate >= 0 else None
    return RegionCoverage(observed=len(members), declared=declared, complete=declared == len(members))


def ax_member_variants(members: Sequence[AxNode], by_id: dict[str, AxNode]) -> str:
    """Report property values carried by SOME but not all members of a repeat region.

    Shape does not split on property values, so twelve checkboxes land in one region — which is
    right for compression and would be wrong if the difference vanished. It does not: a state on
    a strict subset of a run is the page's own statement that these members are not alike, and it
    is reported here instead of fragmenting the region.

    States are collected over each member's whole SUBTREE, not just the member node. In real
    markup the repeated element is often not the stateful one: `<label><input checkbox> Email
    </label>` makes the accessibility tree repeat an unnamed wrapper whose checkbox child holds
    `checked`, so a member-node-only tally reported "these five are identical" about five
    checkboxes, two of which were ticked.
    """
    if len(members) < 2:
        return ''
    counts: Counter[tuple[str, str]] = Counter()
    for member in members:
        states: set[tuple[str, str]] = set()
        stack = [member]
        while stack:
            current = stack.pop()
            states.update((prop.name, prop.value) for prop in current.properties)
            stack.extend(ax_children(current, by_id))
        counts.update(states)
    varying = {pair: count for pair, count in counts.items() if count < len(members)}
    if not varying:
        return ''
    ordered = sorted(varying.items(), key=lambda item: (-item[1], item[0]))
    return ', '.join(f'{name}={value}×{count}' for (name, value), count in ordered)


def ax_index_conventions(capabilities: tuple[AxCapability, ...] = ()) -> str:
    """State the reading conventions and the modality's own limits once, on the root entry.

    The absence caveat is stated unconditionally, not only when a capability record happens to
    carry it: every empty AX result a reader ever sees has to be read as "the browser reported
    nothing here", never as "the page shows nothing here".
    """
    unavailable = [
        f'{capability.kind.value} unavailable ({capability.reason})'
        for capability in capabilities
        if not capability.available
    ]
    defaults = ', '.join(f'{name}={value}' for name, value in sorted(DEFAULT_PROPERTY_VALUES.items()))
    conventions = [
        'AX absence is never proof that visible information does not exist',
        *unavailable,
        'conventions: labels are role "name", executable as click_by_role',
        'ignored nodes retained with reasons',
        f'default states omitted ({defaults})',
        'observed/declared only when setsize declared',
    ]
    return '; '.join(conventions)


def ax_parent_of(node: AxNode, by_id: dict[str, AxNode]) -> AxNode | None:
    """Return one node's parent, or None at the root."""
    return by_id.get(node.parent_id) if node.parent_id is not None else None


def resolve_ax_anchor(snapshot: AxSnapshot, anchor: str) -> AxNode:
    """Resolve an anchored first segment by its KEY rather than by re-parsing its path.

    The locator carries both and `AddressSegment` already checks them against each other, so
    resolution uses the key the identity was computed from — re-deriving a match from the path
    would be a second interpretation of one fact, free to disagree with the first.
    """
    matches = [node for node in walk_ax(snapshot) if anchor in anchoring.anchor_keys(node.role, ax_attributes(node))]
    if len(matches) != 1:
        raise ObservationAddressError(f'AX anchor {anchor!r} resolved to {len(matches)} nodes')
    return matches[0]


def ax_region_members(container: AxNode, shape: str, by_id: dict[str, AxNode]) -> list[AxNode]:
    """Return the container's children whose shape matches, in producer order."""
    members = [child for child in ax_children(container, by_id) if ax_shape_signature(child, by_id) == shape]
    if not members:
        raise ObservationAddressError(f'no AX members of shape {shape!r} remain in this region')
    return members


_AX_STEP = re.compile(r'^(?P<role>[\w.-]+)(?:\[@(?P<name>[\w:.-]+)="(?P<value>[^"]*)"\])?$')
"""The only two relative step forms an AX address may carry: `role` and `role[@name="value"]`.

Bounded on purpose, exactly as the rendered-DOM grammar is: a resolver that accepted steps the
pruner never mints — positional ones above all — would resolve addresses whose durability nobody
has measured.
"""


def _ax_descend(node: AxNode, relative_path: str, by_id: dict[str, AxNode]) -> AxNode:
    """Walk one relative segment step by step, failing closed at the first ambiguity."""
    current = node
    for raw in relative_path.removeprefix('./').split('/'):
        match = _AX_STEP.match(raw)
        if match is None:
            raise ObservationAddressError(f'{raw!r} is not an accessibility-tree address step')
        candidates = [child for child in ax_children(current, by_id) if child.role == match['role']]
        if match['name'] is not None:
            wanted = (match['name'], match['value'])
            candidates = [child for child in candidates if any(pair == wanted for pair in ax_attributes(child))]
        if len(candidates) != 1:
            raise ObservationAddressError(f'AX address step {raw!r} resolved to {len(candidates)} nodes')
        current = candidates[0]
    return current


def resolve_ax_address(snapshot: AxSnapshot, address: ObservationAddress) -> AxNode:
    """Resolve one AX address, anchored or by producer node id, then select any member."""
    by_id = snapshot.by_id
    first = address.segments[0]
    if first.anchor is not None:
        node = resolve_ax_anchor(snapshot, first.anchor)
    else:
        try:
            node_id = node_id_from_locator(first.path)
        except ValueError as exc:
            raise ObservationAddressError(str(exc)) from exc
        found = by_id.get(node_id)
        if found is None:
            raise ObservationAddressError(f'AX node {node_id!r} is absent from this snapshot')
        node = found

    for segment in address.segments:
        if segment is not first:
            node = _ax_descend(node, segment.path, by_id)
        if segment.selects_member:
            node = _select_ax_member(node, segment, by_id)
    return node


def _select_ax_member(container: AxNode, segment: AddressSegment, by_id: dict[str, AxNode]) -> AxNode:
    """Select one member of an AX region by durable key, or by declared-unstable position."""
    members = ax_region_members(container, segment.shape or '', by_id)
    if segment.key is not None:
        matched = [member for member in members if matches_ax_key(member, segment.key, by_id)]
        if len(matched) != 1:
            raise ObservationAddressError(f'AX region key {segment.key!r} resolved to {len(matched)} members')
        return matched[0]
    position = segment.ordinal or 0
    if position >= len(members):
        raise ObservationAddressError(f'AX region member ordinal {position} is past the {len(members)} members present')
    return members[position]


__all__ = [
    'DEFAULT_PROPERTY_VALUES',
    'LEVEL_PROPERTY',
    'SET_SIZE_PROPERTY',
    'AxSiblingIndex',
    'assign_ax_member_keys',
    'ax_anchor_census',
    'ax_attributes',
    'ax_candidate_keys',
    'ax_children',
    'ax_index_conventions',
    'ax_label',
    'ax_locator',
    'ax_member_summary',
    'ax_member_variants',
    'ax_naming_census',
    'ax_nearest_anchor',
    'ax_parent_of',
    'ax_region_coverage',
    'ax_region_members',
    'ax_relation_text',
    'ax_shape_signature',
    'ax_sibling_index',
    'ax_step',
    'ax_subtree_text',
    'ax_summary',
    'deviating_properties',
    'matches_ax_key',
    'node_id_from_locator',
    'resolve_ax_address',
    'resolve_ax_anchor',
    'walk_ax',
]
