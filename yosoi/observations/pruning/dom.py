"""Rendered-DOM semantic pruning over the versioned structured DOM artifact."""

from __future__ import annotations

from collections import Counter

from yosoi.observations.dom_tree import (
    assign_dom_member_keys,
    dom_anchor_census,
    dom_chain,
    dom_declaration_label,
    dom_declaration_summary,
    dom_index_conventions,
    dom_label,
    dom_locator,
    dom_member_variants,
    dom_nearest_anchor,
    dom_parents,
    dom_region_coverage,
    dom_skeleton_signature,
    dom_step,
    dom_subtree_text,
    dom_summary,
    sibling_index,
)
from yosoi.observations.html_tree import METADATA_CONTENT
from yosoi.observations.index.addressing import anchor_address, element_address, format_address
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.dom import DomNode, DomVisibility, parse_dom_snapshot
from yosoi.observations.pruning._base import PruneCandidate, Reduction, SemanticPruner, clip
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy

DOM_PRUNER_VERSION = '4'
"""Bumped when the reduction stopped restating defaults and stopped inlining declaration payloads.

Emitted summaries changed for every node, so views stored under version 2 are not comparable.
Addresses did not change: a stored reference still resolves.
"""

MIN_RUN = 2
MAX_DEPTH = 24
SAMPLED_MEMBERS = 3
"""How many distinguishing member texts a collapsed region keeps inline. Mirrors the HTML pruner."""

SAMPLE_TEXT_CHARS = 40
_DECLARATION_LABEL_CHARS = 60


class _Minter:
    """Mints DOM addresses that start from the nearest durable ancestor.

    The DOM counterpart of the source-HTML minter, and deliberately the same shape: one census
    per snapshot, consulted per node, falling back to the producer's node id when the document
    offers nothing durable on the way up. That fallback still resolves exactly within its own
    snapshot; it simply carries no anchor, so `ref_id` refuses it an identity rather than implying
    a stability the page never offered.
    """

    def __init__(self, root: DomNode) -> None:
        """Build the snapshot-wide census and ancestry this minter consults."""
        self._census = dom_anchor_census(root)
        self._parents = dom_parents(root)
        self._siblings: dict[str, object] = {}

    def _index_for(self, parent: DomNode):
        """Return the sibling counts for one parent, built once and reused."""
        cached = self._siblings.get(parent.node_id)
        if cached is None:
            cached = sibling_index(parent.children)
            self._siblings[parent.node_id] = cached
        return cached

    def _relative(self, ancestor: DomNode, node: DomNode) -> str | None:
        """Return a durable relative path from `ancestor` down to `node`, or None."""
        steps: list[str] = []
        current = node
        while current is not ancestor and current.node_id != ancestor.node_id:
            parent = self._parents.get(current.node_id)
            if parent is None:
                return None
            step = dom_step(current, self._index_for(parent))
            if step is None:
                return None
            steps.append(step.removeprefix('./'))
            current = parent
        return './' + '/'.join(reversed(steps)) if steps else None

    def element(self, node: DomNode):
        """Return the most durable address available for one node."""
        found = dom_nearest_anchor(node, self._parents, self._census)
        if found is not None:
            ancestor, key = found
            if ancestor.node_id == node.node_id:
                return anchor_address(key)
            relative = self._relative(ancestor, node)
            if relative is not None:
                return anchor_address(key, relative)
        return element_address(dom_locator(node.node_id))

    def region(self, container: DomNode, shape: str):
        """Return the address of a repeat container, anchored where the snapshot allows it."""
        address = self.element(container)
        return address.as_region(shape)


class DomPruner(SemanticPruner):
    """Deterministically reduce one structured rendered-DOM snapshot.

    The first beta keeps meaningful hidden state, collapses contiguous same-state sibling
    records, emits explicit shadow-root/portal facts, and reports declared-count gaps as
    incomplete coverage. It never mutates or reserializes the source artifact.

    Metadata content is partitioned out of the structural walk and described by its attributes
    rather than its payload, by the same spec-closed category the source-HTML reducers split
    on. A rendered `<script>` is a declaration wherever it was found, and inlining its source
    was the largest single cost measured in the index.
    """

    name = 'dom'
    version = DOM_PRUNER_VERSION
    evidence_kind = EvidenceKind.RENDERED_DOM

    def reduce_once(self, source: PruningInput, policy: PruningPolicy) -> Reduction:
        """Bind the self-described DOM snapshot to the artifact before reduction."""
        snapshot = parse_dom_snapshot(source.data)
        if snapshot.snapshot_id != source.source.snapshot_id:
            raise ValueError('rendered-DOM payload snapshot disagrees with its artifact')
        return super().reduce_once(source, policy)

    def reduce(self, data: bytes, policy: PruningPolicy) -> Reduction:
        """Return a bounded semantic proposal over validated DOM JSON bytes."""
        snapshot = parse_dom_snapshot(data)
        minter = _Minter(snapshot.root)
        root_summary = dom_summary(snapshot.root, max_chars=policy.max_fragment_chars)
        candidates: list[PruneCandidate] = [
            PruneCandidate(
                locator=format_address(minter.element(snapshot.root)),
                label=dom_label(snapshot.root),
                summary=f'{root_summary}; {dom_index_conventions(snapshot.capabilities)}',
                descends=bool(snapshot.root.children) or snapshot.root.shadow_root is not None,
            )
        ]
        _walk(snapshot.root, out=candidates, policy=policy, depth=0, minter=minter)
        return Reduction(candidates=tuple(candidates), source_items=snapshot.observed_node_count)


def _walk(node: DomNode, *, out: list[PruneCandidate], policy: PruningPolicy, depth: int, minter: _Minter) -> None:
    """Walk light-DOM children and explicit shadow roots without flattening boundaries."""
    if depth > MAX_DEPTH:
        return

    # Partition before structure, exactly as the source-HTML reducers do: metadata content is a
    # flat list of unique declarations, and mixing it into run detection both pollutes the
    # structural shapes and lets a script body compete with a record for an overview slot.
    label_chars = min(_DECLARATION_LABEL_CHARS, policy.max_fragment_chars)
    children: list[DomNode] = []
    for child in node.children:
        if child.tag in METADATA_CONTENT:
            out.append(
                PruneCandidate(
                    locator=format_address(minter.element(child)),
                    label=dom_declaration_label(child, label_chars),
                    summary=dom_declaration_summary(child),
                    depth=depth,
                )
            )
            continue
        children.append(child)

    signatures = [dom_skeleton_signature(child) for child in children]
    runs: list[tuple[int, int, str]] = []
    cursor = 0
    while cursor < len(children):
        signature = signatures[cursor]
        end = cursor + 1
        while end < len(children) and signatures[end] == signature:
            end += 1
        runs.append((cursor, end, signature))
        cursor = end
    run_frequency = Counter(signature for _, _, signature in runs)

    for start, end, signature in runs:
        members = tuple(children[start:end])
        collapse = len(members) >= MIN_RUN and run_frequency[signature] == 1
        if collapse:
            exemplar = _emit_region(
                container=node, members=members, shape=signature, depth=depth, out=out, policy=policy, minter=minter
            )
            _walk(exemplar, out=out, policy=policy, depth=depth + 1, minter=minter)
            continue

        for child in members:
            if _should_emit(child):
                # Fold a chain of pass-through wrappers into the one entry at its end. The chain's
                # depth is the chain START's, so a granularity cut still means "this far into the
                # document's structure" rather than "this many levels of someone's div soup".
                target, label = dom_chain(child)
                out.append(
                    PruneCandidate(
                        locator=format_address(minter.element(target)),
                        label=label,
                        summary=_summary_at(target, depth=depth + 1, policy=policy),
                        depth=depth,
                        descends=bool(target.children) or target.shadow_root is not None,
                    )
                )
                _walk(target, out=out, policy=policy, depth=depth + 1, minter=minter)

    if node.shadow_root is not None:
        shadow = node.shadow_root
        out.append(
            PruneCandidate(
                locator=format_address(minter.element(shadow)),
                label=f'{dom_label(node)} > shadow-root',
                summary=_summary_at(shadow, depth=depth + 1, policy=policy),
                depth=depth,
                descends=bool(shadow.children),
            )
        )
        _walk(shadow, out=out, policy=policy, depth=depth + 1, minter=minter)


def _summary_at(node: DomNode, *, depth: int, policy: PruningPolicy) -> str:
    """Summarize one node, disclosing when the walk stops before its children.

    An entry at the depth ceiling otherwise reads exactly like a fully indexed leaf: it
    reports its child count and says nothing about the subtree the index never visited.
    A reader cannot ask to inspect an omission they cannot see.
    """
    summary = dom_summary(node, max_chars=policy.max_fragment_chars)
    if depth >= MAX_DEPTH and (node.children or node.shadow_root is not None):
        return f'{summary}; below index depth — inspect to descend'
    return summary


def _emit_region(
    *,
    container: DomNode,
    members: tuple[DomNode, ...],
    shape: str,
    depth: int,
    out: list[PruneCandidate],
    policy: PruningPolicy,
    minter: _Minter,
) -> DomNode:
    """Emit one state-aware region and one exemplar; return the exemplar for descent."""
    region = minter.region(container, shape)
    keys = assign_dom_member_keys(members)
    state_counts = Counter(_member_state(member) for member in members)
    state_text = ', '.join(f'{state}×{count}' for state, count in sorted(state_counts.items()))
    observed = len(members)
    coverage = dom_region_coverage(container, members)
    summary = f'×{observed} {dom_label(members[0])}'
    # Which members, not just how many. A region that reports a bare count of 50 list items
    # forces an expand before the reader can tell whether the run is even relevant.
    distinct = list(dict.fromkeys(text for text in (dom_subtree_text(member) for member in members) if text))
    if distinct:
        sample_chars = min(SAMPLE_TEXT_CHARS, policy.max_fragment_chars)
        shown = ', '.join(f'"{clip(text, sample_chars)}"' for text in distinct[:SAMPLED_MEMBERS])
        remainder = len(distinct) - min(SAMPLED_MEMBERS, len(distinct))
        summary += f'  {shown}' + (f' +{remainder} more' if remainder > 0 else '')
    summary += f'; states={state_text or "unknown"}'
    variants = dom_member_variants(members)
    if variants:
        summary += f'; variants: {variants}'
    # Only a DECLARED total is worth a line. No total is the norm on real pages — it was stated
    # on essentially every region across ten live captures — and `coverage.declared is None`
    # already carries it for any consumer that needs to branch on it.
    if coverage.declared is not None:
        summary += f'; observed={observed}/{coverage.declared}'
    if any(key is None for key in keys):
        summary += '; some members are positional'

    out.append(
        PruneCandidate(
            locator=format_address(region),
            label=f'{dom_label(container)} > {dom_label(members[0])}',
            summary=summary,
            coverage=coverage,
            depth=depth,
            descends=True,
        )
    )
    # An exemplar earns its slot by showing the member's STRUCTURE — what a reader would have to
    # descend into. For a childless member there is nothing to show, and the entry restated the
    # region line it sits under: 135 such entries and 4.5% of the index across ten live pages.
    # The member stays reachable through `expand`, which is where members belong.
    if members[0].children or members[0].shadow_root is not None:
        key = keys[0]
        exemplar = region.member(key=key, ordinal=None if key is not None else 0)
        out.append(
            PruneCandidate(
                locator=format_address(exemplar),
                label=dom_label(members[0]),
                summary=f'exemplar of ×{observed}; {dom_summary(members[0], max_chars=policy.max_fragment_chars)}',
                depth=depth,
                descends=bool(members[0].children) or members[0].shadow_root is not None,
                bound_to_previous=True,
            )
        )
    return members[0]


def _member_state(node: DomNode) -> str:
    """Return a compact state bucket used only for region summaries."""
    runtime = node.runtime
    if runtime is not None and runtime.checked is True:
        return 'checked'
    if node.visibility is not DomVisibility.VISIBLE:
        return node.visibility.value
    return 'visible'


def _should_emit(node: DomNode) -> bool:
    """Keep visible nodes and hidden/offscreen nodes that carry recoverable meaning."""
    if node.visibility in {DomVisibility.VISIBLE, DomVisibility.UNKNOWN}:
        return True
    if node.text.strip() or node.runtime is not None or node.portal_target_id is not None:
        return True
    if any(attribute.name in {'id', 'role'} or attribute.name.startswith('data-') for attribute in node.attributes):
        return True
    return any(_should_emit(child) for child in node.children) or node.shadow_root is not None


__all__ = ['DOM_PRUNER_VERSION', 'MAX_DEPTH', 'MIN_RUN', 'SAMPLED_MEMBERS', 'SAMPLE_TEXT_CHARS', 'DomPruner']
