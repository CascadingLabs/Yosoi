"""Optional bounded exact Zhang-Shasha tree edit retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

TREE_EDIT_METHOD = "zss_ordered_tree_edit_reference"
MAX_TREE_NODES_HARD = 64
DEFAULT_MAX_TREE_NODES = 32
DEFAULT_MAX_PAIR_COMPARISONS = 5_000
DEFAULT_MAX_ESTIMATED_WORK = 5_000_000
TREE_EDIT_CACHE_SCHEMA = 1

METHOD_METADATA: dict[str, dict[str, Any]] = {
    TREE_EDIT_METHOD: {
        "family": "ordered_tree_edit",
        "comparison": "candidate prepared subtree to each seed-reference subtree",
        "reference_aggregation": "max",
        "algorithm": (
            "exact Zhang-Shasha ordered labeled-tree edit distance via optional zss"
        ),
        "edit_costs": {
            "insert": 1,
            "delete": 1,
            "relabel_same": 0,
            "relabel_different": 1,
        },
        "similarity": (
            "1 - exact_distance / (candidate_node_count + reference_node_count)"
        ),
        "max_tree_nodes_default": DEFAULT_MAX_TREE_NODES,
        "max_tree_nodes_hard": MAX_TREE_NODES_HARD,
        "max_pair_comparisons_default": DEFAULT_MAX_PAIR_COMPARISONS,
        "max_estimated_work_default": DEFAULT_MAX_ESTIMATED_WORK,
        "work_estimate": "n*m*min(depth,leaves)_candidate*min(depth,leaves)_reference",
        "work_estimate_note": "asymptotic budgeting proxy, not measured CPU operations",
        "input_schema": "advanced_methods.prepare_case candidate['subtree']",
        "input_content": (
            "ordered generic labels, child order and parent "
            "structure only; no node IDs, text, or attribute "
            "values"
        ),
        "cache": "exact normalized tree-pair distance cached within one scorer call",
        "unavailable_dependency": (
            "raises/diagnoses optional zss package absence; no fallback metric"
        ),
        "incomplete_policy": (
            "budget or subtree omissions are diagnosed; list API "
            "raises instead of returning partial scores as valid"
        ),
    }
}

METHODS = list(METHOD_METADATA)

_ELEMENT_LABEL = re.compile(
    r"element:([A-Za-z0-9:_.-]+)\[((?:[A-Za-z0-9:_.-]+(?:,[A-Za-z0-9:_.-]+)*)?)\]"
)
_NODE_LABEL = re.compile(r"node:([A-Za-z0-9:_.-]+)")


class TreeEditError(RuntimeError):
    """Base error carrying diagnostics for an unavailable or incomplete score."""

    def __init__(self, message: str, diagnostics: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics)


class TreeEditUnavailable(TreeEditError):
    """Raised when the optional ``zss`` implementation is not installed."""


class TreeEditIncompleteInput(TreeEditError):
    """Raised when bounded input trees cannot all be compared completely."""


class TreeEditBudgetExceeded(TreeEditIncompleteInput):
    """Raised when a comparison or total-work budget prevents full ranking."""


@dataclass(frozen=True)
class _Shape:
    label: str
    children: tuple[_Shape, ...]
    canonical: tuple[Any, ...]
    node_count: int
    depth: int
    leaves: int


def _load_zss():
    """Load the optional exact tree-edit implementation only when needed."""
    try:
        import zss
    except ImportError as error:
        raise TreeEditUnavailable(
            "exact tree edit requires the optional 'zss' package; install it in the "
            "experiment environment, or use ordered_tree_fragment_jaccard for the "
            "separate bounded fragment signal",
            {"status": "unavailable", "dependency": "zss"},
        ) from error
    node_type = getattr(zss, "Node", None)
    distance = getattr(zss, "distance", None)
    if node_type is None or not callable(distance):
        raise TreeEditUnavailable(
            "installed 'zss' does not expose Node and distance",
            {"status": "unavailable", "dependency": "zss", "reason": "API mismatch"},
        )
    try:
        zss_version = version("zss")
    except PackageNotFoundError:
        zss_version = "unknown"
    return node_type, distance, zss_version


def _safe_label(value: Any) -> str | None:
    """Accept only the generic label grammar emitted by advanced.prepare_case."""
    if not isinstance(value, str):
        return None
    if value == "text":
        return value
    element = _ELEMENT_LABEL.fullmatch(value)
    if element is not None:
        tag, raw_names = element.groups()
        names = sorted(set(name.casefold() for name in raw_names.split(",") if name))
        return f"element:{tag.casefold()}[{','.join(names)}]"
    node = _NODE_LABEL.fullmatch(value)
    if node is not None:
        return f"node:{node.group(1).casefold()}"
    # Reject free text and name=value encodings to keep IDs, text and attribute
    # values outside the edit labels and pair cache keys.
    return None


def _shape_from_candidate(
    candidate: Mapping[str, Any], max_tree_nodes: int
) -> tuple[_Shape | None, str]:
    subtree = candidate.get("subtree")
    if not isinstance(subtree, Mapping):
        return None, "missing_subtree"
    if subtree.get("complete") is not True:
        status = subtree.get("status")
        return None, str(status) if isinstance(status, str) else "incomplete_subtree"
    nodes = subtree.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None, "empty_subtree"
    if len(nodes) > max_tree_nodes:
        return None, "tree_node_limit"

    labels: list[str] = []
    parents: list[int | None] = []
    positions: list[int] = []
    sibling_counts: list[int] = []
    children_by_parent: list[list[tuple[int, int]]] = [[] for _ in range(len(nodes))]

    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            return None, "invalid_tree_node"
        label = _safe_label(node.get("label"))
        parent = node.get("parent")
        position = node.get("position")
        sibling_count = node.get("sibling_count")
        if label is None:
            return None, "unsafe_or_invalid_label"
        if not _is_int(position) or not _is_int(sibling_count):
            return None, "invalid_sibling_order"
        if position < 0 or sibling_count < 1 or position >= sibling_count:
            return None, "invalid_sibling_order"
        if index == 0:
            if parent is not None:
                return None, "invalid_root_parent"
        elif not _is_int(parent) or parent < 0 or parent >= index:
            return None, "invalid_parent_index"
        labels.append(label)
        parents.append(parent)
        positions.append(position)
        sibling_counts.append(sibling_count)
        if index > 0:
            children_by_parent[parent].append((position, index))

    for children in children_by_parent:
        if not children:
            continue
        child_positions = sorted(position for position, _ in children)
        declared_counts = {sibling_counts[child_index] for _, child_index in children}
        if declared_counts != {len(children)} or child_positions != list(
            range(len(children))
        ):
            return None, "incomplete_or_invalid_sibling_order"

    def build(index: int) -> _Shape:
        child_shapes = tuple(
            build(child_index) for _, child_index in sorted(children_by_parent[index])
        )
        canonical = (labels[index], tuple(child.canonical for child in child_shapes))
        node_count = 1 + sum(child.node_count for child in child_shapes)
        depth = 1 + max((child.depth for child in child_shapes), default=0)
        leaves = 1 if not child_shapes else sum(child.leaves for child in child_shapes)
        return _Shape(
            label=labels[index],
            children=child_shapes,
            canonical=canonical,
            node_count=node_count,
            depth=depth,
            leaves=leaves,
        )

    return build(0), "complete"


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _work_estimate(left: _Shape, right: _Shape) -> int:
    """Use the Zhang-Shasha size/depth/leaves complexity proxy for budgeting."""
    left_factor = min(left.depth, left.leaves)
    right_factor = min(right.depth, right.leaves)
    return left.node_count * right.node_count * left_factor * right_factor


def _zss_node(shape: _Shape, node_type):
    return node_type(
        shape.label, [_zss_node(child, node_type) for child in shape.children]
    )


def _exact_distance(left: _Shape, right: _Shape, node_type, distance_function) -> float:
    left_root = _zss_node(left, node_type)
    right_root = _zss_node(right, node_type)
    distance = distance_function(
        left_root,
        right_root,
        get_children=lambda node: node.children,
        insert_cost=lambda _node: 1,
        remove_cost=lambda _node: 1,
        update_cost=lambda old, new: 0 if old.label == new.label else 1,
    )
    value = float(distance)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError("zss returned an invalid tree distance")
    return value


def _similarity(distance: float, left: _Shape, right: _Shape) -> float:
    denominator = left.node_count + right.node_count
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - distance / denominator))


def score_candidates_with_diagnostics(
    method: str,
    query: dict[str, Any],
    candidates: list[dict[str, Any]],
    references: list[dict[str, Any]],
    representation: str = "context",
    semantic_vectors: dict[str, Sequence[float]] | None = None,
    *,
    max_tree_nodes: int = DEFAULT_MAX_TREE_NODES,
    max_pair_comparisons: int = DEFAULT_MAX_PAIR_COMPARISONS,
    max_total_estimated_work: int = DEFAULT_MAX_ESTIMATED_WORK,
) -> tuple[list[float], dict[str, Any]]:
    """Score candidates with bounded exact TED and return explicit completeness data.

    ``query``, ``representation`` and ``semantic_vectors`` are accepted for API
    compatibility but ignored: this is a reference-only structure metric. Pair
    distances are cached by normalized ordered tree shape within this call. The
    cache keys contain generic labels and child order, never candidate IDs, text,
    or attribute values.
    """
    del query, representation, semantic_vectors
    if method not in METHOD_METADATA:
        raise ValueError(f"unknown tree-edit method: {method}")
    if not _is_int(max_tree_nodes) or not 1 <= max_tree_nodes <= MAX_TREE_NODES_HARD:
        raise ValueError(f"max_tree_nodes must be between 1 and {MAX_TREE_NODES_HARD}")
    if not _is_int(max_pair_comparisons) or max_pair_comparisons < 1:
        raise ValueError("max_pair_comparisons must be a positive integer")
    if not _is_int(max_total_estimated_work) or max_total_estimated_work < 1:
        raise ValueError("max_total_estimated_work must be a positive integer")

    scores = [0.0] * len(candidates)
    candidate_shapes: list[_Shape | None] = []
    candidate_statuses: Counter[str] = Counter()
    reference_shapes: list[_Shape | None] = []
    reference_statuses: Counter[str] = Counter()
    for candidate in candidates:
        shape, status = _shape_from_candidate(candidate, max_tree_nodes)
        candidate_shapes.append(shape)
        candidate_statuses[status] += 1
    for reference in references:
        shape, status = _shape_from_candidate(reference, max_tree_nodes)
        reference_shapes.append(shape)
        reference_statuses[status] += 1

    diagnostics: dict[str, Any] = {
        "method": method,
        "status": "complete",
        "candidate_count": len(candidates),
        "reference_count": len(references),
        "candidate_shape_statuses": dict(candidate_statuses),
        "reference_shape_statuses": dict(reference_statuses),
        "possible_pair_slots": len(candidates) * len(references),
        "valid_tree_pair_slots": sum(shape is not None for shape in candidate_shapes)
        * sum(shape is not None for shape in reference_shapes),
        "unmatched_pairs": 0,
        "pair_slots_visited": 0,
        "pairs_skipped_by_comparison_budget": 0,
        "pairs_skipped_by_work_budget": 0,
        "exact_distance_calls": 0,
        "distance_cache_hits": 0,
        "estimated_work_units": 0,
        "normalization": "1 - unit_edit_distance / (candidate_nodes + reference_nodes)",
        "work_estimate_note": (
            "Zhang-Shasha asymptotic proxy; not measured CPU operations"
        ),
        "edit_costs": {"insert": 1, "delete": 1, "same_label": 0, "different_label": 1},
        "limits": {
            "max_tree_nodes": max_tree_nodes,
            "hard_max_tree_nodes": MAX_TREE_NODES_HARD,
            "max_pair_comparisons": max_pair_comparisons,
            "max_total_estimated_work": max_total_estimated_work,
        },
        "distance_cache_identity": (
            "normalized generic ordered tree shape; cache is per call"
        ),
    }
    diagnostics["unmatched_candidates"] = sum(
        shape is None for shape in candidate_shapes
    )
    diagnostics["unmatched_references"] = sum(
        shape is None for shape in reference_shapes
    )
    if not candidates or not references:
        diagnostics["reason"] = "empty candidates or no references"
        return scores, diagnostics

    valid_candidates = [
        (index, shape)
        for index, shape in enumerate(candidate_shapes)
        if shape is not None
    ]
    valid_references = [
        (index, shape)
        for index, shape in enumerate(reference_shapes)
        if shape is not None
    ]
    diagnostics["unmatched_pairs"] = (
        diagnostics["possible_pair_slots"] - diagnostics["valid_tree_pair_slots"]
    )
    if not valid_candidates or not valid_references:
        diagnostics["status"] = "partial"
        return scores, diagnostics

    pair_cache: dict[tuple[Any, Any, int], tuple[float, float]] = {}
    valid_pairs = len(valid_candidates) * len(valid_references)
    budget_status: str | None = None
    try:
        node_type, distance_function, zss_version = _load_zss()
    except TreeEditUnavailable as error:
        diagnostics.update(error.diagnostics)
        diagnostics["status"] = "unavailable"
        diagnostics["reason"] = str(error)
        return scores, diagnostics
    diagnostics["zss_version"] = zss_version

    candidate_has_score = [False] * len(candidates)
    stop = False
    for candidate_index, left in valid_candidates:
        if stop:
            break
        for _reference_index, right in valid_references:
            if diagnostics["pair_slots_visited"] >= max_pair_comparisons:
                budget_status = "comparison_budget_exhausted"
                diagnostics["pairs_skipped_by_comparison_budget"] = (
                    valid_pairs - diagnostics["pair_slots_visited"]
                )
                stop = True
                break

            key_left = left.canonical
            key_right = right.canonical
            if key_left <= key_right:
                cache_key = (key_left, key_right, TREE_EDIT_CACHE_SCHEMA)
            else:
                cache_key = (key_right, key_left, TREE_EDIT_CACHE_SCHEMA)

            cached = pair_cache.get(cache_key)
            if cached is None:
                estimate = _work_estimate(left, right)
                if (
                    diagnostics["estimated_work_units"] + estimate
                    > max_total_estimated_work
                ):
                    budget_status = "total_work_budget_exhausted"
                    diagnostics["pairs_skipped_by_work_budget"] = (
                        valid_pairs - diagnostics["pair_slots_visited"]
                    )
                    stop = True
                    break
                try:
                    distance = _exact_distance(
                        left, right, node_type, distance_function
                    )
                except Exception as error:
                    diagnostics.update(
                        {
                            "status": "comparison_error",
                            "error": f"{type(error).__name__}: {error}",
                        }
                    )
                    return scores, diagnostics
                similarity = _similarity(distance, left, right)
                cached = (distance, similarity)
                pair_cache[cache_key] = cached
                diagnostics["exact_distance_calls"] += 1
                diagnostics["estimated_work_units"] += estimate
            else:
                diagnostics["distance_cache_hits"] += 1

            diagnostics["pair_slots_visited"] += 1
            candidate_has_score[candidate_index] = True
            scores[candidate_index] = max(scores[candidate_index], cached[1])

    diagnostics["scored_candidates"] = sum(candidate_has_score)
    if budget_status is not None:
        diagnostics["status"] = "budget_exhausted"
        diagnostics["budget_reason"] = budget_status
    elif diagnostics["unmatched_candidates"] or diagnostics["unmatched_references"]:
        diagnostics["status"] = "partial"
    return scores, diagnostics


def score_candidates(
    method: str,
    query: dict[str, Any],
    candidates: list[dict[str, Any]],
    references: list[dict[str, Any]],
    representation: str = "context",
    semantic_vectors: dict[str, Sequence[float]] | None = None,
    *,
    max_tree_nodes: int = DEFAULT_MAX_TREE_NODES,
    max_pair_comparisons: int = DEFAULT_MAX_PAIR_COMPARISONS,
    max_total_estimated_work: int = DEFAULT_MAX_ESTIMATED_WORK,
) -> list[float]:
    """Return max-reference exact tree-edit similarities or raise on incompleteness."""
    scores, diagnostics = score_candidates_with_diagnostics(
        method,
        query,
        candidates,
        references,
        representation,
        semantic_vectors,
        max_tree_nodes=max_tree_nodes,
        max_pair_comparisons=max_pair_comparisons,
        max_total_estimated_work=max_total_estimated_work,
    )
    status = diagnostics["status"]
    if status == "unavailable":
        raise TreeEditUnavailable(
            diagnostics.get("reason", "zss is unavailable"), diagnostics
        )
    if status == "budget_exhausted":
        raise TreeEditBudgetExceeded(
            f"tree-edit score is incomplete: {diagnostics.get('budget_reason')}",
            diagnostics,
        )
    if status != "complete":
        raise TreeEditIncompleteInput(
            f"tree-edit score is incomplete: {status}", diagnostics
        )
    return scores
