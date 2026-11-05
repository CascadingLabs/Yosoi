"""Small cached-score evaluation of joint selection and a value-form gate.

This experiment consumes only immutable score-cache arrays. It never invokes a
base scorer or embedding model, and query-case gold annotations are read only
after the complete prediction file has been written.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
import math
import sys
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PRODUCT_ROOT = ROOT / "experiments" / "product-retrieval"
EXTENSIONS = PRODUCT_ROOT / "extensions"
OUTPUT_ROOT = ROOT / ".generated" / "product-retrieval-joint-shape-micro-v1"
SOURCE_RUN = ROOT / ".generated" / "product-retrieval-minilm-v3"
CACHE_ROOT = ROOT / ".generated" / "scoring-cache"
SEMANTIC_ARTIFACT = ROOT / ".generated" / "product-retrieval-input" / "minilm.json"

for _path in (str(PRODUCT_ROOT), str(EXTENSIONS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

methods = importlib.import_module("methods")
projection = importlib.import_module("projection")
run_matrix = importlib.import_module("run_matrix")
value_shape = importlib.import_module("value_shape")
_bootstrap_joint_assignment = importlib.import_module("joint_assignment")
assign_jointly = _bootstrap_joint_assignment.assign_jointly
_bootstrap_migrate_scores = importlib.import_module("migrate_scores")
cache_identity = _bootstrap_migrate_scores.identity


CASE_IDS = ("obj-003", "obj-004", "obj-005", "obj-006")
SEED_CASE_IDS = ("obj-001", "obj-002")
REFERENCE_GROUP = "obj-001+obj-002"
FIELDS = ("color", "id", "material", "name", "price", "stock")
SCORERS = (
    "structural_jaccard",
    "lexical_char_ngram_cosine_reference",
    "semantic_reference",
)
REPRESENTATION = "context"
BOUNDS = {
    "max_fields": 6,
    "per_field_top_k": 5,
    "max_roots": 3,
    "max_dp_transitions": 100_000,
}
ROOT_SIZE_LAMBDAS = (0.0, 0.2)
SHAPE_METHOD = "value_shape_jaccard_max"
SHAPE_STRENGTH = 0.5
FIRST_CASE_CPU_LIMIT_SECONDS = 3.0


class MissingCachedScoreError(KeyError):
    """Raised when an exact cached vector is absent; scoring fallback is forbidden."""


def sha256_file(path: Path) -> str:
    """Hash one retained input file without interpreting its contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def choose_case_ids(case_ids: Sequence[str] | None) -> tuple[str, ...]:
    """Accept only up to four named original cases, never derived variants."""
    selected = CASE_IDS if case_ids is None else tuple(case_ids)
    if not selected:
        raise ValueError("select at least one original micro case")
    if len(selected) > 4:
        raise ValueError("case limit is at most four original micro cases")
    if len(set(selected)) != len(selected):
        raise ValueError("case ids must be unique")
    if any(case_id not in CASE_IDS for case_id in selected):
        raise ValueError(
            "case ids must be original micro cases obj-003 through obj-006"
        )
    return tuple(selected)


def build_cache_key(
    field: str,
    method: str,
    reference_group: str,
    representation: str,
    semantic_artifact_sha256: str | None,
) -> str:
    """Build the exact five-part score-cache key used by the frozen runner."""
    return json.dumps(
        [field, method, reference_group, representation, semantic_artifact_sha256]
    )


def cached_vector(
    entries: Mapping[str, Any], key: str, expected_length: int
) -> list[float]:
    """Load and validate a score vector, failing closed when it is not cached."""
    if key not in entries:
        raise MissingCachedScoreError(f"missing cached score entry: {key}")
    entry = entries[key]
    if not isinstance(entry, Mapping) or not isinstance(entry.get("scores"), list):
        raise ValueError(f"cached score entry has no score list: {key}")
    scores = entry["scores"]
    if len(scores) != expected_length:
        raise ValueError(
            f"cached score vector length {len(scores)} does not match {expected_length}"
        )
    result: list[float] = []
    for index, raw_score in enumerate(scores):
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            raise ValueError(f"cached score {index} is not numeric")
        score = float(raw_score)
        if not math.isfinite(score) or score < 0.0:
            raise ValueError("cached score vector must be finite nonnegative values")
        result.append(score)
    return result


def masked_field_scores(
    scores: Sequence[float],
    candidates: Sequence[Mapping[str, Any]],
    hints: Mapping[str, Any],
) -> list[float]:
    """Mask unsupported projections with a negative sentinel without reindexing."""
    if len(scores) != len(candidates):
        raise ValueError("score and global candidate counts must match")
    projections = set(hints.get("projections", [])) if hints.get("supported") else set()
    result: list[float] = []
    for score, candidate in zip(scores, candidates, strict=True):
        normalized = float(score)
        if not math.isfinite(normalized) or normalized < 0.0:
            raise ValueError("source score must be finite and nonnegative")
        result.append(
            normalized if candidate.get("projection") in projections else -1.0
        )
    return result


def root_text_indices(candidates: Sequence[Mapping[str, Any]]) -> list[int]:
    """Return root scorer indices into its text-only candidate pool."""
    return [
        index
        for index, candidate in enumerate(candidates)
        if candidate.get("projection") == "text"
    ]


def root_size_fractions(nodes: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Compute each DOM node's subtree size divided by total document nodes."""
    if not nodes:
        raise ValueError("document node list must be non-empty")
    by_id: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        raw_id = node.get("id")
        if not isinstance(raw_id, (str, int)) or isinstance(raw_id, bool):
            raise ValueError("DOM node id must be a string or integer")
        node_id = str(raw_id)
        if node_id in by_id:
            raise ValueError(f"duplicate DOM node id: {node_id}")
        by_id[node_id] = node
    parents: dict[str, str | None] = {}
    for node_id, node in by_id.items():
        parent = node.get("parent")
        if parent is not None and str(parent) not in by_id:
            raise ValueError(f"DOM node {node_id} has missing parent {parent!r}")
        parents[node_id] = None if parent is None else str(parent)

    def is_within(candidate_id: str, root_id: str) -> bool:
        current: str | None = candidate_id
        visited: set[str] = set()
        while current is not None:
            if current in visited:
                raise ValueError("cycle in document parent links")
            visited.add(current)
            if current == root_id:
                return True
            current = parents[current]
        return False

    total = len(by_id)
    return {
        root_id: sum(is_within(node_id, root_id) for node_id in by_id) / total
        for root_id in by_id
    }


def seed_candidates_for_field(
    seed_cases: Sequence[Mapping[str, Any]], field: str
) -> list[Mapping[str, Any]]:
    """Return only candidates explicitly expected for a field in seed cases."""
    result: list[Mapping[str, Any]] = []
    for seed_case in seed_cases:
        expected_ids = [
            str(candidate_id)
            for candidate_id in seed_case.get("expected", {}).get(field, [])
        ]
        by_id = {
            str(candidate.get("id")): candidate for candidate in seed_case["candidates"]
        }
        missing = set(expected_ids) - by_id.keys()
        if missing:
            raise ValueError(
                f"seed expected ids missing from candidates: {sorted(missing)}"
            )
        result.extend(by_id[expected_id] for expected_id in expected_ids)
    return result


def projection_hints_for_seeds(
    seed_cases: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Infer supported source projections from the two seed gold lists only."""
    return {
        field: projection.reference_projection_hints(
            seed_candidates_for_field(seed_cases, field), field
        )
        for field in fields
    }


def _read_source() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    frozen_path = SOURCE_RUN / "frozen.json"
    corpus_path = SOURCE_RUN / "corpus.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    data = json.loads(corpus_path.read_text(encoding="utf-8"))
    if run_matrix.checksum(data) != frozen.get("corpus_checksum"):
        raise ValueError("cached source corpus checksum does not match its freeze")
    for relative_path in ("run_matrix.py", "methods.py"):
        current_sha = sha256_file(PRODUCT_ROOT / relative_path)
        if frozen.get("implementation", {}).get(relative_path) != current_sha:
            raise ValueError(f"source scorer implementation changed: {relative_path}")
    if data.get("references") != list(SEED_CASE_IDS):
        raise ValueError("frozen source references differ from the declared seed pair")
    expected_group = {"id": REFERENCE_GROUP, "cases": list(SEED_CASE_IDS)}
    if expected_group not in frozen.get("reference_groups", []):
        raise ValueError("declared pair seed group is not present in the source freeze")
    minilm_digest = sha256_file(SEMANTIC_ARTIFACT)
    return (
        frozen,
        data,
        {
            "frozen_path": frozen_path,
            "corpus_path": corpus_path,
            "minilm_digest": minilm_digest,
        },
    )


def _load_case_cache(
    frozen: Mapping[str, Any],
    data: Mapping[str, Any],
    case: Mapping[str, Any],
    minilm_digest: str,
) -> tuple[dict[str, dict[str, list[float]]], dict[str, Any]]:
    """Load exactly the selected context vectors from the immutable cache."""
    identity = cache_identity(frozen, data, case, 1)
    path = CACHE_ROOT / f"{identity}.json.gz"
    if not path.is_file():
        raise MissingCachedScoreError(f"score cache file is missing: {path.name}")
    raw_cache = path.read_bytes()
    entries = json.loads(gzip.decompress(raw_cache))
    if not isinstance(entries, Mapping):
        raise ValueError(f"score cache root must be an object: {path.name}")

    all_candidates = case["candidates"]
    text_indices = root_text_indices(all_candidates)
    root_candidates = [all_candidates[index] for index in text_indices]
    by_method: dict[str, dict[str, list[float]]] = {}
    vector_footprints: list[dict[str, Any]] = []
    for method in SCORERS:
        metadata = methods.METHOD_METADATA.get(method)
        if metadata is None:
            raise ValueError(
                f"requested method absent from frozen scorer catalog: {method}"
            )
        group_id = (
            "query_only"
            if metadata["reference_aggregation"] == "none"
            else REFERENCE_GROUP
        )
        by_method[method] = {}
        for field in ("root", *FIELDS):
            pool = root_candidates if field == "root" else all_candidates
            semantic_digest = minilm_digest if method.startswith("semantic") else None
            key = build_cache_key(
                field,
                method,
                group_id,
                REPRESENTATION,
                semantic_digest,
            )
            scores = cached_vector(entries, key, len(pool))
            by_method[method][field] = scores
            score_digest = hashlib.sha256(
                json.dumps(scores, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            vector_footprints.append(
                {
                    "field": field,
                    "method": method,
                    "reference_group": group_id,
                    "representation": REPRESENTATION,
                    "cache_key": key,
                    "semantic_artifact_sha256": semantic_digest,
                    "candidate_space": "text_only_root_candidates"
                    if field == "root"
                    else "all_field_candidates",
                    "score_count": len(scores),
                    "score_sha256": score_digest,
                }
            )
    return by_method, {
        "identity_sha256": identity,
        "cache_filename": path.name,
        "cache_sha256": hashlib.sha256(raw_cache).hexdigest(),
        "entry_count": len(entries),
        "candidate_count_all_fields": len(all_candidates),
        "candidate_count_text_root": len(root_candidates),
        "root_text_global_indices": text_indices,
        "all_candidate_ids_sha256": hashlib.sha256(
            json.dumps(
                [candidate["id"] for candidate in all_candidates], separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "root_candidate_ids_sha256": hashlib.sha256(
            json.dumps(
                [candidate["id"] for candidate in root_candidates],
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "vectors": vector_footprints,
    }


def _root_proposals(
    case: Mapping[str, Any],
    root_scores: Sequence[float],
    sizes: Mapping[str, float],
) -> list[dict[str, Any]]:
    all_candidates = case["candidates"]
    indices = root_text_indices(all_candidates)
    if len(indices) != len(root_scores):
        raise ValueError(
            "root score array is not aligned to text-only candidate indices"
        )
    best_by_node: dict[str, dict[str, Any]] = {}
    for global_index, score in zip(indices, root_scores, strict=True):
        candidate = all_candidates[global_index]
        node_id = str(candidate["node_id"])
        if node_id not in sizes:
            raise ValueError(f"root candidate node is missing from DOM: {node_id}")
        proposal = {
            "node_id": node_id,
            "candidate_id": str(candidate["id"]),
            "global_candidate_index": global_index,
            "score": float(score),
            "size": float(sizes[node_id]),
        }
        current = best_by_node.get(node_id)
        if current is None or (-proposal["score"], proposal["candidate_id"]) < (
            -current["score"],
            current["candidate_id"],
        ):
            best_by_node[node_id] = proposal
    return [proposal for proposal in best_by_node.values() if proposal["score"] > 0.0]


def _inside_root(candidate: Mapping[str, Any], root_node_id: str) -> bool:
    return str(candidate["node_id"]) == root_node_id or root_node_id in {
        str(ancestor) for ancestor in candidate.get("ancestors", [])
    }


def _independent_selection(
    case: Mapping[str, Any],
    fields: Sequence[str],
    field_scores: Mapping[str, Sequence[float]],
    hints: Mapping[str, Mapping[str, Any]],
    root_proposals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    all_candidates = case["candidates"]
    candidate_index = {
        str(candidate["id"]): i for i, candidate in enumerate(all_candidates)
    }
    ranked_roots = sorted(
        root_proposals,
        key=lambda row: (
            -float(row["score"]),
            str(row["node_id"]),
            str(row["candidate_id"]),
        ),
    )
    selected_root = ranked_roots[0] if ranked_roots else None
    if selected_root is not None:
        top_score = float(selected_root["score"])
        root_tie_count = sum(float(row["score"]) == top_score for row in ranked_roots)
    else:
        root_tie_count = 0
    selected_fields: dict[str, dict[str, Any]] = {}
    for field in fields:
        selected = None
        tie_count = 0
        if selected_root is not None:
            eligible_indices = [
                index
                for index, candidate in enumerate(all_candidates)
                if _inside_root(candidate, str(selected_root["node_id"]))
                and candidate.get("projection")
                in set(hints[field].get("projections", []))
            ]
            eligible_candidates = [all_candidates[index] for index in eligible_indices]
            eligible_scores = [
                float(field_scores[field][index]) for index in eligible_indices
            ]
            positive = [score for score in eligible_scores if score > 0.0]
            if positive:
                best_score = max(positive)
                tie_count = sum(score == best_score for score in positive)
            result = projection.apply_projection_policy(
                projection.POLICY_RESTRICTED_RANKING,
                eligible_scores,
                eligible_candidates,
                hints[field],
                top_k=5,
                top_nodes=5,
            )
            if result["results"]:
                best = result["results"][0]
                candidate_id = str(best["candidate_id"])
                selected = {
                    "candidate_id": candidate_id,
                    "global_candidate_index": candidate_index[candidate_id],
                    "node_id": str(best["node_id"]),
                    "projection": str(best["projection"]),
                    "score": float(best["candidate_score"]),
                }
        selected_fields[field] = {
            "selection": selected,
            "top_score_tie_count": tie_count,
            "optional_unmatched": selected is None,
        }
    return {
        "selected_root": None if selected_root is None else dict(selected_root),
        "root_score_tie_count": root_tie_count,
        "fields": selected_fields,
        "status": "complete" if selected_root is not None else "no_positive_root_score",
        "ambiguous": root_tie_count > 1
        or any(row["top_score_tie_count"] > 1 for row in selected_fields.values()),
        "incomplete_paths": [],
        "dp_transitions": 0,
        "bounds": dict(BOUNDS),
    }


def _joint_selection(
    case: Mapping[str, Any],
    fields: Sequence[str],
    field_scores: Mapping[str, Sequence[float]],
    hints: Mapping[str, Mapping[str, Any]],
    root_proposals: Sequence[Mapping[str, Any]],
    root_size_lambda: float,
) -> dict[str, Any]:
    all_candidates = case["candidates"]
    masked = {
        field: masked_field_scores(field_scores[field], all_candidates, hints[field])
        for field in fields
    }
    result = assign_jointly(
        masked,
        all_candidates,
        root_proposals,
        required_fields=(),
        bounds=BOUNDS,
        candidate_threshold=0.0,
        root_specificity_lambda=root_size_lambda,
    )
    candidate_index = {
        str(candidate["id"]): index for index, candidate in enumerate(all_candidates)
    }
    selected_fields: dict[str, dict[str, Any]] = {}
    for field, assignment in result["field_mapping"].items():
        candidate = assignment["candidate"]
        selected = None
        if candidate is not None:
            candidate_id = str(candidate["id"])
            selected = {
                "candidate_id": candidate_id,
                "global_candidate_index": candidate_index[candidate_id],
                "node_id": str(candidate["node_id"]),
                "projection": str(candidate["projection"]),
                "score": float(assignment["utility"]),
            }
        selected_fields[field] = {
            "selection": selected,
            "optional_unmatched": selected is None,
            "assignment_status": assignment["status"],
        }
    root = result["selected_root"]
    proposal_by_node = {str(row["node_id"]): row for row in root_proposals}
    selected_root = (
        None
        if root is None
        else {
            **dict(root),
            "candidate_id": proposal_by_node[str(root["node_id"])]["candidate_id"],
            "global_candidate_index": proposal_by_node[str(root["node_id"])][
                "global_candidate_index"
            ],
        }
    )
    return {
        "selected_root": selected_root,
        "fields": selected_fields,
        "status": result["status"],
        "ambiguous": result["ambiguous"],
        "ambiguity_reasons": result["ambiguity_reasons"],
        "optional_unmatched": result["optional_unmatched"],
        "incomplete_paths": result["incomplete_paths"],
        "optimal_within_declared_bounds": result["optimal_within_declared_bounds"],
        "dp_transitions": result["dp_transitions"],
        "root_size_penalty": result["root_size_penalty"],
        "total_utility": result["total_utility"],
        "candidate_threshold": result["candidate_threshold"],
        "candidate_threshold_is_probability": False,
        "bounds": result["bounds"],
    }


def _case_predictions(
    case: Mapping[str, Any],
    score_vectors: Mapping[str, Mapping[str, Sequence[float]]],
    seed_cases: Sequence[Mapping[str, Any]],
    query_descriptions: Mapping[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_candidates = case["candidates"]
    hints = projection_hints_for_seeds(seed_cases, FIELDS)
    sizes = root_size_fractions(case["document"]["nodes"])
    cache_index: dict[str, int] = {
        str(candidate["id"]): index for index, candidate in enumerate(all_candidates)
    }
    if len(cache_index) != len(all_candidates):
        raise ValueError(f"duplicate candidate id in {case['id']}")
    shape_vectors: dict[str, list[float]] = {}
    for field in FIELDS:
        references = seed_candidates_for_field(seed_cases, field)
        shape_vectors[field] = value_shape.score_candidates(
            SHAPE_METHOD,
            {"field": field, "description": query_descriptions[field]},
            all_candidates,
            references,
            REPRESENTATION,
            None,
        )
    outputs: list[dict[str, Any]] = []
    for scorer in SCORERS:
        raw = score_vectors[scorer]
        proposals = _root_proposals(case, raw["root"], sizes)
        if not proposals:
            # Retain a no-root result; do not synthesize a replacement proposal.
            proposals = []
        gated = {
            field: value_shape.multiplicative_shape_gate(
                raw[field], shape_vectors[field], strength=SHAPE_STRENGTH
            )
            for field in FIELDS
        }
        for variant, field_scores in (
            ("base", raw),
            ("value_shape_gate_alpha_0.5", gated),
        ):
            independent = _independent_selection(
                case, FIELDS, field_scores, hints, proposals
            )
            outputs.append(
                {
                    "case_id": str(case["id"]),
                    "scorer": scorer,
                    "score_variant": variant,
                    "selector": "independent_max",
                    "root_size_lambda": None,
                    **independent,
                }
            )
            for root_size_lambda in ROOT_SIZE_LAMBDAS:
                joint = _joint_selection(
                    case,
                    FIELDS,
                    field_scores,
                    hints,
                    proposals,
                    root_size_lambda,
                )
                outputs.append(
                    {
                        "case_id": str(case["id"]),
                        "scorer": scorer,
                        "score_variant": variant,
                        "selector": "injective_joint",
                        "root_size_lambda": root_size_lambda,
                        **joint,
                    }
                )
    metadata = {
        "candidate_count_all_fields": len(all_candidates),
        "candidate_count_text_root": len(root_text_indices(all_candidates)),
        "global_candidate_ids_sha256": hashlib.sha256(
            json.dumps(
                [candidate["id"] for candidate in all_candidates], separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "root_sizes_denominator_document_nodes": len(case["document"]["nodes"]),
        "seed_projection_hints": {
            field: {
                "status": hints[field]["status"],
                "supported": hints[field]["supported"],
                "projections": hints[field]["projections"],
                "reference_candidate_count": hints[field]["reference_candidate_count"],
                "reference_candidate_ids": hints[field].get(
                    "reference_candidate_ids", []
                ),
            }
            for field in FIELDS
        },
        "shape_method": SHAPE_METHOD,
        "shape_text_candidate_score_count_by_field": {
            field: len(shape_vectors[field]) for field in FIELDS
        },
    }
    return outputs, metadata


def _evaluate_predictions(
    predictions: Sequence[Mapping[str, Any]],
    case_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read query-case gold only after predictions have been serialized."""
    evaluated: list[dict[str, Any]] = []
    for prediction in predictions:
        case = case_by_id[str(prediction["case_id"])]
        candidate_by_id = {
            str(candidate["id"]): candidate for candidate in case["candidates"]
        }
        fields: dict[str, dict[str, Any]] = {}
        collisions: dict[tuple[str, str], list[str]] = defaultdict(list)
        exact_top1_count = 0
        wrong_owner_count = 0
        expected_present_count = 0
        for field in FIELDS:
            selection = prediction["fields"][field]["selection"]
            expected_ids = set(case["expected"].get(field, []))
            selected_id = None if selection is None else selection["candidate_id"]
            exact_top1 = (
                selected_id in expected_ids if expected_ids else selected_id is None
            )
            owner_correct: bool | None = None
            if selection is not None:
                candidate = candidate_by_id[selected_id]
                owner = str(case["owning_root_id"])
                owner_correct = str(candidate["node_id"]) == owner or owner in {
                    str(item) for item in candidate.get("ancestors", [])
                }
                if not owner_correct:
                    wrong_owner_count += 1
                collisions[
                    (str(candidate["node_id"]), str(candidate["projection"]))
                ].append(field)
            if expected_ids:
                expected_present_count += 1
            exact_top1_count += int(exact_top1)
            fields[field] = {
                "selected_candidate_id": selected_id,
                "expected_present": bool(expected_ids),
                "exact_top1": exact_top1,
                "owner_correct": owner_correct,
                "optional_unmatched": selection is None,
                "top_score_tie_count": int(
                    prediction["fields"][field].get("top_score_tie_count", 0)
                ),
            }
        collision_groups = [
            {"node_id": key[0], "projection": key[1], "fields": members}
            for key, members in sorted(collisions.items())
            if len(members) > 1
        ]
        collision_pairs = sum(
            len(group["fields"]) * (len(group["fields"]) - 1) // 2
            for group in collision_groups
        )
        evaluated.append(
            {
                "case_id": prediction["case_id"],
                "scorer": prediction["scorer"],
                "score_variant": prediction["score_variant"],
                "selector": prediction["selector"],
                "root_size_lambda": prediction["root_size_lambda"],
                "selected_root": prediction["selected_root"],
                "fields": fields,
                "exact_top1_fields": exact_top1_count,
                "field_count": len(FIELDS),
                "expected_present_fields": expected_present_count,
                "wrong_owner_count": wrong_owner_count,
                "collision_pairs": collision_pairs,
                "collision_groups": collision_groups,
                "ambiguous": prediction["ambiguous"],
                "root_score_tie_count": int(prediction.get("root_score_tie_count", 0)),
                "ambiguity_reasons": prediction.get("ambiguity_reasons", []),
                "incomplete_paths": prediction.get("incomplete_paths", []),
                "optional_unmatched_fields": [
                    field
                    for field, detail in fields.items()
                    if detail["optional_unmatched"]
                ],
                "dp_transitions": prediction["dp_transitions"],
                "bounds": prediction["bounds"],
                "status": prediction["status"],
            }
        )
    grouped: dict[tuple[str, str, str, float | None], list[Mapping[str, Any]]] = (
        defaultdict(list)
    )
    for row in evaluated:
        grouped[
            (
                str(row["scorer"]),
                str(row["score_variant"]),
                str(row["selector"]),
                row["root_size_lambda"],
            )
        ].append(row)
    summaries = []
    for (scorer, variant, selector, size_lambda), rows in sorted(
        grouped.items(), key=lambda item: tuple(str(value) for value in item[0])
    ):
        total_fields = sum(int(row["field_count"]) for row in rows)
        summaries.append(
            {
                "scorer": scorer,
                "score_variant": variant,
                "selector": selector,
                "root_size_lambda": size_lambda,
                "case_count": len(rows),
                "exact_top1_fields": sum(int(row["exact_top1_fields"]) for row in rows),
                "field_trials": total_fields,
                "expected_present_fields": sum(
                    int(row["expected_present_fields"]) for row in rows
                ),
                "wrong_owner_count": sum(int(row["wrong_owner_count"]) for row in rows),
                "collision_pairs": sum(int(row["collision_pairs"]) for row in rows),
                "ambiguous_case_count": sum(bool(row["ambiguous"]) for row in rows),
                "incomplete_case_count": sum(
                    bool(row["incomplete_paths"]) for row in rows
                ),
                "optional_unmatched_fields": sum(
                    len(row["optional_unmatched_fields"]) for row in rows
                ),
                "tied_field_count": sum(
                    detail["top_score_tie_count"] > 1
                    for row in rows
                    for detail in row["fields"].values()
                ),
                "root_tie_case_count": sum(
                    int(row["root_score_tie_count"]) > 1 for row in rows
                ),
                "max_dp_transitions": max(int(row["dp_transitions"]) for row in rows),
            }
        )
    return evaluated, {"by_policy": summaries, "by_case_policy": evaluated}


def run_experiment(
    *,
    destination: Path = OUTPUT_ROOT,
    case_ids: Sequence[str] | None = None,
    output_name: str = "micro-v1.json",
) -> dict[str, Any]:
    """Create a bounded cached-score result without recomputing base scores."""
    selected_cases = choose_case_ids(case_ids)
    if Path(output_name).name != output_name or not output_name.endswith(".json"):
        raise ValueError("output_name must be a single JSON filename")
    resolved_destination = destination.resolve()
    if not resolved_destination.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ValueError(
            "output destination must stay under the declared generated directory"
        )
    prediction_name = output_name.replace(".json", ".predictions.json")
    if (resolved_destination / output_name).exists() or (
        resolved_destination / prediction_name
    ).exists():
        raise FileExistsError(
            "refusing to replace an existing micro-experiment artifact"
        )
    started_cpu = time.process_time()
    started_wall = time.perf_counter()
    frozen, data, input_paths = _read_source()
    case_by_id = {str(case["id"]): case for case in data["cases"]}
    missing_cases = set((*SEED_CASE_IDS, *selected_cases)) - case_by_id.keys()
    if missing_cases:
        raise ValueError(
            "required original cases absent from source corpus: "
            f"{sorted(missing_cases)}"
        )
    seed_cases = [case_by_id[case_id] for case_id in SEED_CASE_IDS]
    query_descriptions = frozen["queries"]
    destination.mkdir(parents=True, exist_ok=True)
    prediction_rows: list[dict[str, Any]] = []
    per_case_metadata: list[dict[str, Any]] = []
    per_case_timings: list[dict[str, Any]] = []
    stop_reason = None
    for case_id in selected_cases:
        case_started_cpu = time.process_time()
        case_started_wall = time.perf_counter()
        case = case_by_id[case_id]
        score_vectors, cache_metadata = _load_case_cache(
            frozen, data, case, input_paths["minilm_digest"]
        )
        case_predictions, metadata = _case_predictions(
            case, score_vectors, seed_cases, query_descriptions
        )
        prediction_rows.extend(case_predictions)
        per_case_metadata.append(
            {"case_id": case_id, **metadata, "score_cache": cache_metadata}
        )
        cpu_seconds = time.process_time() - case_started_cpu
        wall_seconds = time.perf_counter() - case_started_wall
        per_case_timings.append(
            {
                "case_id": case_id,
                "cpu_seconds": cpu_seconds,
                "wall_seconds": wall_seconds,
            }
        )
        if len(per_case_timings) == 1 and cpu_seconds > FIRST_CASE_CPU_LIMIT_SECONDS:
            stop_reason = "first_case_cpu_exceeded_3_second_microbenchmark_cap"
            break

    prediction_path = resolved_destination / prediction_name
    prediction_document = {
        "format": "cached-joint-shape-predictions-v1",
        "case_ids": [row["case_id"] for row in per_case_metadata],
        "target_gold_read": False,
        "reference_group": REFERENCE_GROUP,
        "representation": REPRESENTATION,
        "scorers": list(SCORERS),
        "policies_per_scorer": 6,
        "predictions": prediction_rows,
    }
    prediction_path.write_text(
        json.dumps(prediction_document, indent=2) + "\n", encoding="utf-8"
    )
    prediction_sha = sha256_file(prediction_path)

    evaluation_started_cpu = time.process_time()
    evaluation_started_wall = time.perf_counter()
    evaluated, evaluation_summary = _evaluate_predictions(prediction_rows, case_by_id)
    evaluation_cpu = time.process_time() - evaluation_started_cpu
    evaluation_wall = time.perf_counter() - evaluation_started_wall
    total_cpu = time.process_time() - started_cpu
    total_wall = time.perf_counter() - started_wall

    source_files = [
        SOURCE_RUN / "frozen.json",
        SOURCE_RUN / "corpus.json",
        SEMANTIC_ARTIFACT,
        PRODUCT_ROOT / "run_matrix.py",
        PRODUCT_ROOT / "methods.py",
        EXTENSIONS / "migrate_scores.py",
        EXTENSIONS / "joint_assignment.py",
        EXTENSIONS / "value_shape.py",
        EXTENSIONS / "projection.py",
        Path(__file__),
        Path(__file__).with_name("test_cached_joint_shape.py"),
    ]
    input_hashes = {
        str(path.relative_to(ROOT)): sha256_file(path) for path in source_files
    }
    summary = {
        "format": "cached-joint-shape-micro-v1",
        "python_version": sys.version,
        "claim_scope": (
            "Four original cases from one template; a bounded "
            "mechanism demonstration, not a population benchmark."
        ),
        "case_ids": [row["case_id"] for row in per_case_metadata],
        "case_limit": 4,
        "reference_group": REFERENCE_GROUP,
        "reference_case_ids": list(SEED_CASE_IDS),
        "representation": REPRESENTATION,
        "fields": list(FIELDS),
        "scorers": list(SCORERS),
        "score_source": (
            "immutable cached arrays only; no base scorer or "
            "embedding inference was invoked"
        ),
        "semantic_cache_binding": {
            "artifact_path": str(SEMANTIC_ARTIFACT.relative_to(ROOT)),
            "artifact_sha256": input_paths["minilm_digest"],
            "vectors_loaded": False,
        },
        "projection_policy": {
            "hint_source": (
                "expected candidates from seed cases obj-001 and obj-002 only"
            ),
            "selection_policy": projection.POLICY_RESTRICTED_RANKING,
            "candidate_mask_sentinel": -1.0,
            "candidate_threshold": 0.0,
            "field_candidate_indices_preserved": True,
            "root_candidate_indices": (
                "text-only subset, recorded against the full candidate index"
            ),
        },
        "selection_policies": {
            "independent_max": (
                "Highest root score selects one root; fields are "
                "independently projection-restricted within that "
                "root."
            ),
            "injective_joint": (
                "joint_assignment exact DP with distinct (node_id, "
                "projection) evidence keys, lambda 0.0 and 0.2."
            ),
            "value_shape_gate": {
                **value_shape.GATE_METADATA,
                "method": SHAPE_METHOD,
                "strength": SHAPE_STRENGTH,
                "field_scores_only": True,
                "root_scores_gated": False,
            },
        },
        "bounds": {
            **BOUNDS,
            "candidate_threshold_is_probability": False,
            "max_roots_are_ranked_by_cached_root_score_before_size_penalty": True,
            "required_fields": [],
            "all_six_fields_are_scored_as_optional_for_selection": True,
            "first_case_cpu_microbenchmark_limit_seconds": FIRST_CASE_CPU_LIMIT_SECONDS,
        },
        "target_gold_evaluation": {
            "predictions_written_before_gold_read": True,
            "prediction_file": prediction_path.name,
            "prediction_file_sha256": prediction_sha,
            "exact_top1": (
                "selected candidate id is present in the original "
                "target expected-id set; absent gold is exact only "
                "when no candidate is selected."
            ),
            "wrong_owner": (
                "selected candidate node is outside the target "
                "owning_root_id ancestry, evaluated after prediction "
                "serialization."
            ),
        },
        "timings": {
            "prediction_cpu_seconds": sum(
                row["cpu_seconds"] for row in per_case_timings
            ),
            "prediction_wall_seconds": sum(
                row["wall_seconds"] for row in per_case_timings
            ),
            "evaluation_cpu_seconds": evaluation_cpu,
            "evaluation_wall_seconds": evaluation_wall,
            "total_cpu_seconds": total_cpu,
            "total_wall_seconds": total_wall,
            "per_case": per_case_timings,
            "stop_reason": stop_reason,
        },
        "source_hashes": input_hashes,
        "case_inputs": per_case_metadata,
        "evaluation": evaluation_summary,
        "limitations": [
            (
                "Only original obj-003 through obj-006 from one site "
                "template are included; findings do not generalize "
                "to a benchmark population."
            ),
            (
                "Projection support is learned from the two labeled "
                "seed cases and can miss valid target-only "
                "projections."
            ),
            (
                "Root max-3 and per-field top-5 truncation are "
                "explicit; bounded or incomplete assignments are not "
                "full-corpus optima."
            ),
            (
                "The flat injective assignment can still combine "
                "sibling product branches within one proposed root; "
                "it does not infer nested ownership."
            ),
            (
                "The value-form gate is a ranking sensitivity "
                "experiment; alpha 0.5 is not confidence or a "
                "probability."
            ),
            (
                "Root size is a DOM-descendant fraction, not a "
                "product relevance or correctness signal."
            ),
        ],
    }
    summary_path = resolved_destination / output_name
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--case-ids", nargs="*", default=None)
    parser.add_argument("--output-name", default="micro-v1.json")
    args = parser.parse_args()
    summary = run_experiment(
        destination=args.destination,
        case_ids=args.case_ids,
        output_name=args.output_name,
    )
    print(
        json.dumps(
            {
                "case_ids": summary["case_ids"],
                "prediction_count": len(summary["evaluation"]["by_case_policy"]),
                "timings": summary["timings"],
                "output": str(args.destination / args.output_name),
                "predictions": str(
                    args.destination
                    / args.output_name.replace(".json", ".predictions.json")
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
