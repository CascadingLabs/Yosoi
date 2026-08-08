"""Rendered-DOM semantic pruning over the versioned structured DOM artifact."""

from __future__ import annotations

from collections import Counter

from yosoi.observations.dom_tree import (
    assign_dom_member_keys,
    dom_label,
    dom_locator,
    dom_skeleton_signature,
    dom_summary,
)
from yosoi.observations.index.addressing import element_address, format_address, region_address
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.dom import DomNode, DomVisibility, parse_dom_snapshot
from yosoi.observations.models.view import RegionCoverage
from yosoi.observations.pruning._base import PruneCandidate, Reduction, SemanticPruner
from yosoi.observations.pruning.protocol import PruningPolicy

DOM_PRUNER_VERSION = '1'
MIN_RUN = 2
MAX_DEPTH = 24


class DomPruner(SemanticPruner):
    """Deterministically reduce one structured rendered-DOM snapshot.

    The first beta keeps meaningful hidden state, collapses contiguous same-state sibling
    records, emits explicit shadow-root/portal facts, and reports declared-count gaps as
    incomplete coverage. It never mutates or reserializes the source artifact.
    """

    name = 'dom'
    version = DOM_PRUNER_VERSION
    evidence_kind = EvidenceKind.RENDERED_DOM

    def reduce(self, data: bytes, policy: PruningPolicy) -> Reduction:
        """Return a bounded semantic proposal over validated DOM JSON bytes."""
        snapshot = parse_dom_snapshot(data)
        candidates: list[PruneCandidate] = [
            PruneCandidate(
                locator=format_address(element_address(dom_locator(snapshot.root.node_id))),
                label=dom_label(snapshot.root),
                summary=dom_summary(snapshot.root, max_chars=policy.max_fragment_chars),
            )
        ]
        _walk(snapshot.root, out=candidates, policy=policy, depth=0)
        return Reduction(candidates=tuple(candidates), source_items=snapshot.observed_node_count)


def _walk(node: DomNode, *, out: list[PruneCandidate], policy: PruningPolicy, depth: int) -> None:
    """Walk light-DOM children and explicit shadow roots without flattening boundaries."""
    if depth > MAX_DEPTH:
        return

    children = node.children
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
        members = children[start:end]
        collapse = len(members) >= MIN_RUN and run_frequency[signature] == 1
        if collapse:
            exemplar = _emit_region(
                container=node,
                members=members,
                shape=signature,
                declared_count=node.declared_count if len(runs) == 1 else None,
                out=out,
                policy=policy,
            )
            _walk(exemplar, out=out, policy=policy, depth=depth + 1)
            continue

        for child in members:
            if _should_emit(child):
                out.append(
                    PruneCandidate(
                        locator=format_address(element_address(dom_locator(child.node_id))),
                        label=dom_label(child),
                        summary=dom_summary(child, max_chars=policy.max_fragment_chars),
                    )
                )
                _walk(child, out=out, policy=policy, depth=depth + 1)

    if node.shadow_root is not None:
        shadow = node.shadow_root
        out.append(
            PruneCandidate(
                locator=format_address(element_address(dom_locator(shadow.node_id))),
                label=f'{dom_label(node)} > shadow-root',
                summary=dom_summary(shadow, max_chars=policy.max_fragment_chars),
            )
        )
        _walk(shadow, out=out, policy=policy, depth=depth + 1)


def _emit_region(
    *,
    container: DomNode,
    members: tuple[DomNode, ...],
    shape: str,
    declared_count: int | None,
    out: list[PruneCandidate],
    policy: PruningPolicy,
) -> DomNode:
    """Emit one state-aware region and one exemplar; return the exemplar for descent."""
    region = region_address(dom_locator(container.node_id), shape)
    keys = assign_dom_member_keys(members)
    state_counts = Counter(_member_state(member) for member in members)
    state_text = ', '.join(f'{state}×{count}' for state, count in sorted(state_counts.items()))
    observed = len(members)
    complete = declared_count is not None and declared_count == observed
    coverage = RegionCoverage(observed=observed, declared=declared_count, complete=complete)
    summary = f'×{observed} {dom_label(members[0])}; states={state_text or "unknown"}'
    if declared_count is not None:
        summary += f'; observed={observed}/{declared_count}'
    else:
        summary += '; declared count unavailable'
    if any(key is None for key in keys):
        summary += '; some members are positional'

    out.append(
        PruneCandidate(
            locator=format_address(region),
            label=f'{dom_label(container)} > {dom_label(members[0])}',
            summary=summary,
            coverage=coverage,
        )
    )
    key = keys[0]
    exemplar = region.member(key=key, ordinal=None if key is not None else 0)
    out.append(
        PruneCandidate(
            locator=format_address(exemplar),
            label=dom_label(members[0]),
            summary=f'exemplar of ×{observed}; {dom_summary(members[0], max_chars=policy.max_fragment_chars)}',
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


__all__ = ['DOM_PRUNER_VERSION', 'MAX_DEPTH', 'MIN_RUN', 'DomPruner']
