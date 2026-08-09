"""Accessibility-tree semantic pruning over the versioned raw AX artifact.

Two things make this modality different from the rendered-DOM one, and both are deliberate:

* **There is no keep/drop predicate.** The DOM reducer has `_should_emit`, an enumerated list of
  what counts as important. An AX tree has already been filtered once — by the browser — and the
  nodes it *excluded* are the ones a QA reader most needs, so filtering a second time on our own
  notion of importance would drop exactly the evidence this artifact exists to carry. Everything
  the producer captured stays addressable; deciding what fits in a reader's budget is the
  renderer's job and the pager's.
* **Ignored nodes are a band, not noise.** They are emitted with the browser's own
  `ignoredReasons`, and `ax_shape_signature` treats the ignored flag as shape, so an
  `aria-hidden` control among live controls appears as its own entry instead of being averaged
  into their region's tally.
"""

from __future__ import annotations

from collections import Counter

from yosoi.observations.ax_tree import (
    assign_ax_member_keys,
    ax_anchor_census,
    ax_children,
    ax_index_conventions,
    ax_label,
    ax_locator,
    ax_member_variants,
    ax_naming_census,
    ax_nearest_anchor,
    ax_parent_of,
    ax_region_coverage,
    ax_shape_signature,
    ax_sibling_index,
    ax_step,
    ax_subtree_text,
    ax_summary,
    walk_ax,
)
from yosoi.observations.index.addressing import (
    ObservationAddress,
    anchor_address,
    element_address,
    format_address,
)
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.ax import AxNode, AxSnapshot, parse_ax_snapshot
from yosoi.observations.pruning._base import PruneCandidate, Reduction, SemanticPruner, clip
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy

AX_PRUNER_VERSION = '1'
"""First implemented version. `scaffold` refused every reduction, so nothing stored compares."""

MIN_RUN = 2
MAX_DEPTH = 24
SAMPLED_MEMBERS = 3
"""How many distinguishing member texts a collapsed region keeps inline. Mirrors DOM and HTML."""

SAMPLE_TEXT_CHARS = 40


class _Minter:
    """Mints AX addresses that start from the nearest durable ancestor.

    The AX counterpart of the rendered-DOM minter, and deliberately the same shape: one census per
    snapshot, consulted per node, falling back to the producer's node id when nothing on the way up
    is unique. That fallback still resolves exactly inside its own snapshot; it carries no anchor,
    so `ref_id` refuses it an identity rather than implying a durability the tree never offered.
    """

    def __init__(self, snapshot: AxSnapshot) -> None:
        """Build the snapshot-wide census, ancestry, and naming counts this minter consults."""
        self._by_id = snapshot.by_id
        self._census = ax_anchor_census(snapshot)
        self._siblings: dict[str, object] = {}
        # Occurrence indexes are computed once in tree order, not searched per node: the
        # per-node formulation is quadratic, and width is exactly where real trees get large.
        naming = ax_naming_census(snapshot)
        seen: Counter[tuple[str, str]] = Counter()
        self._nth: dict[str, int] = {}
        for candidate in walk_ax(snapshot):
            key = (candidate.role, ' '.join(candidate.name.split()))
            self._nth[candidate.node_id] = seen[key] if naming.get(key, 0) > 1 else 0
            seen[key] += 1

    @property
    def by_id(self) -> dict[str, AxNode]:
        """Return the snapshot's node index."""
        return self._by_id

    def nth(self, node: AxNode) -> int:
        """Return this node's occurrence index among nodes sharing its `(role, name)` pair.

        Zero unless the pair actually repeats, and `ax_label` prints it only then — it exists so a
        label stays a usable `click_by_role` target when a page has three buttons called "Delete".
        """
        return self._nth.get(node.node_id, 0)

    def label(self, node: AxNode) -> str:
        """Return the executable `role "name"` label, disambiguated when the pair repeats."""
        return ax_label(node, nth=self.nth(node))

    def _index_for(self, parent: AxNode):
        """Return the sibling counts for one parent, built once and reused."""
        cached = self._siblings.get(parent.node_id)
        if cached is None:
            cached = ax_sibling_index(ax_children(parent, self._by_id))
            self._siblings[parent.node_id] = cached
        return cached

    def _relative(self, ancestor: AxNode, node: AxNode) -> str | None:
        """Return a durable relative path from `ancestor` down to `node`, or None."""
        steps: list[str] = []
        current = node
        while current.node_id != ancestor.node_id:
            parent = ax_parent_of(current, self._by_id)
            if parent is None:
                return None
            step = ax_step(current, self._index_for(parent))
            if step is None:
                return None
            steps.append(step.removeprefix('./'))
            current = parent
        return './' + '/'.join(reversed(steps)) if steps else None

    def element(self, node: AxNode) -> ObservationAddress:
        """Return the most durable address available for one AX node."""
        found = ax_nearest_anchor(node, self._by_id, self._census)
        if found is not None:
            ancestor, key = found
            if ancestor.node_id == node.node_id:
                return anchor_address(key)
            relative = self._relative(ancestor, node)
            if relative is not None:
                return anchor_address(key, relative)
        return element_address(ax_locator(node.node_id))

    def region(self, container: AxNode, shape: str) -> ObservationAddress:
        """Return the address of a repeat container, anchored where the snapshot allows it."""
        return self.element(container).as_region(shape)


class AxPruner(SemanticPruner):
    """Deterministically reduce one raw accessibility-tree snapshot.

    Roles, accessible names, states, relationships, and the ignored band all survive; repeated
    controls that differ only in state collapse into one region that reports the state tally and
    the variants, and stay individually reachable through `expand`. The canonical artifact is
    never mutated or reserialized.
    """

    name = 'ax'
    version = AX_PRUNER_VERSION
    evidence_kind = EvidenceKind.AX_TREE

    def reduce_once(self, source: PruningInput, policy: PruningPolicy) -> Reduction:
        """Bind the self-described AX snapshot to the artifact before reduction."""
        snapshot = parse_ax_snapshot(source.data)
        if snapshot.snapshot_id != source.source.snapshot_id:
            raise ValueError('accessibility-tree payload snapshot disagrees with its artifact')
        return super().reduce_once(source, policy)

    def reduce(self, data: bytes, policy: PruningPolicy) -> Reduction:
        """Return a bounded semantic proposal over validated AX JSON bytes."""
        snapshot = parse_ax_snapshot(data)
        minter = _Minter(snapshot)
        root = snapshot.root
        root_summary = ax_summary(root, minter.by_id, max_chars=policy.max_fragment_chars)
        candidates: list[PruneCandidate] = [
            PruneCandidate(
                locator=format_address(minter.element(root)),
                label=minter.label(root),
                summary=f'{root_summary}; {ax_index_conventions(snapshot.capabilities)}',
                descends=bool(root.child_ids),
            )
        ]
        _walk(root, out=candidates, policy=policy, depth=0, minter=minter)
        return Reduction(candidates=tuple(candidates), source_items=snapshot.observed_node_count)


def _walk(node: AxNode, *, out: list[PruneCandidate], policy: PruningPolicy, depth: int, minter: _Minter) -> None:
    """Walk one node's children, collapsing contiguous same-shape runs."""
    if depth > MAX_DEPTH:
        return

    children = list(ax_children(node, minter.by_id))
    signatures = [ax_shape_signature(child, minter.by_id) for child in children]
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
        if len(members) >= MIN_RUN and run_frequency[signature] == 1:
            exemplar = _emit_region(
                container=node, members=members, shape=signature, depth=depth, out=out, policy=policy, minter=minter
            )
            _walk(exemplar, out=out, policy=policy, depth=depth + 1, minter=minter)
            continue

        for child in members:
            out.append(
                PruneCandidate(
                    locator=format_address(minter.element(child)),
                    label=minter.label(child),
                    summary=_summary_at(child, depth=depth + 1, policy=policy, minter=minter),
                    depth=depth,
                    descends=bool(child.child_ids),
                )
            )
            _walk(child, out=out, policy=policy, depth=depth + 1, minter=minter)


def _summary_at(node: AxNode, *, depth: int, policy: PruningPolicy, minter: _Minter) -> str:
    """Summarize one node, disclosing when the walk stops before its children.

    An entry at the depth ceiling otherwise reads exactly like a fully indexed leaf, and a reader
    cannot ask to inspect an omission they cannot see.
    """
    summary = ax_summary(node, minter.by_id, max_chars=policy.max_fragment_chars)
    if depth >= MAX_DEPTH and node.child_ids:
        return f'{summary}; below index depth — inspect to descend'
    return summary


def _emit_region(
    *,
    container: AxNode,
    members: tuple[AxNode, ...],
    shape: str,
    depth: int,
    out: list[PruneCandidate],
    policy: PruningPolicy,
    minter: _Minter,
) -> AxNode:
    """Emit one state-aware region and one exemplar; return the exemplar for descent."""
    region = minter.region(container, shape)
    by_id = minter.by_id
    keys = assign_ax_member_keys(members, by_id)
    observed = len(members)
    coverage = ax_region_coverage(container, members)
    summary = f'×{observed} {minter.label(members[0])}'
    # Which members, not just how many. A region reporting a bare count of 12 checkboxes forces
    # an `expand` before a reader can tell whether the run is even relevant.
    distinct = list(dict.fromkeys(text for text in (ax_subtree_text(m, by_id) for m in members) if text))
    if distinct:
        sample_chars = min(SAMPLE_TEXT_CHARS, policy.max_fragment_chars)
        shown = ', '.join(f'"{clip(text, sample_chars)}"' for text in distinct[:SAMPLED_MEMBERS])
        remainder = len(distinct) - min(SAMPLED_MEMBERS, len(distinct))
        summary += f'  {shown}' + (f' +{remainder} more' if remainder > 0 else '')
    ignored = sum(member.ignored for member in members)
    if ignored:
        summary += f'; {ignored} ignored'
    variants = ax_member_variants(members, by_id)
    # State belongs here rather than in the shape: this is where twelve checkboxes that differ
    # only in `checked` state the difference, having been collapsed for being alike in structure.
    summary += f'; variants: {variants}' if variants else '; members share every state'
    if coverage.declared is not None:
        summary += f'; observed={observed}/{coverage.declared}'
    if any(key is None for key in keys):
        summary += '; some members are positional'

    out.append(
        PruneCandidate(
            locator=format_address(region),
            label=f'{minter.label(container)} > {minter.label(members[0])}',
            summary=summary,
            coverage=coverage,
            depth=depth,
            descends=True,
        )
    )
    # An exemplar earns its slot by showing the member's STRUCTURE — what a reader would descend
    # into. For a childless member there is nothing to show and the entry would restate the region
    # line above it; the member stays reachable through `expand`, which is where members belong.
    if members[0].child_ids:
        key = keys[0]
        exemplar = region.member(key=key, ordinal=None if key is not None else 0)
        out.append(
            PruneCandidate(
                locator=format_address(exemplar),
                label=minter.label(members[0]),
                summary=f'exemplar of ×{observed}; '
                f'{ax_summary(members[0], by_id, max_chars=policy.max_fragment_chars)}',
                depth=depth,
                descends=True,
                bound_to_previous=True,
            )
        )
    return members[0]


__all__ = ['AX_PRUNER_VERSION', 'MAX_DEPTH', 'MIN_RUN', 'SAMPLED_MEMBERS', 'SAMPLE_TEXT_CHARS', 'AxPruner']
