"""Pure rendered-DOM shape, identity, and summary primitives."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import quote, unquote

from yosoi.observations import anchoring
from yosoi.observations.models.dom import DomCapability, DomNode, DomRuntimeState, DomVisibility
from yosoi.observations.models.view import RegionCoverage

_DOM_PATH_PREFIX = '/dom/node/'
_MEANINGFUL_INVISIBILITY = frozenset(
    {DomVisibility.HIDDEN, DomVisibility.DISPLAY_NONE, DomVisibility.OFFSCREEN, DomVisibility.INERT}
)
"""Visibility states that are a finding about a node, as opposed to an unmeasured one."""

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
    """Return the node's SHAPE — the equivalence relation a repeat region collapses on.

    Shape is tag structure plus the attribute *vocabulary*, and nothing else. Attribute values,
    visibility, and runtime state are deliberately excluded, because they are DISCRIMINANTS, not
    shape: they tell one member from another, which is what the region summary, the member keys,
    and `expand` are for. The region line already reports its state tally and member variants.

    Putting them in the signature counted them twice — once as a splitter, once as a description
    — and the splitting won. Measured on ten live qscrape.dev captures: the nine VaultMart
    product cards produced NINE distinct signatures and collapsed not at all, while the only
    regions the pruner found on that page were star-rating glyphs and two scripts. Real records
    are near-identical, never identical: one card carries a `SPONSORED` badge, another `NEW`, a
    third differs only in `href` and `src`.

    The source-HTML reducer has used tag structure alone since CAS-262 and collapses 10,000 rows
    to two entries. This is that rule, plus the attribute vocabulary, which is a structural fact
    about how an element is built rather than a fact about what fills it.
    """
    names = tuple(
        sorted(
            attribute.name
            for attribute in node.attributes
            if attribute.name != 'id' and not attribute.name.startswith('data-')
        )
    )
    children = tuple(dom_skeleton_signature(child) for child in node.children)
    shadow = dom_skeleton_signature(node.shadow_root) if node.shadow_root is not None else None
    material = repr((node.tag, names, children, shadow)).encode()
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


def dom_region_coverage(container: DomNode, members: Sequence[DomNode]) -> RegionCoverage:
    """State how much of a repeat region one capture actually observed.

    A container's declared count (`aria-rowcount`, `aria-setsize`, …) describes the container's
    whole collection, so it can only be compared against members that are the container's whole
    collection. A run of 20 rows beside a header row is 20 of something the declaration never
    counted, and calling that `20/500` would be a fabricated coverage claim.

    One rule, one place: the pruner and the inspector each derive coverage for the same region,
    and two formulations of "close enough" drift into disagreeing about `complete`.
    """
    declared = container.declared_count if len(members) == len(container.children) else None
    return RegionCoverage(observed=len(members), declared=declared, complete=declared == len(members))


def dom_is_pass_through(node: DomNode) -> bool:
    """Return whether a node adds a level of nesting and nothing else.

    `div.product-card > div.product-card-inner > div.product-card-body` is three entries on a
    real page, each summarised only as `children=1`, none of them telling a reader anything the
    one below does not. Measured across ten live captures: 177 such entries.

    The test is derived, not enumerated — no list of wrapper tag names, which could only fold the
    wrappers someone thought of in advance. A node is a pass-through when it has exactly one
    content child and contributes no discriminant of its own: no text, no runtime state, no
    declared count, no portal or shadow boundary, and no geometry that contradicts its visibility.

    Visibility blocks the fold only when it is a *finding* — hidden, display_none, offscreen, or
    inert. A wrapper that is hidden tells a reader something its child does not. `unknown` is the
    absence of a measurement rather than a fact about the node, and it is uniform across a capture
    whose producer did not report visibility, so treating it as a finding would make this fold dead
    for every such producer while adding nothing.

    `id` and `data-*` bearers are never folded. They carry no content, but they are the most
    intentional anchors a page offers and the raw material a selector is made of; folding away
    the best available anchor to save a line is a bad trade.
    """
    if len(node.children) != 1 or node.shadow_root is not None:
        return False
    if node.visibility in _MEANINGFUL_INVISIBILITY:
        return False
    if node.text.strip() or node.runtime is not None:
        return False
    if node.declared_count is not None or node.portal_target_id is not None:
        return False
    if remarkable_geometry(node) is not None:
        return False
    return not any(attribute.name == 'id' or attribute.name.startswith('data-') for attribute in node.attributes)


def dom_chain(node: DomNode) -> tuple[DomNode, str]:
    """Follow a pass-through chain and return where it ends, plus the path it went through.

    The chain's nesting is not lost, it is moved into the label: `div.card > .inner > .body`
    reads as one place and still names every level a selector would have to traverse. The folded
    wrappers remain in the canonical artifact, so inspecting the entry above the chain returns
    them verbatim.
    """
    labels = [dom_label(node)]
    current = node
    while dom_is_pass_through(current):
        current = current.children[0]
        labels.append(dom_label(current))
    if len(labels) == 1:
        return node, labels[0]
    return current, ' > '.join(labels)


def dom_member_variants(members: Sequence[DomNode]) -> str:
    """Report class tokens carried by SOME but not all members of a repeat region.

    Shape no longer splits on attribute values, so `li.todo` and `li.todo.completed` land in one
    region — which is right for compression and would be wrong if the difference vanished. It
    does not: a token on a strict subset of a run is exactly the page's own statement that these
    members are not all alike, and it is reported here instead of fragmenting the region.

    Strict subset, both ends. A token on every member is the run's shared identity and says
    nothing about variation; a token on one member of one is not a variant of anything.
    """
    if len(members) < 2:
        return ''
    counts: Counter[str] = Counter()
    for member in members:
        for attribute in member.attributes:
            if attribute.name == 'class':
                counts.update(set(attribute.value.split()))
    varying = {token: count for token, count in counts.items() if count < len(members)}
    if not varying:
        return ''
    ordered = sorted(varying.items(), key=lambda item: (-item[1], item[0]))
    return ', '.join(f'{token}×{count}' for token, count in ordered)


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


def remarkable_geometry(node: DomNode) -> str | None:
    """Return a geometry fact only when the box CONTRADICTS the node's visibility claim.

    Geometry was emitted for every node at capture precision — `box=6.60938x12` on a star
    glyph — which measured 12.5% of the index across ten live pages while discriminating
    almost nothing. A layout box is evidence when it disagrees with something: a node the
    producer called visible that occupies no area, or one that sits outside the viewport it
    was measured against. Agreeing geometry is one `inspect` away, in the canonical node.
    """
    box = node.geometry
    if box is None or node.visibility is not DomVisibility.VISIBLE:
        return None
    if box.width * box.height == 0:
        return 'box=0x0 (visible, no area)'
    if not box.in_viewport:
        return f'box={round(box.width)}x{round(box.height)} (visible, outside viewport)'
    return None


def dom_summary(node: DomNode, *, max_chars: int = 160) -> str:
    """Summarize what DEVIATES for one node, without serializing the whole subtree.

    Facts are stated when they depart from the modality's default, not unconditionally. On a
    real page nearly every node is visible, so `visible;` on every line was 3.7% of the index
    spent restating the background. The defaults themselves are declared once, on the root
    entry, so a reader never has to guess whether silence means "visible" or "not checked".
    """
    parts: list[str] = []
    if node.visibility is not DomVisibility.VISIBLE:
        parts.append(node.visibility.value)
    text = ' '.join(node.text.split())
    if text:
        parts.append(f'text="{text[:max_chars]}"')
    if node.runtime is not None:
        state = _runtime_values(node.runtime)
        if state:
            parts.append('state[' + ', '.join(f'{name}={value}' for name, value in state) + ']')
    box = remarkable_geometry(node)
    if box is not None:
        parts.append(box)
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
    # A node that deviates in nothing and holds no own text would otherwise summarise to the
    # empty string, which reads as "nothing here" for a node that may hold a whole record.
    return ('; '.join(parts) or dom_subtree_text(node))[:max_chars]


def dom_member_summary(node: DomNode, *, max_chars: int = 160) -> str:
    """Summarise one expanded region member, carrying the content that tells it apart.

    `expand` is the one hop that answers "which member do I want?", so a member summary must
    discriminate. `dom_summary` reports a node's OWN text, and a record's content lives in its
    descendants — a product card summarised to `children=1` while its price sat three levels
    down. The source-HTML path has always used the member's subtree text for exactly this, and
    the divergence made DOM region expansion unable to answer questions about its own members.
    """
    content = dom_subtree_text(node)
    base = dom_summary(node, max_chars=max_chars)
    if not content or content in base:
        return base[:max_chars]
    return f'{base}; content="{content}"'[:max_chars]


def dom_declaration_label(node: DomNode, max_value_chars: int = 60) -> str:
    """Label a rendered declaration by its own first attribute — the author's key, not ours.

    Mirrors the source-HTML declaration reducer deliberately: an allowlist of `name`/`rel`/
    `charset` can only name the declarations someone thought of in advance, and source
    attribute order is the author's own statement of what identifies the element.
    """
    if not node.attributes:
        return node.tag
    first = node.attributes[0]
    return f'{node.tag}[{first.name}={" ".join(first.value.split())[:max_value_chars]}]'


def dom_declaration_summary(node: DomNode) -> str:
    """Report a declaration's remaining attributes, never its payload.

    A `<script>` body and a `<style>` sheet are payloads, not discriminants. Inlining them
    measured 31.9% of the whole index across ten live pages, in 2.8% of its entries — one
    page spent 86% of its index on them. The element stays addressed, so the payload is one
    `inspect` away; what the overview carries is what tells one declaration from another.
    """
    parts = [f'{attribute.name}="{attribute.value}"' for attribute in node.attributes[1:]]
    text = ' '.join(node.text.split())
    if text:
        parts.append(f'{len(text)} chars of content')
    return ' '.join(parts)


def dom_index_conventions(snapshot_capabilities: tuple[DomCapability, ...] = ()) -> str:
    """State the reading conventions once, so every omission below them is visible.

    An index that silently omits agreeing geometry and the word `visible` is smaller and, to a
    reader who was not told, indistinguishable from one describing a page with neither. The
    conventions are part of the reduction's meaning, so they are stated where the reduction
    starts rather than in documentation the reader does not have.

    Kept terse deliberately: this rides on the root entry, and the renderer clips any entry over
    its per-line ceiling. A convention statement that gets truncated is worse than none, because
    the reader learns half a rule.
    """
    unavailable = [
        f'{capability.kind.value} unavailable ({capability.reason})'
        for capability in snapshot_capabilities
        if not capability.available
    ]
    conventions = [
        'conventions: non-default visibility only',
        'contradicting geometry only',
        'observed/declared only when declared',
        'declarations by attribute, not payload',
    ]
    return '; '.join([*conventions, *unavailable])


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
    'SiblingIndex',
    'assign_dom_member_keys',
    'dom_anchor_census',
    'dom_attributes',
    'dom_candidate_keys',
    'dom_chain',
    'dom_declaration_label',
    'dom_declaration_summary',
    'dom_index_conventions',
    'dom_is_pass_through',
    'dom_label',
    'dom_locator',
    'dom_member_summary',
    'dom_member_variants',
    'dom_nearest_anchor',
    'dom_parents',
    'dom_region_coverage',
    'dom_skeleton_signature',
    'dom_step',
    'dom_subtree_text',
    'dom_summary',
    'node_id_from_locator',
    'remarkable_geometry',
    'sibling_index',
    'walk_dom',
]


def dom_attributes(node: DomNode) -> list[tuple[str, str]]:
    """Return one node's attributes in producer order, for the shared anchor tiers."""
    return [(attribute.name, attribute.value) for attribute in node.attributes]


def dom_anchor_census(root: DomNode) -> dict[str, int]:
    """Count anchor keys across the light and shadow trees of one rendered snapshot.

    Shadow content is included: a shadow root is a real part of the rendered document, and a key
    unique in the light tree but repeated inside a shadow root is not document-unique.
    """
    return anchoring.build_census((node.tag, dom_attributes(node)) for node in walk_dom(root))


def walk_dom(root: DomNode):
    """Yield every node of one snapshot, crossing shadow boundaries, in document order."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))
        if node.shadow_root is not None:
            stack.append(node.shadow_root)


def dom_parents(root: DomNode) -> dict[str, DomNode]:
    """Map each node id to its parent. A `DomNode` tree carries no parent pointers."""
    parents: dict[str, DomNode] = {}
    for node in walk_dom(root):
        for child in node.children:
            parents[child.node_id] = node
        if node.shadow_root is not None:
            parents[node.shadow_root.node_id] = node
    return parents


def dom_nearest_anchor(
    node: DomNode, parents: dict[str, DomNode], census: dict[str, int]
) -> tuple[DomNode, str] | None:
    """Return the nearest ancestor-or-self carrying a document-unique key, and that key.

    The DOM counterpart of the HTML walk, and the only part of anchoring that differs between
    the two: lxml elements carry parent pointers and `DomNode` does not, so ancestry comes from a
    map built once per snapshot. The tiers, the uniqueness test, and the resulting keys are the
    shared ones — identity has one definition.
    """
    current: DomNode | None = node
    while current is not None:
        key = anchoring.usable_anchor(current.tag, dom_attributes(current), census)
        if key is not None:
            return current, key
        current = parents.get(current.node_id)
    return None


@dataclass(frozen=True, slots=True)
class SiblingIndex:
    """Counts over one parent's children, so a durable step costs attributes, not siblings.

    Built once per parent. The scan-the-siblings formulation is quadratic in the width of a level,
    and width is exactly where real documents get large: the HTML Living Standard holds 10,016
    nodes at one level, where per-node sibling scans took the reduction from 7.3s to 180.3s.
    """

    tags: Counter[str]
    keyed: Counter[tuple[str, str, str]]
    """Counts of `(tag, attribute name, attribute value)` — uniqueness must be among SAME-TAG
    siblings, since that is what the emitted step `./tag[@name="value"]` selects within."""


def sibling_index(children: Sequence[DomNode]) -> SiblingIndex:
    """Build the per-parent counts a durable step decision needs."""
    tags: Counter[str] = Counter()
    keyed: Counter[tuple[str, str, str]] = Counter()
    for child in children:
        tags[child.tag] += 1
        for name, value in dom_attributes(child):
            keyed[(child.tag, name, value)] += 1
    return SiblingIndex(tags=tags, keyed=keyed)


def dom_step(node: DomNode, index: SiblingIndex) -> str | None:
    """Return a relative step selecting `node` among its siblings, or None if none is durable.

    Only two forms are minted, and both are content-addressed rather than positional: `./tag`
    when the tag is unique among its siblings, and `./tag[@name="value"]` when one attribute
    makes it so. A step that would need a sibling index is refused, because `./div[3]` is a
    positional guess wearing a durable address's clothes — insert a sibling and it silently names
    something else.
    """
    if not anchoring.SAFE_TAG.fullmatch(node.tag):
        # A shadow root is named `#shadow-root` by its producer: a real boundary that cannot be
        # written as a path step. Refusing here sends the caller to a positional address, which
        # `ref_id` then declines to give an identity — the honest outcome for a node the document
        # offers no durable way to name.
        return None
    if index.tags.get(node.tag) == 1:
        return f'./{node.tag}'
    for name, value in dom_attributes(node):
        if any(character in value for character in anchoring.LOCATOR_RESERVED):
            continue
        if index.keyed.get((node.tag, name, value)) == 1:
            return f'./{node.tag}[@{name}="{value}"]'
    return None
