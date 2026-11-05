"""Bounded structural retrieval experiments independent of the frozen runner."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

MAX_CWS_FEATURES = 512
CWS_SEED = b"yosoi-product-retrieval-cws-v1"
MAX_DOCUMENT_NODES = 20_000
MAX_DOCUMENT_DEPTH = 256
MAX_CANDIDATES = 5_000
MAX_SUBTREE_NODES = 128
MAX_TOTAL_SUBTREE_NODES = 100_000
MAX_TREE_FRAGMENT_EDGES = 4

ADVANCED_METHODS: dict[str, dict[str, Any]] = {
    "weighted_jaccard_exact": {
        "family": "weighted_structure",
        "comparison": "candidate structural feature weights to each seed reference",
        "reference_aggregation": "max",
        "estimator": "exact weighted Jaccard control",
        "feature_weights": "exact path 3.0; motifs 1.0; tag 0.75; attribute names 0.5",
        "empty_features": "score zero",
    },
    "weighted_minhash_64": {
        "family": "weighted_structure",
        "comparison": "candidate sketch to each seed reference sketch",
        "reference_aggregation": "max",
        "estimator": "fraction of equal consistent weighted samples",
        "sample_width": 64,
        "feature_weights": "same structural feature map as weighted_jaccard_exact",
        "theoretical_target": (
            "weighted Jaccard collision probability under independent CWS draws"
        ),
        "implementation_note": (
            "deterministic hash-derived pseudorandom draws; one fixed sketch per input"
        ),
        "max_nonzero_features": MAX_CWS_FEATURES,
        "empty_features": "score zero",
    },
    "weighted_minhash_128": {
        "family": "weighted_structure",
        "comparison": "candidate sketch to each seed reference sketch",
        "reference_aggregation": "max",
        "estimator": "fraction of equal consistent weighted samples",
        "sample_width": 128,
        "feature_weights": "same structural feature map as weighted_jaccard_exact",
        "theoretical_target": (
            "weighted Jaccard collision probability under independent CWS draws"
        ),
        "implementation_note": (
            "deterministic hash-derived pseudorandom draws; one fixed sketch per input"
        ),
        "max_nonzero_features": MAX_CWS_FEATURES,
        "empty_features": "score zero",
    },
    "ordered_tree_fragment_jaccard": {
        "family": "tree_structure",
        "comparison": "candidate bounded subtree fragments to each seed reference",
        "reference_aggregation": "max",
        "algorithm": "multiset Jaccard over ordered ancestor-path fragments",
        "interpretation": (
            "partial tree-fragment alignment; not full tree edit distance"
        ),
        "requires": "complete candidate['subtree'] from prepare_case or caller",
        "max_subtree_nodes": MAX_SUBTREE_NODES,
        "max_fragment_edges": MAX_TREE_FRAGMENT_EDGES,
        "fragment_scope": (
            "all local ancestor-path windows up to the configured edge limit"
        ),
        "incomplete_or_unmatched": (
            "score zero; inspect prepare_case diagnostics and candidate status"
        ),
    },
}


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _normalized(value: Any) -> str:
    return _string(value).strip().casefold()


def _path_tags(candidate: Mapping[str, Any]) -> list[str]:
    path = candidate.get("path")
    if not isinstance(path, Sequence) or isinstance(path, (str, bytes)):
        return []
    return [tag for item in path if (tag := _normalized(item))]


def _candidate_motifs(candidate: Mapping[str, Any]) -> list[str]:
    motifs = candidate.get("motifs")
    if not isinstance(motifs, Sequence) or isinstance(motifs, (str, bytes)):
        return []
    return [motif for item in motifs if (motif := _normalized(item))]


def _attribute_names(candidate: Mapping[str, Any]) -> list[str]:
    attributes = candidate.get("attributes")
    if not isinstance(attributes, Mapping):
        return []
    return sorted(name for key in attributes if (name := _normalized(key)))


def structural_feature_weights(candidate: Mapping[str, Any]) -> dict[str, float]:
    """Return the shared sparse structural vector used by exact Jaccard and CWS.

    Attribute values, candidate IDs, node IDs, text, and ancestor IDs are omitted.
    """
    features: dict[str, float] = {}
    path = _path_tags(candidate)
    if path:
        features[f"path:{'/'.join(path)}"] = 3.0
    tag = _normalized(candidate.get("tag"))
    if tag:
        features[f"tag:{tag}"] = 0.75
    for motif in set(_candidate_motifs(candidate)):
        features[f"motif:{motif}"] = 1.0
    for name in set(_attribute_names(candidate)):
        features[f"attribute:{name}"] = 0.5
    return features


def weighted_jaccard(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    """Compute the exact weighted Jaccard similarity of nonnegative sparse maps."""
    left_values = _validated_weights(left)
    right_values = _validated_weights(right)
    keys = set(left_values) | set(right_values)
    denominator = sum(
        max(left_values.get(key, 0.0), right_values.get(key, 0.0)) for key in keys
    )
    if denominator == 0.0:
        return 0.0
    numerator = sum(
        min(left_values.get(key, 0.0), right_values.get(key, 0.0)) for key in keys
    )
    return numerator / denominator


def _validated_weights(weights: Mapping[str, float]) -> dict[str, float]:
    result: dict[str, float] = {}
    for feature, raw_weight in weights.items():
        if not isinstance(feature, str) or not feature:
            raise ValueError("sparse feature keys must be non-empty strings")
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError("sparse feature weights must be finite and nonnegative")
        if weight > 0.0:
            result[feature] = weight
    return result


def _uniform_open(word: int) -> float:
    """Map an integer word to a stable 53-bit floating value strictly inside (0,1)."""
    mantissa = word >> 11
    value = (mantissa + 0.5) / (1 << 53)
    return min(math.nextafter(1.0, 0.0), max(1.0 / (1 << 53), value))


def _cws_uniforms(
    feature: str, sample_index: int
) -> tuple[float, float, float, float, float]:
    encoded = feature.encode("utf-8")
    payload = (
        CWS_SEED
        + sample_index.to_bytes(4, "big", signed=False)
        + len(encoded).to_bytes(4, "big", signed=False)
        + encoded
    )
    digest = hashlib.blake2b(payload, digest_size=40, person=b"ys-cws-v1").digest()
    uniforms = tuple(
        _uniform_open(int.from_bytes(digest[offset : offset + 8], "big"))
        for offset in range(0, 40, 8)
    )
    return uniforms  # type: ignore[return-value]


def _cws_signature(
    weights: Mapping[str, float], width: int
) -> tuple[tuple[str, int], ...]:
    """Build an Ioffe-style consistent weighted sample signature.

    Each sample uses r,c ~ Gamma(2,1) and beta ~ Uniform(0,1), with
    t=floor(log(w)/r+beta), y=exp(r(t-beta)), and a=c/(y exp(r)). The
    argmin of a returns (feature,t); equal pairs are the CWS collision event.
    Hash-derived draws make this experiment repeatable, so the returned sketch
    is one deterministic pseudorandom realization rather than a fresh random
    estimate on each call.
    """
    if width not in (64, 128):
        raise ValueError("consistent weighted sample width must be 64 or 128")
    values = _validated_weights(weights)
    if len(values) > MAX_CWS_FEATURES:
        raise ValueError(
            f"CWS feature budget exceeded: {len(values)} > {MAX_CWS_FEATURES}"
        )
    if not values:
        return ()

    ordered_items = sorted(values.items())
    signature: list[tuple[str, int]] = []
    for sample_index in range(width):
        best: tuple[float, str, int] | None = None
        for feature, weight in ordered_items:
            u1, u2, u3, u4, beta = _cws_uniforms(feature, sample_index)
            r = -math.log(u1) - math.log(u2)
            c = -math.log(u3) - math.log(u4)
            t = math.floor(math.log(weight) / r + beta)
            log_y = r * (t - beta)
            log_a = math.log(c) - log_y - r
            proposal = (log_a, feature, t)
            if best is None or proposal < best:
                best = proposal
        if best is None:
            return ()
        signature.append((best[1], best[2]))
    return tuple(signature)


def _reference_max(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    similarity,
) -> list[float]:
    if not references:
        return [0.0] * len(candidates)
    return [
        max((similarity(candidate, reference) for reference in references), default=0.0)
        for candidate in candidates
    ]


def _exact_structural_scores(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
) -> list[float]:
    return _reference_max(
        candidates,
        references,
        lambda candidate, reference: weighted_jaccard(
            structural_feature_weights(candidate),
            structural_feature_weights(reference),
        ),
    )


def _minhash_scores(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    width: int,
) -> list[float]:
    candidate_signatures = [
        _cws_signature(structural_feature_weights(candidate), width)
        for candidate in candidates
    ]
    reference_signatures = [
        _cws_signature(structural_feature_weights(reference), width)
        for reference in references
    ]
    if not reference_signatures:
        return [0.0] * len(candidates)
    return [
        max(
            (
                sum(
                    left == right
                    for left, right in zip(signature, reference, strict=True)
                )
                / width
                if signature and reference
                else 0.0
                for reference in reference_signatures
            ),
            default=0.0,
        )
        for signature in candidate_signatures
    ]


def _node_label(node: Mapping[str, Any]) -> str:
    kind = _normalized(node.get("kind"))
    if kind == "element":
        tag = _normalized(node.get("tag_name")) or "unknown"
        raw_attributes = node.get("attributes", [])
        names = (
            sorted(
                {
                    name
                    for attribute in raw_attributes
                    if isinstance(attribute, Mapping)
                    and (name := _normalized(attribute.get("name")))
                }
            )
            if isinstance(raw_attributes, Sequence)
            and not isinstance(raw_attributes, (str, bytes))
            else []
        )
        return f"element:{tag}[{','.join(names)}]"
    if kind == "text":
        return "text"
    return f"node:{kind or 'unknown'}"


def _index_case_document(
    document: Mapping[str, Any],
    *,
    max_document_nodes: int,
    max_document_depth: int,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[str]]]:
    raw_nodes = document.get("nodes")
    root = document.get("root")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("case document has no node list")
    nodes: dict[str, Mapping[str, Any]] = {}
    for node in raw_nodes:
        if not isinstance(node, Mapping) or "id" not in node:
            raise ValueError("case document contains an invalid node")
        key = str(node["id"])
        if key in nodes:
            raise ValueError("case document has duplicate stringified node IDs")
        nodes[key] = node
    if len(nodes) > max_document_nodes:
        raise ValueError("case document exceeds the node-validation budget")
    root_key = str(root)
    if root_key not in nodes:
        raise ValueError("case document root is missing")

    children_by_parent: dict[str, list[str]] = {}
    for key, node in nodes.items():
        raw_children = node.get("children", [])
        if not isinstance(raw_children, list):
            raise ValueError("case document child list is invalid")
        children: list[str] = []
        for child in raw_children:
            child_key = str(child)
            if child_key not in nodes:
                raise ValueError("case document references an absent child")
            children.append(child_key)
        children_by_parent[key] = children

    seen = {root_key}
    assigned_parent: dict[str, str] = {}
    stack: list[tuple[str, int]] = [(root_key, 0)]
    visited = 0
    while stack:
        node_key, depth = stack.pop()
        visited += 1
        if visited > max_document_nodes:
            raise ValueError("case document exceeds the traversal budget")
        if depth > max_document_depth:
            raise ValueError("case document exceeds the depth budget")
        for child_key in reversed(children_by_parent[node_key]):
            if child_key in seen:
                raise ValueError("case document contains a cycle or shared child")
            seen.add(child_key)
            assigned_parent[child_key] = node_key
            stack.append((child_key, depth + 1))
    if len(seen) != len(nodes):
        raise ValueError("case document contains unreachable nodes")
    return nodes, children_by_parent


def _subtree_for_candidate(
    candidate: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    children_by_parent: Mapping[str, list[str]],
    *,
    node_budget: int,
) -> tuple[dict[str, Any], int]:
    root_key = _string_id(candidate.get("node_id"))
    if root_key not in nodes:
        return {"complete": False, "status": "candidate_node_missing", "nodes": []}, 0

    labels: list[dict[str, Any]] = []
    stack: list[tuple[str, int | None, int, int]] = [(root_key, None, 0, 1)]
    while stack and len(labels) < node_budget:
        node_key, parent_index, position, sibling_count = stack.pop()
        node_index = len(labels)
        labels.append(
            {
                "label": _node_label(nodes[node_key]),
                "parent": parent_index,
                "position": position,
                "sibling_count": sibling_count,
            }
        )
        children = children_by_parent[node_key]
        for child_position in range(len(children) - 1, -1, -1):
            stack.append(
                (
                    children[child_position],
                    node_index,
                    child_position,
                    len(children),
                )
            )

    complete = not stack
    status = "complete" if complete else "truncated_node_limit"
    return {"complete": complete, "status": status, "nodes": labels}, len(labels)


def _string_id(value: Any) -> str:
    return str(value) if isinstance(value, (str, int)) else ""


def prepare_case(
    case: Mapping[str, Any],
    *,
    max_document_nodes: int = MAX_DOCUMENT_NODES,
    max_document_depth: int = MAX_DOCUMENT_DEPTH,
    max_candidates: int = MAX_CANDIDATES,
    max_subtree_nodes: int = MAX_SUBTREE_NODES,
    max_total_subtree_nodes: int = MAX_TOTAL_SUBTREE_NODES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach bounded, value-free subtree shapes to candidates.

    Only ``document`` and ``candidates`` are read from ``case``. Gold annotations,
    expected values, owning-root metadata and mutation labels are not consulted.
    Subtrees retain ordered tags and attribute names but no DOM IDs or values.

    Returns augmented candidate copies plus counters describing omitted or
    truncated shapes. Tree-kernel scoring treats any non-complete shape as
    unmatched and returns zero for that comparison.
    """
    budgets = {
        "max_document_nodes": max_document_nodes,
        "max_document_depth": max_document_depth,
        "max_candidates": max_candidates,
        "max_subtree_nodes": max_subtree_nodes,
        "max_total_subtree_nodes": max_total_subtree_nodes,
    }
    if any(not isinstance(value, int) or value < 1 for value in budgets.values()):
        raise ValueError("all preparation budgets must be positive integers")

    document = case.get("document")
    candidates = case.get("candidates")
    if not isinstance(document, Mapping) or not isinstance(candidates, list):
        raise ValueError("case must contain a document and candidate list")
    nodes, children_by_parent = _index_case_document(
        document,
        max_document_nodes=max_document_nodes,
        max_document_depth=max_document_depth,
    )

    augmented: list[dict[str, Any]] = []
    total_subtree_nodes = 0
    counts: Counter[str] = Counter()
    for index, raw_candidate in enumerate(candidates):
        if not isinstance(raw_candidate, Mapping):
            raise ValueError("candidate records must be mappings")
        candidate = dict(raw_candidate)
        if index >= max_candidates:
            subtree = {
                "complete": False,
                "status": "candidate_budget_exhausted",
                "nodes": [],
            }
            visited = 0
        elif total_subtree_nodes >= max_total_subtree_nodes:
            subtree = {
                "complete": False,
                "status": "total_node_budget_exhausted",
                "nodes": [],
            }
            visited = 0
        else:
            remaining = max_total_subtree_nodes - total_subtree_nodes
            node_budget = min(max_subtree_nodes, remaining)
            subtree, visited = _subtree_for_candidate(
                candidate, nodes, children_by_parent, node_budget=node_budget
            )
            if (
                subtree["status"] == "truncated_node_limit"
                and remaining <= max_subtree_nodes
            ):
                subtree["status"] = "total_node_budget_exhausted"
        total_subtree_nodes += visited
        counts[subtree["status"]] += 1
        candidate["subtree"] = subtree
        candidate["subtree_status"] = subtree["status"]
        augmented.append(candidate)

    complete_count = counts["complete"]
    preparation_status = (
        "no_candidates"
        if not augmented
        else "complete"
        if complete_count == len(augmented)
        else "partial"
    )
    diagnostics = {
        "status": preparation_status,
        "candidate_count": len(augmented),
        "complete_subtrees": complete_count,
        "unmatched_candidates": counts["candidate_node_missing"],
        "subtree_truncations": counts["truncated_node_limit"],
        "total_node_budget_exhaustions": counts["total_node_budget_exhausted"],
        "candidate_budget_exhaustions": counts["candidate_budget_exhausted"],
        "materialized_subtree_nodes": total_subtree_nodes,
        "budgets": budgets,
        "feature_policy": (
            "ordered tag and attribute-name structure; "
            "text/attribute values and node IDs omitted"
        ),
    }
    return augmented, diagnostics


def _position_bucket(position: int, sibling_count: int) -> str:
    if sibling_count <= 1:
        return "only"
    if position == 0:
        return "first"
    if position == sibling_count - 1:
        return "last"
    return "middle"


def tree_fragment_weights(candidate: Mapping[str, Any]) -> Counter[str] | None:
    """Build bounded ordered ancestor-path fragments from a complete subtree."""
    subtree = candidate.get("subtree")
    if not isinstance(subtree, Mapping) or subtree.get("complete") is not True:
        return None
    nodes = subtree.get("nodes")
    if not isinstance(nodes, list) or not nodes or len(nodes) > MAX_SUBTREE_NODES:
        return None

    labels: list[str] = []
    parents: list[int | None] = []
    positions: list[int] = []
    sibling_counts: list[int] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            return None
        label = _string(node.get("label"))
        parent = node.get("parent")
        position = node.get("position")
        sibling_count = node.get("sibling_count")
        if (
            not label
            or not isinstance(position, int)
            or not isinstance(sibling_count, int)
        ):
            return None
        if index == 0:
            if parent is not None:
                return None
        elif not isinstance(parent, int) or parent < 0 or parent >= index:
            return None
        if position < 0 or sibling_count < 1 or position >= sibling_count:
            return None
        labels.append(label)
        parents.append(parent)
        positions.append(position)
        sibling_counts.append(sibling_count)

    fragments: Counter[str] = Counter()
    for node_index in range(len(nodes)):
        chain: list[int] = []
        current: int | None = node_index
        while current is not None and len(chain) <= MAX_TREE_FRAGMENT_EDGES:
            chain.append(current)
            current = parents[current]
        chain.reverse()
        for start in range(len(chain)):
            fragment = chain[start:]
            if len(fragment) > MAX_TREE_FRAGMENT_EDGES + 1:
                continue
            tokens = [labels[fragment[0]]]
            for child_index in fragment[1:]:
                tokens.append(
                    _position_bucket(
                        positions[child_index], sibling_counts[child_index]
                    )
                )
                tokens.append(labels[child_index])
            key = json.dumps(tokens, ensure_ascii=False, separators=(",", ":"))
            fragments[key] += 1
    return fragments


def _multiset_jaccard(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    keys = set(left) | set(right)
    denominator = sum(max(left.get(key, 0), right.get(key, 0)) for key in keys)
    if denominator == 0:
        return 0.0
    numerator = sum(min(left.get(key, 0), right.get(key, 0)) for key in keys)
    return numerator / denominator


def _tree_kernel_scores(
    candidates: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
) -> list[float]:
    candidate_features = [tree_fragment_weights(candidate) for candidate in candidates]
    reference_features = [tree_fragment_weights(reference) for reference in references]
    if not reference_features:
        return [0.0] * len(candidates)
    scores: list[float] = []
    for candidate in candidate_features:
        if candidate is None:
            scores.append(0.0)
            continue
        scores.append(
            max(
                (
                    _multiset_jaccard(candidate, reference)
                    if reference is not None
                    else 0.0
                    for reference in reference_features
                ),
                default=0.0,
            )
        )
    return scores


def score_candidates(
    method: str,
    query: dict[str, Any],
    candidates: list[dict[str, Any]],
    references: list[dict[str, Any]],
    representation: str = "context",
    semantic_vectors: dict[str, Sequence[float]] | None = None,
) -> list[float]:
    """Score candidates using exact/CWS structure or bounded tree fragments.

    These methods are representation-independent and ignore query text and
    semantic vectors. Reference methods take the maximum score over seed examples.
    Empty or unavailable evidence abstains with a zero score.
    """
    del query, representation, semantic_vectors
    if method not in ADVANCED_METHODS:
        raise ValueError(f"unknown advanced method: {method}")
    if not candidates:
        return []
    if method == "weighted_jaccard_exact":
        scores = _exact_structural_scores(candidates, references)
    elif method == "weighted_minhash_64":
        scores = _minhash_scores(candidates, references, 64)
    elif method == "weighted_minhash_128":
        scores = _minhash_scores(candidates, references, 128)
    elif method == "ordered_tree_fragment_jaccard":
        scores = _tree_kernel_scores(candidates, references)
    else:
        raise ValueError(f"advanced method has no implementation: {method}")
    return [
        min(1.0, float(score)) if math.isfinite(score) and score >= 0.0 else 0.0
        for score in scores
    ]
