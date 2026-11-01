"""Finite, synthetic resource-scaling probes for the fingerprint substrate.

The command is intentionally separate from the retrieval matrix: it measures
generic rendered-DOM candidate generation, bounded subtree preparation, one
structural ranking pass, and selected structural fingerprints. It does not run
models, browser acquisition, or RuntimeContract validation.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import signal
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPERIMENT_ROOT.parents[2]
if str(EXPERIMENT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_ROOT))

corpus = importlib.import_module("corpus")
methods = importlib.import_module("methods")
advanced_methods = importlib.import_module("extensions.advanced_methods")

try:
    tree_edit = importlib.import_module("extensions.tree_edit")
except ImportError:  # pragma: no cover - optional code is present in this repository
    tree_edit = None


DEPTH_VALUES = (1, 8, 32, 64, 128, 256, 257)
WIDTH_VALUES = (1, 8, 32, 128, 512)
ATTRIBUTE_VALUES = (1, 32, 128, 512, 513)
RECORD_FIELDS = ("id", "name", "price", "stock")
FINGERPRINT_FEATURE_SAMPLE_CAP = 32
TREE_EDIT_PROBE_CASE = "depth-8"
TREE_EDIT_MAX_NODES = 32
TREE_EDIT_MAX_PAIR_COMPARISONS = 1
TREE_EDIT_MAX_WORK = 5_000
MAX_SYNTHETIC_NODES = 6_000
MAX_SYNTHETIC_WIDTH = 512
MAX_SYNTHETIC_ATTRIBUTES = 513
DEFAULT_CASE_CPU_SECONDS = 2.0
DEFAULT_CASE_WALL_SECONDS = 2.5
DEFAULT_OVERALL_CPU_SECONDS = 20.0
DEFAULT_OVERALL_WALL_SECONDS = 20.0


class CaseCpuBudgetExceeded(TimeoutError):
    """Raised by the worker's CPU timer; the case is not a passing measurement."""


def case_plan() -> list[dict[str, Any]]:
    """Return three one-axis sweeps, not their unbounded Cartesian product."""
    plan: list[dict[str, Any]] = []
    for depth in DEPTH_VALUES:
        plan.append(
            {
                "case_id": f"depth-{depth}",
                "axis": "depth",
                "depth": depth,
                "width": 1,
                "attribute_count": 1,
                "tree_edit_probe": depth == 8,
            }
        )
    for width in WIDTH_VALUES:
        plan.append(
            {
                "case_id": f"width-{width}",
                "axis": "width",
                "depth": 2,
                "width": width,
                "attribute_count": 1,
                "tree_edit_probe": False,
            }
        )
    for attribute_count in ATTRIBUTE_VALUES:
        plan.append(
            {
                "case_id": f"attributes-{attribute_count}",
                "axis": "attributes",
                "depth": 2,
                "width": 1,
                "attribute_count": attribute_count,
                "tree_edit_probe": False,
            }
        )
    return plan


def build_synthetic_document(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Build a small generic rooted-record DOM with one controlled dimension."""
    axis = spec.get("axis")
    if axis not in {"depth", "width", "attributes"}:
        raise ValueError("axis must be depth, width, or attributes")
    depth = _positive_int(spec.get("depth"), "depth")
    width = _positive_int(spec.get("width"), "width")
    attribute_count = _positive_int(spec.get("attribute_count"), "attribute_count")
    if depth > max(DEPTH_VALUES) or width > MAX_SYNTHETIC_WIDTH:
        raise ValueError("requested DOM shape exceeds synthetic harness bounds")
    if attribute_count > MAX_SYNTHETIC_ATTRIBUTES:
        raise ValueError("attribute count exceeds synthetic harness bound")

    nodes: list[dict[str, Any]] = [
        {"id": 0, "kind": "document", "children": [1]},
        {
            "id": 1,
            "kind": "element",
            "tag_name": "main",
            "attributes": [
                *_record_attributes(),
                {"name": "data-feature", "value": "base-feature"},
            ],
            "children": [],
        },
    ]
    probe_node_id = 1
    deepest_node_id = 1
    next_id = 2

    def add_element(
        parent_id: int, tag_name: str, attributes: list[dict[str, str]]
    ) -> int:
        nonlocal next_id
        node_id = next_id
        next_id += 1
        nodes.append(
            {
                "id": node_id,
                "kind": "element",
                "tag_name": tag_name,
                "attributes": attributes,
                "children": [],
            }
        )
        parent = nodes[parent_id]
        if not isinstance(parent.get("children"), list):
            raise ValueError("synthetic parent has an invalid child list")
        parent["children"].append(node_id)
        return node_id

    if axis == "depth":
        parent_id = 1
        for level in range(2, depth + 1):
            parent_id = add_element(
                parent_id,
                "section",
                [{"name": "data-level", "value": str(level)}],
            )
        deepest_node_id = parent_id
        probe_node_id = deepest_node_id
    elif axis == "width":
        for index in range(width):
            card_id = add_element(
                1,
                "article",
                [
                    *_record_attributes(index=index),
                    {"name": "data-feature", "value": "repeated-record"},
                ],
            )
            if index == 0:
                probe_node_id = card_id
    else:
        attributes = [
            {
                "name": f"data-feature-{index:04d}",
                "value": f"feature-value-{index:04d}",
            }
            for index in range(attribute_count)
        ]
        probe_node_id = add_element(1, "span", attributes)
        deepest_node_id = probe_node_id

    document = {
        "schema": "yosoi.rendered-dom.v1",
        "document_epoch": 1,
        "root": 0,
        "tree_model": "document_light_dom",
        "nodes": nodes,
    }
    return {
        "document": document,
        "probe_node_id": probe_node_id,
        "deepest_node_id": deepest_node_id,
    }


def validate_synthetic_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate unique source IDs, child/parent ownership, reachability, and depth."""
    if document.get("schema") != "yosoi.rendered-dom.v1":
        raise ValueError("synthetic document has an unsupported wire schema")
    raw_nodes = document.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("synthetic document has no node list")
    if len(raw_nodes) > MAX_SYNTHETIC_NODES:
        raise ValueError("synthetic document exceeds harness node bound")

    nodes: dict[int, Mapping[str, Any]] = {}
    for index, node in enumerate(raw_nodes):
        if not isinstance(node, Mapping):
            raise ValueError(f"synthetic node {index} is not a mapping")
        node_id = _node_id(node.get("id"), f"synthetic node {index} ID")
        if node_id in nodes:
            raise ValueError(f"duplicate synthetic source ID {node_id}")
        kind = node.get("kind")
        if kind not in {"document", "element", "text"}:
            raise ValueError(f"synthetic node {node_id} has invalid kind")
        children = node.get("children")
        if not isinstance(children, list):
            raise ValueError(f"synthetic node {node_id} has invalid children")
        if kind == "element":
            if not isinstance(node.get("tag_name"), str) or not node["tag_name"]:
                raise ValueError(f"synthetic element {node_id} has no tag name")
            _validate_attributes(node.get("attributes"), node_id)
        elif kind == "text" and children:
            raise ValueError(f"synthetic non-element {node_id} cannot have children")
        if kind == "text" and not isinstance(node.get("value", ""), str):
            raise ValueError(f"synthetic text node {node_id} has invalid value")
        nodes[node_id] = node

    root_id = _node_id(document.get("root"), "synthetic root ID")
    if root_id not in nodes:
        raise ValueError("synthetic root ID does not exist")
    parents: dict[int, int] = {}
    stack: list[tuple[int, int]] = [(root_id, 0)]
    seen = {root_id}
    max_depth = 0
    while stack:
        node_id, depth = stack.pop()
        max_depth = max(max_depth, depth)
        children = nodes[node_id]["children"]
        for child_value in reversed(children):
            child_id = _node_id(child_value, f"child of source ID {node_id}")
            if child_id not in nodes:
                raise ValueError(
                    f"source ID {node_id} references absent child {child_id}"
                )
            if child_id in seen:
                raise ValueError(
                    f"source ID {child_id} has a cycle or more than one parent"
                )
            seen.add(child_id)
            parents[child_id] = node_id
            stack.append((child_id, depth + 1))
    if len(seen) != len(nodes):
        raise ValueError("synthetic document contains unreachable source IDs")
    return {
        "node_count": len(nodes),
        "max_node_depth": max_depth,
        "source_root_id": root_id,
        "parents": parents,
        "nodes_by_id": nodes,
    }


def validate_candidate_source_links(
    candidates: Sequence[Mapping[str, Any]], document_index: Mapping[str, Any]
) -> dict[str, int]:
    """Check candidate IDs and root-first ancestor links against the source graph."""
    nodes = document_index.get("nodes_by_id")
    parents = document_index.get("parents")
    root_id = document_index.get("source_root_id")
    if not isinstance(nodes, Mapping) or not isinstance(parents, Mapping):
        raise ValueError("document index is incomplete")
    checked = 0
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"candidate {index} is not a mapping")
        node_key = _string_node_id(
            candidate.get("node_id"), f"candidate {index} node_id"
        )
        node_id = int(node_key)
        if node_id not in nodes:
            raise ValueError(f"candidate {index} references absent source ID {node_id}")
        chain: list[int] = []
        current = parents.get(node_id)
        seen: set[int] = set()
        while current is not None:
            if current in seen:
                raise ValueError(f"candidate {index} parent chain contains a cycle")
            seen.add(current)
            chain.append(current)
            current = parents.get(current)
        chain.reverse()
        if not chain or chain[0] != root_id:
            raise ValueError(f"candidate {index} does not descend from source root")
        raw_ancestors = candidate.get("ancestors")
        if not isinstance(raw_ancestors, list):
            raise ValueError(f"candidate {index} ancestors are not a list")
        observed = [
            _string_node_id(value, "candidate ancestor") for value in raw_ancestors
        ]
        if observed != [str(value) for value in chain]:
            raise ValueError(
                f"candidate {index} parent links do not match the source tree"
            )
        checked += 1
    return {"candidate_source_links_checked": checked}


def _record_attributes(index: int | None = None) -> list[dict[str, str]]:
    suffix = "base" if index is None else f"{index:04d}"
    return [
        {"name": f"data-{field}", "value": f"synthetic-{field}-{suffix}"}
        for field in RECORD_FIELDS
    ]


def _validate_attributes(value: Any, node_id: int) -> None:
    if not isinstance(value, list):
        raise ValueError(f"synthetic element {node_id} has invalid attributes")
    names: set[str] = set()
    for index, attribute in enumerate(value):
        if not isinstance(attribute, Mapping):
            raise ValueError(
                f"synthetic attribute {index} on node {node_id} is invalid"
            )
        name = attribute.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"synthetic attribute {index} on node {node_id} has no name"
            )
        if name in names:
            raise ValueError(f"synthetic element {node_id} repeats attribute {name!r}")
        if not isinstance(attribute.get("value"), str):
            raise ValueError(
                f"synthetic attribute {name!r} on node {node_id} has no value"
            )
        names.add(name)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _node_id(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _string_node_id(value: Any, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{label} must be a source ID string or integer")
    text = str(value)
    if not text.isdigit():
        raise ValueError(f"{label} is not a numeric synthetic source ID")
    return text


def _timed_stage(
    stages: dict[str, Any],
    name: str,
    operation: Callable[[], Any],
) -> Any:
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    try:
        value = operation()
    except CaseCpuBudgetExceeded:
        stages[name] = {
            "status": "budget_exhausted",
            "wall_seconds": time.perf_counter() - wall_start,
            "cpu_seconds": time.process_time() - cpu_start,
        }
        raise
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        status = "budget_rejected" if "budget" in str(error).lower() else "failed"
        stages[name] = {
            "status": status,
            "error": message,
            "wall_seconds": time.perf_counter() - wall_start,
            "cpu_seconds": time.process_time() - cpu_start,
        }
        return None
    stages[name] = {
        "status": "complete",
        "wall_seconds": time.perf_counter() - wall_start,
        "cpu_seconds": time.process_time() - cpu_start,
    }
    return value


def _execute_case(
    payload: Mapping[str, Any], progress: dict[str, Any]
) -> dict[str, Any]:
    spec = payload.get("spec")
    reference_candidate = payload.get("reference_candidate")
    if not isinstance(spec, Mapping) or not isinstance(reference_candidate, Mapping):
        raise ValueError("worker payload is missing the spec or reference candidate")
    stages: dict[str, Any] = progress["stages"]
    shape = build_synthetic_document(spec)
    document = shape["document"]
    document_index = _timed_stage(
        stages, "wire_validation", lambda: validate_synthetic_document(document)
    )
    if document_index is None:
        return _case_result(spec, "invalid_synthetic_data", stages)

    candidate_result = _timed_stage(
        stages,
        "candidate_generation",
        lambda: corpus.build_candidates(document, str(spec["case_id"])),
    )
    if candidate_result is None:
        status = stages["candidate_generation"]["status"]
        return _case_result(
            spec,
            "budget_rejected" if status == "budget_rejected" else "failed",
            stages,
            wire=document_index,
        )
    candidates = candidate_result
    link_check = _timed_stage(
        stages,
        "candidate_source_links",
        lambda: validate_candidate_source_links(candidates, document_index),
    )
    if link_check is None:
        return _case_result(spec, "failed", stages, wire=document_index)

    prepared_result = _timed_stage(
        stages,
        "advanced_subtree_preparation",
        lambda: advanced_methods.prepare_case(
            {"document": document, "candidates": candidates}
        ),
    )
    prepared_candidates = candidates
    preparation_diagnostics = None
    if prepared_result is not None:
        prepared_candidates, preparation_diagnostics = prepared_result

    structural_result = _timed_stage(
        stages,
        "structural_jaccard_full_candidate_scan",
        lambda: methods.score_candidates(
            "structural_jaccard",
            {"field": "synthetic_record", "description": "synthetic record"},
            candidates,
            [reference_candidate],
            representation="structure_context",
        ),
    )

    probe = _select_probe_candidate(
        candidates,
        int(shape["probe_node_id"]),
        str(spec["axis"]),
    )
    fingerprint: dict[str, Any] = {
        "status": "unavailable" if probe is None else "complete",
        "probe_candidate_id": None if probe is None else probe["id"],
        "attribute_count_requested": int(spec["attribute_count"]),
        "weighted_feature_count": None,
        "attribute_feature_count": None,
        "cws_feature_limit": advanced_methods.MAX_CWS_FEATURES,
        "weighted_jaccard_score": None,
        "cws": {},
        "serialized_fingerprint_bytes": {},
    }
    if probe is not None:
        weight_start_wall = time.perf_counter()
        weight_start_cpu = time.process_time()
        try:
            weights = advanced_methods.structural_feature_weights(probe)
            fingerprint["weighted_feature_count"] = len(weights)
            fingerprint["attribute_feature_count"] = sum(
                feature.startswith("attribute:") for feature in weights
            )
            reference_weights = advanced_methods.structural_feature_weights(
                reference_candidate
            )
            fingerprint["weighted_jaccard_score"] = advanced_methods.weighted_jaccard(
                weights, reference_weights
            )
            weight_payload = _canonical_bytes(weights)
            fingerprint["serialized_fingerprint_bytes"]["weighted_features"] = len(
                weight_payload
            )
            sampled_payload_bytes = 0
            sampled_count = min(FINGERPRINT_FEATURE_SAMPLE_CAP, len(candidates))
            for candidate in candidates[:sampled_count]:
                sampled_payload_bytes += len(
                    _canonical_bytes(
                        advanced_methods.structural_feature_weights(candidate)
                    )
                )
            fingerprint["serialized_fingerprint_bytes"][
                "first_32_candidate_weighted_features"
            ] = sampled_payload_bytes
            fingerprint["serialized_fingerprint_sample_count"] = sampled_count
            fingerprint["exact_structural_fingerprint"] = {
                "status": "complete",
                "wall_seconds": time.perf_counter() - weight_start_wall,
                "cpu_seconds": time.process_time() - weight_start_cpu,
            }
        except CaseCpuBudgetExceeded:
            raise
        except Exception as error:
            fingerprint["status"] = "failed"
            fingerprint["error"] = f"{type(error).__name__}: {error}"
            fingerprint["exact_structural_fingerprint"] = {"status": "failed"}
            weights = None
            reference_weights = None

        if weights is not None and reference_weights is not None:
            for width in (64, 128):
                start_wall = time.perf_counter()
                start_cpu = time.process_time()
                try:
                    signature = advanced_methods._cws_signature(weights, width)
                    reference_signature = advanced_methods._cws_signature(
                        reference_weights, width
                    )
                    similarity = (
                        sum(
                            left == right
                            for left, right in zip(
                                signature, reference_signature, strict=True
                            )
                        )
                        / width
                        if signature and reference_signature
                        else 0.0
                    )
                    signature_payload = _canonical_bytes(
                        [[feature, token] for feature, token in signature]
                    )
                    fingerprint["cws"][str(width)] = {
                        "status": "complete",
                        "similarity": similarity,
                        "signature_length": len(signature),
                        "wall_seconds": time.perf_counter() - start_wall,
                        "cpu_seconds": time.process_time() - start_cpu,
                    }
                    fingerprint["serialized_fingerprint_bytes"][f"cws_{width}"] = len(
                        signature_payload
                    )
                except ValueError as error:
                    fingerprint["cws"][str(width)] = {
                        "status": "budget_rejected"
                        if "budget" in str(error).lower()
                        else "failed",
                        "error": f"{type(error).__name__}: {error}",
                        "wall_seconds": time.perf_counter() - start_wall,
                        "cpu_seconds": time.process_time() - start_cpu,
                    }
                except CaseCpuBudgetExceeded:
                    raise
                except Exception as error:
                    fingerprint["cws"][str(width)] = {
                        "status": "failed",
                        "error": f"{type(error).__name__}: {error}",
                        "wall_seconds": time.perf_counter() - start_wall,
                        "cpu_seconds": time.process_time() - start_cpu,
                    }

    tree_result = None
    if spec.get("tree_edit_probe") is True:
        tree_result = _timed_stage(
            stages,
            "single_tree_edit_component_pair",
            lambda: _run_tree_edit_probe(
                spec,
                int(shape["deepest_node_id"]),
                prepared_candidates,
                reference_candidate,
                payload.get("reference_document"),
            ),
        )

    scores = structural_result if isinstance(structural_result, list) else []
    prep_status = (
        None
        if preparation_diagnostics is None
        else preparation_diagnostics.get("status")
    )
    case_status = "measured"
    if any(stage.get("status") == "failed" for stage in stages.values()):
        case_status = "failed"
    elif fingerprint.get("status") == "failed" or any(
        value.get("status") == "failed" for value in fingerprint.get("cws", {}).values()
    ):
        case_status = "failed"
    elif structural_result is None or preparation_diagnostics is None:
        case_status = "measured_with_stage_failure"
    elif prep_status != "complete" or any(
        value.get("status") == "budget_rejected"
        for value in fingerprint.get("cws", {}).values()
    ):
        case_status = "measured_with_budget_or_truncation"
    elif tree_result is not None and tree_result.get("status") != "complete":
        case_status = "measured_with_unavailable_method"

    result = _case_result(
        spec,
        case_status,
        stages,
        wire=document_index,
        candidate_count=len(candidates),
        candidate_link_check=link_check,
        preparation=preparation_diagnostics,
        structural_score={
            "method": "structural_jaccard",
            "reference_count": 1,
            "candidate_count": len(scores),
            "top_score": max(scores, default=0.0),
        },
        fingerprint=fingerprint,
        tree_edit=tree_result,
    )
    return result


def _run_tree_edit_probe(
    spec: Mapping[str, Any],
    deepest_node_id: int,
    prepared_candidates: Sequence[Mapping[str, Any]],
    reference_candidate: Mapping[str, Any],
    reference_document: Any,
) -> dict[str, Any]:
    """Run at most one exact tree pair, on the named depth-8 probe case."""
    if tree_edit is None:
        return {"status": "unavailable", "reason": "tree_edit module missing"}
    if not isinstance(reference_document, Mapping):
        return {"status": "unavailable", "reason": "probe reference document missing"}
    candidates = [
        candidate
        for candidate in prepared_candidates
        if candidate.get("node_id") == str(deepest_node_id)
        and candidate.get("projection") == "text"
    ]
    reference_prepared, reference_diagnostics = advanced_methods.prepare_case(
        {"document": reference_document, "candidates": [dict(reference_candidate)]}
    )
    if not candidates or not reference_prepared:
        return {
            "status": "unavailable",
            "reason": "selected component candidate missing",
            "reference_preparation": reference_diagnostics,
        }
    score_values, diagnostics = tree_edit.score_candidates_with_diagnostics(
        tree_edit.TREE_EDIT_METHOD,
        {},
        [dict(candidates[0])],
        [reference_prepared[0]],
        max_tree_nodes=TREE_EDIT_MAX_NODES,
        max_pair_comparisons=TREE_EDIT_MAX_PAIR_COMPARISONS,
        max_total_estimated_work=TREE_EDIT_MAX_WORK,
    )
    return {
        "status": diagnostics.get("status", "unknown"),
        "candidate_id": candidates[0].get("id"),
        "reference_candidate_id": reference_prepared[0].get("id"),
        "pair_count": diagnostics.get("possible_pair_slots"),
        "score": score_values[0] if score_values else None,
        "diagnostics": diagnostics,
        "reference_preparation": reference_diagnostics,
    }


def _select_probe_candidate(
    candidates: Sequence[Mapping[str, Any]], node_id: int, axis: str
) -> Mapping[str, Any] | None:
    projection = "@data-feature-0000" if axis == "attributes" else "text"
    for candidate in candidates:
        if (
            candidate.get("node_id") == str(node_id)
            and candidate.get("projection") == projection
        ):
            return candidate
    return None


def _case_result(
    spec: Mapping[str, Any],
    status: str,
    stages: Mapping[str, Any],
    *,
    wire: Mapping[str, Any] | None = None,
    candidate_count: int | None = None,
    candidate_link_check: Mapping[str, Any] | None = None,
    preparation: Mapping[str, Any] | None = None,
    structural_score: Mapping[str, Any] | None = None,
    fingerprint: Mapping[str, Any] | None = None,
    tree_edit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "case_id": spec.get("case_id"),
        "axis": spec.get("axis"),
        "requested_depth": spec.get("depth"),
        "requested_width": spec.get("width"),
        "requested_attribute_count": spec.get("attribute_count"),
        "constant_synthetic_record_field_count": len(RECORD_FIELDS),
        "status": status,
        "stages": dict(stages),
        "scope_note": ("DOM substrate only; no RuntimeContract recursion claim"),
    }
    if wire is not None:
        result["wire"] = {
            "node_count": wire.get("node_count"),
            "max_node_depth": wire.get("max_node_depth"),
            "source_root_id": wire.get("source_root_id"),
        }
    if candidate_count is not None:
        result["candidate_count"] = candidate_count
    if candidate_link_check is not None:
        result["candidate_source_links"] = dict(candidate_link_check)
    if preparation is not None:
        result["preparation"] = dict(preparation)
    if structural_score is not None:
        result["structural_score"] = dict(structural_score)
    if fingerprint is not None:
        result["fingerprint"] = dict(fingerprint)
    if tree_edit is not None:
        result["tree_edit_probe"] = dict(tree_edit)
    return result


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _peak_rss_bytes() -> tuple[int | None, str | None]:
    try:
        import resource

        raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, AttributeError, OSError):
        return None, None
    if sys.platform == "darwin":
        return int(raw), "bytes"
    return int(raw * 1024), "KiB converted to bytes"


def _child_cpu_seconds() -> float | None:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    except (ImportError, AttributeError, OSError):
        return None
    return float(usage.ru_utime + usage.ru_stime)


def _arm_cpu_budget(seconds: float) -> bool:
    if not hasattr(signal, "setitimer") or not hasattr(signal, "ITIMER_PROF"):
        return False

    def exceeded(_signum, _frame):
        raise CaseCpuBudgetExceeded("per-case CPU budget exhausted")

    signal.signal(signal.SIGPROF, exceeded)
    signal.setitimer(signal.ITIMER_PROF, seconds)
    return True


def _cancel_cpu_budget() -> None:
    if hasattr(signal, "setitimer") and hasattr(signal, "ITIMER_PROF"):
        signal.setitimer(signal.ITIMER_PROF, 0)


def _worker_main(payload: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(payload.get("spec", {}).get("case_id", "unknown"))
    progress: dict[str, Any] = {"stages": {}}
    baseline_rss, rss_unit = _peak_rss_bytes()
    cpu_cap = float(payload.get("max_case_cpu_seconds", DEFAULT_CASE_CPU_SECONDS))
    cap_enforced = _arm_cpu_budget(cpu_cap)
    if not cap_enforced:
        result = _case_result(
            payload.get("spec", {}),
            "budget_unavailable",
            progress["stages"],
        )
        result["budget_reason"] = "process CPU timer is unavailable on this platform"
        result["measurement"] = {
            "cpu_cap_seconds": cpu_cap,
            "cpu_cap_enforced_by_signal_timer": False,
            "process_peak_rss_bytes": baseline_rss,
            "process_peak_rss_raw_unit": rss_unit,
            "process_baseline_peak_rss_bytes": baseline_rss,
            "peak_rss_delta_from_worker_baseline_bytes": 0,
            "rss_caveat": "worker baseline only; no scaling stage was run",
        }
        return result
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    try:
        result = _execute_case(payload, progress)
    except CaseCpuBudgetExceeded:
        result = _case_result(
            payload.get("spec", {}), "budget_exhausted", progress["stages"]
        )
        result["budget_reason"] = "max_case_cpu_seconds"
    except Exception as error:
        result = _case_result(payload.get("spec", {}), "failed", progress["stages"])
        result["worker_error"] = f"{type(error).__name__}: {error}"
    finally:
        _cancel_cpu_budget()
    peak_rss, peak_unit = _peak_rss_bytes()
    result["measurement"] = {
        "worker_wall_seconds": time.perf_counter() - start_wall,
        "worker_cpu_seconds": time.process_time() - start_cpu,
        "cpu_cap_seconds": cpu_cap,
        "cpu_cap_enforced_by_signal_timer": cap_enforced,
        "process_peak_rss_bytes": peak_rss,
        "process_peak_rss_raw_unit": peak_unit,
        "process_baseline_peak_rss_bytes": baseline_rss,
        "peak_rss_delta_from_worker_baseline_bytes": (
            None
            if peak_rss is None or baseline_rss is None
            else max(0, peak_rss - baseline_rss)
        ),
        "rss_caveat": (
            "ru_maxrss is worker high-water RSS, includes Python/import baseline"
        ),
    }
    result["case_id"] = result.get("case_id", case_id)
    return result


def run_scaling(
    output: str | Path,
    *,
    max_case_cpu_seconds: float = DEFAULT_CASE_CPU_SECONDS,
    max_case_wall_seconds: float = DEFAULT_CASE_WALL_SECONDS,
    overall_cpu_seconds: float = DEFAULT_OVERALL_CPU_SECONDS,
    overall_wall_seconds: float = DEFAULT_OVERALL_WALL_SECONDS,
) -> dict[str, Any]:
    """Run the finite case plan sequentially and write compact results.

    Each worker has a process-CPU signal timer and a parent-enforced wall timeout.
    If the overall deadline expires, remaining cases are reported as skipped.
    Budget-rejected inputs and incomplete work are never relabeled as passes.
    """
    output_path = Path(output)
    if output_path.exists():
        raise ValueError("scaling output directory must be new")
    for name, value in (
        ("max_case_cpu_seconds", max_case_cpu_seconds),
        ("max_case_wall_seconds", max_case_wall_seconds),
        ("overall_cpu_seconds", overall_cpu_seconds),
        ("overall_wall_seconds", overall_wall_seconds),
    ):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} must be a positive finite number")
        if not math.isfinite(float(value)) or value <= 0:
            raise ValueError(f"{name} must be a positive finite number")

    started_wall = time.perf_counter()
    started_monotonic = time.monotonic()
    parent_cpu_start = time.process_time()
    child_cpu_start = _child_cpu_seconds()
    reference_shape = build_synthetic_document(
        {
            "axis": "depth",
            "depth": 1,
            "width": 1,
            "attribute_count": 1,
        }
    )
    reference_candidates = corpus.build_candidates(
        reference_shape["document"], "scaling-reference"
    )
    reference_candidate = next(
        candidate
        for candidate in reference_candidates
        if candidate["node_id"] == "1" and candidate["projection"] == "text"
    )
    reference_index = validate_synthetic_document(reference_shape["document"])
    validate_candidate_source_links(reference_candidates, reference_index)
    plan = case_plan()
    deadline = started_monotonic + float(overall_wall_seconds)
    results: list[dict[str, Any]] = []
    reference_document = reference_shape["document"]

    for index, spec in enumerate(plan):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            results.extend(
                _case_result(item, "skipped_overall_budget", {})
                for item in plan[index:]
            )
            break
        current_child_cpu = _child_cpu_seconds()
        parent_cpu_used = max(0.0, time.process_time() - parent_cpu_start)
        if child_cpu_start is None or current_child_cpu is None:
            used_cpu = parent_cpu_used
            cpu_counter_available = False
        else:
            child_cpu_used = max(0.0, current_child_cpu - child_cpu_start)
            used_cpu = parent_cpu_used + child_cpu_used
            cpu_counter_available = True
        remaining_cpu = float(overall_cpu_seconds) - used_cpu
        cpu_startup_reserve = 0.1 if cpu_counter_available else 0.0
        if remaining_cpu <= cpu_startup_reserve:
            results.extend(
                _case_result(item, "skipped_overall_cpu_budget", {})
                for item in plan[index:]
            )
            break
        case_cpu_budget = min(float(max_case_cpu_seconds), remaining_cpu)
        if cpu_counter_available and remaining_cpu < float(max_case_cpu_seconds):
            # Leave a small allowance for interpreter startup before the worker's
            # process-CPU timer is armed; child CPU is measured by RUSAGE_CHILDREN.
            case_cpu_budget = remaining_cpu - cpu_startup_reserve
        payload = {
            "spec": spec,
            "reference_candidate": reference_candidate,
            "reference_document": reference_document,
            "max_case_cpu_seconds": case_cpu_budget,
        }
        timeout = min(float(max_case_wall_seconds), remaining)
        try:
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker"],
                input=json.dumps(payload, separators=(",", ":")),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            results.append(
                _case_result(
                    spec,
                    "budget_exhausted",
                    {},
                )
                | {"budget_reason": "max_case_or_overall_wall_seconds"}
            )
            if time.monotonic() >= deadline:
                results.extend(
                    _case_result(item, "skipped_overall_budget", {})
                    for item in plan[index + 1 :]
                )
                break
            continue
        if completed.returncode != 0:
            results.append(
                _case_result(spec, "worker_failed", {})
                | {
                    "worker_returncode": completed.returncode,
                    "stderr_tail": completed.stderr[-1000:],
                }
            )
            continue
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            results.append(
                _case_result(spec, "worker_failed", {})
                | {"worker_error": "worker returned invalid JSON"}
            )
            continue
        results.append(result)

    elapsed = time.perf_counter() - started_wall
    overall_parent_cpu = max(0.0, time.process_time() - parent_cpu_start)
    child_cpu_end = _child_cpu_seconds()
    overall_child_cpu = (
        None
        if child_cpu_start is None or child_cpu_end is None
        else max(0.0, child_cpu_end - child_cpu_start)
    )
    status_counts = Counter(str(result.get("status")) for result in results)
    stopped_statuses = {
        "budget_exhausted",
        "failed",
        "invalid_synthetic_data",
        "measured_with_stage_failure",
        "skipped_overall_budget",
        "skipped_overall_cpu_budget",
        "worker_failed",
        "budget_unavailable",
    }
    stopped_count = sum(
        1 for result in results if result.get("status") in stopped_statuses
    )
    method_limited_count = sum(
        1
        for result in results
        if result.get("status")
        in {
            "budget_rejected",
            "measured_with_budget_or_truncation",
            "measured_with_unavailable_method",
        }
    )
    overall_status = (
        "partial"
        if len(results) != len(plan) or stopped_count
        else "completed_with_method_limits"
        if method_limited_count
        else "complete"
    )
    report = {
        "format": "product-retrieval-scaling-v1",
        "status": overall_status,
        "scope": {
            "synthetic_record_fields_constant": list(RECORD_FIELDS),
            "dom_depth_is_a_separate_axis": True,
            "width_is_a_separate_axis": True,
            "attribute_count_is_a_separate_axis": True,
            "runtime_contract_recursion_tested": False,
            "model_or_browser_calls": 0,
            "structural_score_candidate_cap": corpus.MAX_CANDIDATES,
            "fingerprint_feature_serialization_sample_cap": (
                FINGERPRINT_FEATURE_SAMPLE_CAP
            ),
            "tree_edit_pair_limit": TREE_EDIT_MAX_PAIR_COMPARISONS,
        },
        "bounds": {
            "max_case_cpu_seconds": float(max_case_cpu_seconds),
            "max_case_wall_seconds": float(max_case_wall_seconds),
            "overall_cpu_seconds": float(overall_cpu_seconds),
            "overall_wall_seconds": float(overall_wall_seconds),
            "synthetic_node_limit": MAX_SYNTHETIC_NODES,
            "synthetic_width_limit": MAX_SYNTHETIC_WIDTH,
            "synthetic_attribute_limit": MAX_SYNTHETIC_ATTRIBUTES,
            "corpus_candidate_node_depth_limit": corpus.MAX_DOM_DEPTH,
            "corpus_document_node_limit": corpus.MAX_DOM_NODES,
            "advanced_subtree_node_limit": advanced_methods.MAX_SUBTREE_NODES,
            "cws_feature_limit": advanced_methods.MAX_CWS_FEATURES,
        },
        "case_plan": plan,
        "case_count": len(plan),
        "result_count": len(results),
        "status_counts": dict(status_counts),
        "case_budget_or_execution_stop_count": stopped_count,
        "case_or_method_limit_count": method_limited_count,
        "overall_child_cpu_seconds": overall_child_cpu,
        "overall_parent_cpu_seconds": overall_parent_cpu,
        "overall_cpu_seconds": (
            None
            if overall_child_cpu is None
            else overall_child_cpu + overall_parent_cpu
        ),
        "overall_cpu_counter_source": "resource.RUSAGE_CHILDREN"
        if cpu_counter_available
        else None,
        "overall_wall_seconds": elapsed,
        "rss_caveat": (
            "child ru_maxrss includes Python/import baseline; units converted to bytes"
        ),
        "interpretation_limits": [
            "one-axis sweeps only; no Cartesian depth x width x attribute product",
            "candidate count is capped by current corpus implementation limits",
            "advanced subtree shapes are bounded and may be partial by design",
            "CWS count includes path, tag, and motif features",
            "only one optional exact tree-edit component pair is attempted",
            "synthetic results do not establish recursive RuntimeContract support",
            "local latency does not imply API, electricity, or operator cost",
        ],
        "cases": results,
    }
    output_path.mkdir(parents=True, exist_ok=False)
    output_path.joinpath("report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    compact = {key: value for key, value in report.items() if key != "cases"}
    compact["case_statuses"] = [
        {"case_id": item.get("case_id"), "status": item.get("status")}
        for item in results
    ]
    output_path.joinpath("summary.json").write_text(
        json.dumps(compact, indent=2, ensure_ascii=False)
    )
    return compact


def _worker_entry() -> int:
    payload = json.load(sys.stdin)
    if not isinstance(payload, Mapping):
        raise ValueError("worker input must be a JSON object")
    print(json.dumps(_worker_main(payload), ensure_ascii=False, separators=(",", ":")))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list == ["--worker"]:
        return _worker_entry()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / ".generated" / "product-retrieval-scaling-v1",
    )
    parser.add_argument(
        "--max-case-cpu-seconds", type=float, default=DEFAULT_CASE_CPU_SECONDS
    )
    parser.add_argument(
        "--max-case-wall-seconds", type=float, default=DEFAULT_CASE_WALL_SECONDS
    )
    parser.add_argument(
        "--overall-cpu-seconds", type=float, default=DEFAULT_OVERALL_CPU_SECONDS
    )
    parser.add_argument(
        "--overall-wall-seconds", type=float, default=DEFAULT_OVERALL_WALL_SECONDS
    )
    args = parser.parse_args(args_list)
    summary = run_scaling(
        args.output,
        max_case_cpu_seconds=args.max_case_cpu_seconds,
        max_case_wall_seconds=args.max_case_wall_seconds,
        overall_cpu_seconds=args.overall_cpu_seconds,
        overall_wall_seconds=args.overall_wall_seconds,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] in {"complete", "completed_with_method_limits"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
