"""Gold-blind node localization and source projection policies."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

POLICY_VALUE_RANKING = "original_value_ranking"
POLICY_NODE_THEN_PROJECT = "node_rank_then_project"
POLICY_RESTRICTED_RANKING = "projection_restricted_ranking"
POLICIES = (
    POLICY_VALUE_RANKING,
    POLICY_NODE_THEN_PROJECT,
    POLICY_RESTRICTED_RANKING,
)
MAX_PROJECTION_HINTS = 64
MAX_RANK_LIMIT = 50
_ATTRIBUTE_PROJECTION = re.compile(r"^@[A-Za-z_][A-Za-z0-9_.:-]*$")


def reference_projection_hints(
    seed_candidates: Sequence[Mapping[str, Any]], field: str
) -> dict[str, Any]:
    """Infer allowed source projections from labeled seed candidates only.

    This function intentionally accepts no query-page gold annotations. An empty
    seed list produces an unsupported hint state rather than a default-to-text
    behavior. Root references are accepted only when their observed projection
    is text.
    """
    if not isinstance(field, str) or not field:
        raise ValueError("field must be a non-empty string")
    if not seed_candidates:
        return {
            "field": field,
            "status": "no_reference_candidates",
            "supported": False,
            "projections": [],
            "reference_candidate_count": 0,
        }
    if len(seed_candidates) > MAX_PROJECTION_HINTS:
        return {
            "field": field,
            "status": "reference_hint_budget_exceeded",
            "supported": False,
            "projections": [],
            "reference_candidate_count": len(seed_candidates),
        }

    projections: set[str] = set()
    for candidate in seed_candidates:
        if not isinstance(candidate, Mapping):
            return {
                "field": field,
                "status": "invalid_reference_candidate",
                "supported": False,
                "projections": [],
                "reference_candidate_count": len(seed_candidates),
            }
        projection = candidate.get("projection")
        if not isinstance(projection, str) or not (
            projection == "text" or _ATTRIBUTE_PROJECTION.fullmatch(projection)
        ):
            return {
                "field": field,
                "status": "invalid_reference_projection",
                "supported": False,
                "projections": [],
                "reference_candidate_count": len(seed_candidates),
            }
        projections.add(projection)

    if field == "root" and projections != {"text"}:
        return {
            "field": field,
            "status": "root_requires_text_reference",
            "supported": False,
            "projections": [],
            "reference_candidate_count": len(seed_candidates),
        }
    if not projections:
        return {
            "field": field,
            "status": "no_reference_projections",
            "supported": False,
            "projections": [],
            "reference_candidate_count": len(seed_candidates),
        }
    ordered = sorted(projections, key=lambda value: (value != "text", value))
    return {
        "field": field,
        "status": "supported",
        "supported": True,
        "projections": ordered,
        "reference_candidate_count": len(seed_candidates),
        "reference_candidate_ids": sorted(
            str(candidate["id"])
            for candidate in seed_candidates
            if isinstance(candidate.get("id"), (str, int))
        ),
    }


def apply_projection_policy(
    policy: str,
    scores: Sequence[float],
    candidates: Sequence[Mapping[str, Any]],
    hints: Mapping[str, Any],
    *,
    source_candidates: Sequence[Mapping[str, Any]] | None = None,
    top_k: int = 5,
    top_nodes: int = 5,
) -> dict[str, Any]:
    """Apply a value, node-then-project, or projection-restricted policy.

    ``scores`` align exactly with ``candidates``. For node-then-project,
    ``source_candidates`` is the complete source-side projection map; it may
    contain same-node projections that the scoring pool did not include. A
    node's maximum score localizes that node only. It is never copied to a
    newly materialized projection as a probability or projection score.
    """
    if policy not in POLICIES:
        raise ValueError(f"unknown projection policy: {policy}")
    if not isinstance(hints, Mapping):
        raise TypeError("hints must be a projection-hint mapping")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k not in {5, 50}:
        raise ValueError("top_k must be either 5 or 50")
    if (
        not isinstance(top_nodes, int)
        or isinstance(top_nodes, bool)
        or top_nodes not in {5, 50}
    ):
        raise ValueError("top_nodes must be either 5 or 50")
    if len(scores) != len(candidates):
        raise ValueError("score count must match the scored candidate pool")

    scored = _validate_candidates(candidates, scores, "scored")
    source = _validate_candidates(
        source_candidates if source_candidates is not None else candidates,
        None,
        "source",
    )
    candidate_ids = {str(candidate["id"]) for candidate in scored}
    positive_scores = [
        (float(score), candidate)
        for score, candidate in zip(scores, scored, strict=True)
        if float(score) > 0.0
    ]
    hint_status = str(hints.get("status", "unsupported"))
    projections = _validated_hints(hints)
    if policy != POLICY_VALUE_RANKING and (
        not hints.get("supported") or not projections
    ):
        return _empty_result(
            policy,
            "unsupported_projection_hints",
            hint_status,
            projections,
            len(scored),
        )

    if policy == POLICY_VALUE_RANKING:
        ordered = sorted(
            (
                (float(score), candidate)
                for score, candidate in zip(scores, scored, strict=True)
                if float(score) > 0.0
            ),
            key=lambda pair: (-pair[0], str(pair[1]["id"])),
        )[:top_k]
        results = [
            {
                "candidate_id": str(candidate["id"]),
                "node_id": str(candidate["node_id"]),
                "projection": str(candidate["projection"]),
                "value": str(candidate.get("text", "")),
                "candidate": dict(candidate),
                "candidate_score": value_score,
                "score_role": "original_candidate_score",
            }
            for value_score, candidate in ordered
        ]
        node_ranking = _node_ranking(positive_scores, top_nodes)
        return {
            "policy": policy,
            "status": "complete",
            "projection_source": "scored_candidate_pool",
            "projection_scores_are_probabilities": False,
            "original_model_pool_recall_applies_to_materialized_candidates": True,
            "hint_status": hint_status,
            "hints": projections,
            "results": results,
            "selected_nodes": node_ranking,
            "node_ranking": node_ranking,
            "source_projection_reads": 0,
            "extra_source_projection_reads": 0,
            "absent_projection_count": 0,
            "duplicate_source_candidates": 0,
            "scored_candidate_count": len(scored),
        }

    if not positive_scores:
        return _empty_result(
            policy,
            "no_positive_scores",
            hint_status,
            projections,
            len(scored),
        )

    if policy == POLICY_RESTRICTED_RANKING:
        restricted = [
            (score, candidate)
            for score, candidate in positive_scores
            if candidate["projection"] in projections
        ]
        ordered = sorted(
            restricted,
            key=lambda pair: (-pair[0], str(pair[1]["id"])),
        )[:top_k]
        results = [
            {
                "candidate_id": str(candidate["id"]),
                "node_id": str(candidate["node_id"]),
                "projection": str(candidate["projection"]),
                "value": str(candidate.get("text", "")),
                "candidate": dict(candidate),
                "candidate_score": value_score,
                "score_role": "original_candidate_score_with_projection_filter",
            }
            for value_score, candidate in ordered
        ]
        node_ranking = _node_ranking(restricted, top_nodes)
        status = "complete" if results else "no_supported_candidates"
        return {
            "policy": policy,
            "status": status,
            "projection_source": "scored_candidate_pool",
            "projection_scores_are_probabilities": False,
            "original_model_pool_recall_applies_to_materialized_candidates": True,
            "hint_status": hint_status,
            "hints": projections,
            "results": results,
            "selected_nodes": node_ranking,
            "node_ranking": node_ranking,
            "source_projection_reads": 0,
            "extra_source_projection_reads": 0,
            "absent_projection_count": 0,
            "duplicate_source_candidates": 0,
            "scored_candidate_count": len(scored),
        }

    node_ranking = _node_ranking(positive_scores, top_nodes)
    selected_nodes = [
        (entry["node_id"], entry["localization_score"]) for entry in node_ranking
    ]
    source_by_projection: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(
        list
    )
    for candidate in source:
        source_by_projection[
            (str(candidate["node_id"]), str(candidate["projection"]))
        ].append(candidate)
    for values in source_by_projection.values():
        values.sort(key=lambda candidate: str(candidate["id"]))

    results = []
    missing_projections = []
    reads = 0
    extra_reads = 0
    duplicate_candidates = 0
    for node_id, localization_score in selected_nodes:
        for projection in projections:
            reads += 1
            matches = source_by_projection.get((node_id, projection), [])
            if not matches:
                missing_projections.append(
                    {"node_id": node_id, "projection": projection}
                )
                continue
            duplicate_candidates += max(0, len(matches) - 1)
            for candidate in matches:
                candidate_id = str(candidate["id"])
                was_scored = candidate_id in candidate_ids
                extra_reads += not was_scored
                results.append(
                    {
                        "candidate_id": candidate_id,
                        "node_id": node_id,
                        "projection": projection,
                        "value": str(candidate.get("text", "")),
                        "candidate": dict(candidate),
                        "candidate_was_scored": was_scored,
                        "localization_score": localization_score,
                        "projection_score": None,
                        "score_role": (
                            "node_localization_only; projected value is unscored"
                        ),
                    }
                )

    if results and missing_projections:
        status = "partial_projection_materialization"
    elif results:
        status = "complete"
    else:
        status = "no_supported_projection_at_selected_nodes"
    return {
        "policy": policy,
        "status": status,
        "projection_source": "source_candidate_map",
        "projection_scores_are_probabilities": False,
        "original_model_pool_recall_applies_to_materialized_candidates": False,
        "hint_status": hint_status,
        "hints": projections,
        "results": results,
        "selected_nodes": node_ranking,
        "node_ranking": node_ranking,
        "source_projection_reads": reads,
        "extra_source_projection_reads": extra_reads,
        "absent_projection_count": len(missing_projections),
        "missing_projections": missing_projections,
        "duplicate_source_candidates": duplicate_candidates,
        "scored_candidate_count": len(scored),
    }


def evaluate_node_location(
    ranked_results: Sequence[Mapping[str, Any]],
    gold_candidate_ids: Sequence[str],
    source_candidates: Sequence[Mapping[str, Any]],
    owning_root_id: str,
    *,
    expected_present: bool,
    expected_status: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """Evaluate node localization separately from projection and value quality.

    Gold candidate IDs and source ownership enter only here, after a policy has
    produced its candidate/node ordering. This helper never scores candidate
    text or compares a retrieved value with the gold field value.
    """
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k not in {5, 50}:
        raise ValueError("top_k must be either 5 or 50")
    candidate_by_id = _validate_candidates(source_candidates, None, "source")
    candidate_map = {str(candidate["id"]): candidate for candidate in candidate_by_id}
    gold_ids = {str(candidate_id) for candidate_id in gold_candidate_ids}
    if expected_status == "absent" and (expected_present or gold_ids):
        raise ValueError(
            "absent field must not carry a present flag or gold candidate IDs"
        )
    if expected_status == "present_dom" and not expected_present:
        raise ValueError("present DOM field must carry expected_present=true")
    if expected_status in {"present_external_url", "unavailable"} and gold_ids:
        raise ValueError(
            "external or unavailable fields must not claim DOM gold candidates"
        )
    if expected_status == "present_external_url" and not expected_present:
        raise ValueError("external URL identity must carry expected_present=true")
    missing_gold = sorted(gold_ids - candidate_map.keys())
    if missing_gold:
        return {
            "status": "gold_candidate_missing_from_source",
            "missing_gold_candidate_ids": missing_gold,
            "quality_evaluable": False,
            "expected_present": expected_present,
            "expected_status": expected_status,
            "value_correct": None,
        }

    gold_nodes = {
        str(candidate_map[candidate_id]["node_id"]) for candidate_id in gold_ids
    }
    predictions = []
    seen_nodes = set()
    for result in ranked_results:
        node_id = _result_node_id(result)
        if node_id is None or node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        predictions.append(result)
        if len(predictions) >= top_k:
            break

    external = expected_status in {"present_external_url", "unavailable"}
    quality_evaluable = expected_status in {"present_dom", "absent"}
    operational_present = expected_present and expected_status in {
        "present_dom",
        "present_unlocatable",
        "ambiguous",
        "ambiguous_dom",
    }
    predicted_nodes = [_result_node_id(result) for result in predictions]
    if external:
        return {
            "status": "present_without_dom_projection"
            if expected_present
            else "unavailable",
            "quality_evaluable": False,
            "operational_present": False,
            "expected_present": expected_present,
            "expected_status": expected_status,
            "gold_node_count": len(gold_nodes),
            "predicted_node_ids": predicted_nodes,
            "node_hit_at_k": {str(k): None for k in (1, 3, 5)},
            "node_top1_correct": None,
            "owned_node_top1_correct": None,
            "owner_correct": None,
            "value_correct": None,
        }

    if not quality_evaluable:
        return {
            "status": "present_but_unlocatable"
            if operational_present
            else "not_evaluable",
            "quality_evaluable": False,
            "operational_present": operational_present,
            "expected_present": expected_present,
            "expected_status": expected_status,
            "gold_node_count": len(gold_nodes),
            "predicted_node_ids": predicted_nodes,
            "node_hit_at_k": {str(k): False for k in (1, 3, 5)},
            "node_top1_correct": False if operational_present else None,
            "owned_node_top1_correct": False if operational_present else None,
            "owner_correct": False if operational_present else None,
            "value_correct": None,
        }

    if not expected_present:
        abstained = not predictions
        return {
            "status": "complete_absent_field",
            "quality_evaluable": True,
            "operational_present": False,
            "expected_present": False,
            "expected_status": expected_status,
            "gold_node_count": 0,
            "predicted_node_ids": predicted_nodes,
            "node_hit_at_k": {str(k): False for k in (1, 3, 5)},
            "node_top1_correct": abstained,
            "owned_node_top1_correct": abstained,
            "owner_correct": None,
            "abstained": abstained,
            "value_correct": None,
        }

    hits = {str(k): bool(set(predicted_nodes[:k]) & gold_nodes) for k in (1, 3, 5)}
    top = predictions[0] if predictions else None
    top_node = _result_node_id(top) if top is not None else None
    top_candidate = _result_candidate(top) if top is not None else None
    owner_correct = bool(
        top_node is not None
        and top_candidate is not None
        and (
            top_node == str(owning_root_id)
            or str(owning_root_id)
            in {str(value) for value in top_candidate.get("ancestors", [])}
        )
    )
    location_correct = top_node in gold_nodes if top_node is not None else False
    return {
        "status": "complete_present_field",
        "quality_evaluable": True,
        "operational_present": True,
        "expected_present": True,
        "expected_status": expected_status,
        "gold_node_count": len(gold_nodes),
        "predicted_node_ids": predicted_nodes,
        "node_hit_at_k": hits,
        "node_top1_correct": location_correct,
        "owner_correct": owner_correct,
        "owned_node_top1_correct": location_correct and owner_correct,
        "abstained": top is None,
        "value_correct": None,
    }


def _result_node_id(result: Mapping[str, Any]) -> str | None:
    node_id = result.get("node_id")
    if node_id is not None:
        return str(node_id)
    candidate = _result_candidate(result)
    if candidate is None or candidate.get("node_id") is None:
        return None
    return str(candidate["node_id"])


def _result_candidate(result: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if result is None:
        return None
    candidate = result.get("candidate")
    if isinstance(candidate, Mapping):
        return candidate
    return result


def _empty_result(policy, status, hint_status, projections, scored_count):
    return {
        "policy": policy,
        "status": status,
        "projection_source": (
            "source_candidate_map"
            if policy == POLICY_NODE_THEN_PROJECT
            else "scored_candidate_pool"
        ),
        "projection_scores_are_probabilities": False,
        "original_model_pool_recall_applies_to_materialized_candidates": policy
        != POLICY_NODE_THEN_PROJECT,
        "hint_status": hint_status,
        "hints": projections,
        "results": [],
        "selected_nodes": [],
        "node_ranking": [],
        "source_projection_reads": 0,
        "extra_source_projection_reads": 0,
        "absent_projection_count": 0,
        "duplicate_source_candidates": 0,
        "scored_candidate_count": scored_count,
    }


def _validated_hints(hints):
    raw = hints.get("projections", [])
    if not isinstance(raw, (list, tuple)):
        raise ValueError("hint projections must be a list or tuple")
    if len(raw) > MAX_PROJECTION_HINTS:
        raise ValueError("projection hint count exceeds its bound")
    projections = set()
    for projection in raw:
        if not isinstance(projection, str) or not (
            projection == "text" or _ATTRIBUTE_PROJECTION.fullmatch(projection)
        ):
            raise ValueError("invalid source projection hint")
        projections.add(projection)
    return sorted(projections, key=lambda value: (value != "text", value))


def _node_ranking(scored_candidates, limit):
    by_node: dict[str, tuple[float, list[Mapping[str, Any]]]] = {}
    for value_score, candidate in scored_candidates:
        node_id = str(candidate["node_id"])
        current = by_node.get(node_id)
        if current is None or value_score > current[0]:
            by_node[node_id] = (float(value_score), [candidate])
        elif value_score == current[0]:
            current[1].append(candidate)
    ordered = sorted(by_node.items(), key=lambda item: (-item[1][0], item[0]))[:limit]
    result = []
    for node_id, (value_score, best_candidates) in ordered:
        representative = min(
            best_candidates, key=lambda candidate: str(candidate["id"])
        )
        result.append(
            {
                "node_id": node_id,
                "localization_score": value_score,
                "source_candidate_ids": sorted(
                    str(candidate["id"]) for candidate in best_candidates
                ),
                "candidate": dict(representative),
                "score_role": (
                    "node localization only; projection/value remains separate"
                ),
            }
        )
    return result


def _validate_candidates(candidates, scores, label):
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise TypeError(f"{label} candidates must be a sequence")
    result = []
    identities = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise TypeError(f"{label} candidate must be a mapping")
        if any(
            key in candidate
            for key in ("expected", "expected_values", "gold", "field_name")
        ):
            raise ValueError(f"{label} candidates must not contain target annotations")
        if not isinstance(candidate.get("id"), (str, int)):
            raise ValueError(f"{label} candidate has no stable ID")
        if not isinstance(candidate.get("node_id"), (str, int)):
            raise ValueError(f"{label} candidate has no source node ID")
        if not isinstance(candidate.get("text"), str):
            raise ValueError(f"{label} candidate text must be a string")
        projection = candidate.get("projection")
        if not isinstance(projection, str) or not (
            projection == "text" or _ATTRIBUTE_PROJECTION.fullmatch(projection)
        ):
            raise ValueError(f"{label} candidate has an invalid projection")
        candidate_id = str(candidate["id"])
        if candidate_id in identities:
            raise ValueError(f"duplicate {label} candidate ID: {candidate_id}")
        identities.add(candidate_id)
        result.append(candidate)

    if scores is not None:
        if not isinstance(scores, Sequence) or isinstance(scores, (str, bytes)):
            raise TypeError("scores must be a numeric sequence")
        if len(scores) != len(result):
            raise ValueError("score count must match the scored candidate pool")
        for value in scores:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError("scores must contain numeric values")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError("scores must be finite and nonnegative")
    return result


def _ranked(indices, scores, candidates, top_k):
    return [
        (float(scores[index]), candidates[index])
        for index in sorted(
            indices,
            key=lambda index: (-float(scores[index]), str(candidates[index]["id"])),
        )[:top_k]
        if float(scores[index]) > 0.0
    ]
