"""Exact-score tie sensitivity for six saved same-site heldout pages.

The audit recomputes only the frozen, dependency-free structural scorer. It
writes a complete equal-score partition before reading heldout gold, then
computes uniform tie-order expectations and worst/best outcomes analytically.
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
from math import comb
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PRODUCT_ROOT = ROOT / "experiments" / "product-retrieval"
SAME_SITE_ROOT = ROOT / ".generated" / "product-retrieval-same-site-v1"
TARGET_PLAN = SAME_SITE_ROOT / "target-plan.json"
WAVE_COMPLETE = SAME_SITE_ROOT / "same-site-view" / "wave-complete.json"
FRESH_ROOT = ROOT / ".generated" / "product-retrieval-fresh"
QUALIFIED_MAP = (
    ROOT / ".generated" / "product-retrieval-gold-v2" / "qualified-alternatives.json"
)
OUTPUT_ROOT = ROOT / ".generated" / "product-retrieval-same-site-ties-v1"
METHOD = "structural_jaccard"
REPRESENTATION = "context"
MODE = "global"
ENCODERS = ("minilm", "bge-small")
CUTOFFS = (1, 3, 5)

if str(PRODUCT_ROOT) not in sys.path:
    sys.path.insert(0, str(PRODUCT_ROOT))

methods = importlib.import_module("methods")
run_matrix = importlib.import_module("run_matrix")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(raw.encode("utf-8"))


def build_score_groups(
    scores: Sequence[float], candidates: Sequence[Mapping[str, Any]]
) -> tuple[list[int], list[dict[str, Any]]]:
    """Return deterministic runner order and the full exact-score partition."""
    if len(scores) != len(candidates):
        raise ValueError("score and candidate counts must match")
    ids = [str(candidate["id"]) for candidate in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("candidate IDs must be unique")
    normalized = [float(score) for score in scores]
    if any(not math.isfinite(score) or score < 0 for score in normalized):
        raise ValueError("scores must be finite and nonnegative")
    # The evaluator abstains on exact zero scores; zeros remain in the full
    # vector but do not participate in retrieval ranking or ties.
    ranked = sorted(
        (index for index, score in enumerate(normalized) if score > 0.0),
        key=lambda index: (-normalized[index], ids[index]),
    )
    groups: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(ranked):
        score = normalized[ranked[cursor]]
        end = cursor + 1
        while end < len(ranked) and normalized[ranked[end]] == score:
            end += 1
        groups.append(
            {
                "score": score,
                "rank_start": cursor + 1,
                "rank_end": end,
                "candidate_count": end - cursor,
                "candidate_ids": [ids[index] for index in ranked[cursor:end]],
            }
        )
        cursor = end
    return ranked, groups


def tie_sensitivity(
    scores: Sequence[float],
    candidates: Sequence[Mapping[str, Any]],
    gold_ids: set[str],
    ranked: Sequence[int] | None = None,
    groups: Sequence[Mapping[str, Any]] | None = None,
    cutoffs: Sequence[int] = CUTOFFS,
) -> dict[int, dict[str, Any]]:
    """Calculate exact hit probability and recall bounds within cutoff ties."""
    if ranked is None or groups is None:
        ranked, groups = build_score_groups(scores, candidates)
    population = {str(candidate["id"]) for candidate in candidates}
    gold = {str(candidate_id) for candidate_id in gold_ids}
    in_population = gold & population
    eligible_ids = {str(candidates[index]["id"]) for index in ranked}
    eligible_gold = in_population & eligible_ids
    zero_score_gold = in_population - eligible_ids
    missing = gold - population
    result: dict[int, dict[str, Any]] = {}
    for requested_k in cutoffs:
        if not isinstance(requested_k, int) or requested_k < 1:
            raise ValueError("cutoffs must be positive integers")
        k = min(requested_k, len(ranked))
        fixed_gold = 0
        crossing = None
        for group in groups:
            start, end = int(group["rank_start"]), int(group["rank_end"])
            group_gold = set(group["candidate_ids"]) & eligible_gold
            if end <= k:
                fixed_gold += len(group_gold)
            elif start <= k < end:
                crossing = group
                break
            else:
                break

        expected_count = float(fixed_gold)
        worst_count = best_count = fixed_gold
        hit_probability = 1.0 if fixed_gold else 0.0
        worst_hit = best_hit = int(fixed_gold > 0)
        boundary = None
        if crossing is not None:
            group_ids = [str(value) for value in crossing["candidate_ids"]]
            group_gold_ids = sorted(set(group_ids) & eligible_gold)
            n, g = len(group_ids), len(group_gold_ids)
            slots = k - int(crossing["rank_start"]) + 1
            expected_in_group = slots * g / n
            worst_in_group = max(0, slots - (n - g))
            best_in_group = min(g, slots)
            expected_count += expected_in_group
            worst_count += worst_in_group
            best_count += best_in_group
            if not fixed_gold and g and slots:
                no_gold_orders = 0 if slots > n - g else comb(n - g, slots)
                hit_probability = 1.0 - no_gold_orders / comb(n, slots)
                worst_hit = int(worst_in_group > 0)
                best_hit = int(best_in_group > 0)
            boundary = {
                "score": crossing["score"],
                "rank_start": crossing["rank_start"],
                "rank_end": crossing["rank_end"],
                "candidate_count": n,
                "gold_candidate_count": g,
                "gold_candidate_ids": group_gold_ids,
                "slots_taken": slots,
                "expected_gold_in_slots": expected_in_group,
            }

        actual_ids = {str(candidates[index]["id"]) for index in ranked[:k]}
        actual_gold = len(actual_ids & in_population)
        denominator = len(gold) or None
        result[requested_k] = {
            "cutoff": k,
            "gold_candidate_count": len(gold),
            "gold_candidates_in_score_universe": len(in_population),
            "gold_candidates_with_positive_scores": len(eligible_gold),
            "gold_candidates_with_zero_scores": len(zero_score_gold),
            "zero_score_gold_candidate_ids": sorted(zero_score_gold),
            "gold_candidate_ids_missing_from_score_universe": sorted(missing),
            "actual_gold_retrieved": actual_gold,
            "actual_hit": bool(actual_gold),
            "expected_gold_retrieved": expected_count,
            "expected_hit_probability": hit_probability,
            "worst_gold_retrieved": worst_count,
            "best_gold_retrieved": best_count,
            "worst_hit": worst_hit,
            "best_hit": best_hit,
            "actual_recall": actual_gold / denominator if denominator else None,
            "expected_recall": expected_count / denominator if denominator else None,
            "worst_recall": worst_count / denominator if denominator else None,
            "best_recall": best_count / denominator if denominator else None,
            "cutoff_tie": boundary,
        }
    return result


def _root_code_identity(frozen: Mapping[str, Any]) -> dict[str, Any]:
    identity = frozen.get("code_identity")
    if not isinstance(identity, Mapping):
        raise ValueError("frozen wave has no source code identity")
    expected = {
        str(key): str(value) for key, value in identity.items() if "/" not in str(key)
    }
    current = {path.name: path for path in PRODUCT_ROOT.glob("*.py")}
    if set(expected) != set(current):
        raise ValueError(
            "current root Python source set differs from the frozen source set"
        )
    mismatches = [
        name for name, path in current.items() if _sha256_file(path) != expected[name]
    ]
    if mismatches:
        raise ValueError(
            f"root-level frozen source hashes changed: {sorted(mismatches)}"
        )
    return {
        "root_python_file_count": len(expected),
        "all_root_python_hashes_match": True,
        "hashes": dict(sorted(expected.items())),
    }


def _load_saved_shard(
    case_id: str, encoder: str, group_id: str, raw_directory: Path
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    raw_directory = raw_directory.resolve()
    if not raw_directory.is_relative_to(SAME_SITE_ROOT.resolve()):
        raise ValueError(f"raw shard escaped same-site artifact: {raw_directory}")
    certificate_path = raw_directory / "shard-complete.json"
    rows_path = raw_directory / "rows.jsonl.gz"
    summary_path = raw_directory / "summary.json"
    certificate_bytes = certificate_path.read_bytes()
    certificate = json.loads(certificate_bytes)
    hashes = certificate.get("output_sha256", {})
    rows_hash, summary_hash = _sha256_file(rows_path), _sha256_file(summary_path)
    if (
        hashes.get("rows.jsonl.gz") != rows_hash
        or hashes.get("summary.json") != summary_hash
    ):
        raise ValueError(
            f"saved row/certificate hashes disagree for {encoder}/{case_id}"
        )
    selected: dict[str, dict[str, Any]] = {}
    with gzip.open(rows_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if (
                row.get("case") == case_id
                and row.get("method") == METHOD
                and row.get("representation") == REPRESENTATION
                and row.get("mode") == MODE
                and row.get("group") == group_id
                and row.get("variant") == "original"
            ):
                field = str(row["field"])
                if field in selected:
                    raise ValueError(f"duplicate saved row for {case_id}/{field}")
                selected[field] = row
    if len(selected) != 7:
        raise ValueError(f"expected seven saved query rows for {encoder}/{case_id}")
    return selected, {
        "encoder": encoder,
        "case_id": case_id,
        "raw_source_directory": str(raw_directory.relative_to(ROOT)),
        "certificate_sha256": _sha256_bytes(certificate_bytes),
        "rows_sha256": rows_hash,
        "summary_sha256": summary_hash,
        "selected_original_rows": len(selected),
    }


def _compare_saved_rows(
    rows: Mapping[str, Mapping[str, Any]],
    ranked: Sequence[int],
    scores: Sequence[float],
    candidates: Sequence[Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    top = [
        {
            "id": str(candidates[index]["id"]),
            "score": float(scores[index]),
            "node_id": str(candidates[index]["node_id"]),
        }
        for index in ranked[:5]
    ]
    top_score = float(scores[ranked[0]]) if ranked else 0.0
    second_score = float(scores[ranked[1]]) if len(ranked) > 1 else 0.0
    top_ties = int(groups[0]["candidate_count"]) if groups else 0
    result: dict[str, Any] = {"recomputed_top5": top}
    signatures = []
    for encoder, row in rows.items():
        saved_top = [
            {
                "id": str(item["id"]),
                "score": float(item["score"]),
                "node_id": str(item["node_id"]),
            }
            for item in row["top"]
        ]
        signatures.append(
            tuple((item["id"], item["score"], item["node_id"]) for item in saved_top)
        )
        result[encoder] = {
            "saved_top5": saved_top,
            "saved_top5_matches_recomputed_full_rank": saved_top == top,
            "score_equality_certificate_matches": (
                float(row["top_score"]) == top_score
                and float(row["margin"]) == top_score - second_score
                and int(row["top_tie_count"]) == top_ties
            ),
            "candidate_universe_count_verified_from_full_score_vector": len(candidates),
            "saved_top_score": float(row["top_score"]),
            "saved_margin": float(row["margin"]),
            "saved_top_tie_count": int(row["top_tie_count"]),
        }
    result["encoder_saved_top5s_identical"] = len(set(signatures)) <= 1
    return result


def _load_and_score(
    target_plan: Mapping[str, Any], wave_complete: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    targets = target_plan.get("targets", [])
    case_ids = [str(target["case"]) for target in targets]
    if len(case_ids) != 6 or len(set(case_ids)) != 6:
        raise ValueError("target plan must contain six heldout originals")
    raw_by_key = {
        (str(entry["case"]), str(entry["model"])): Path(entry["raw_source_directory"])
        for entry in wave_complete.get("completed", [])
    }
    expected_keys = {(case_id, encoder) for case_id in case_ids for encoder in ENCODERS}
    if set(raw_by_key) != expected_keys:
        raise ValueError("wave-complete must include six heldouts for both encoders")

    first_raw = raw_by_key[(case_ids[0], ENCODERS[0])]
    frozen_bytes = (first_raw / "frozen.json").read_bytes()
    corpus_bytes = (first_raw / "corpus.json").read_bytes()
    frozen, corpus = json.loads(frozen_bytes), json.loads(corpus_bytes)
    if run_matrix.checksum(corpus.get("cases")) != frozen.get("corpus_checksum"):
        raise ValueError("frozen case corpus checksum mismatch")
    root_identity = _root_code_identity(frozen)
    if METHOD not in frozen.get("core_methods", []):
        raise ValueError(f"{METHOD} is not in the frozen scorer list")
    case_by_id = {str(case["id"]): case for case in corpus["cases"]}
    groups = {str(group["id"]): group for group in frozen["reference_groups"]}
    for target in targets:
        if str(target["case"]) not in case_by_id or str(target["group"]) not in groups:
            raise ValueError(f"target or reference group absent: {target['case']}")

    saved: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    shard_footprints: list[dict[str, Any]] = []
    for target in targets:
        case_id, group_id = str(target["case"]), str(target["group"])
        for encoder in ENCODERS:
            raw = raw_by_key[(case_id, encoder)]
            encoder_frozen = json.loads(
                (raw / "frozen.json").read_text(encoding="utf-8")
            )
            encoder_corpus = json.loads(
                (raw / "corpus.json").read_text(encoding="utf-8")
            )
            if encoder_frozen["code_identity"] != frozen["code_identity"]:
                raise ValueError(
                    f"frozen code identity differs for {encoder}/{case_id}"
                )
            if encoder_frozen["corpus_checksum"] != frozen["corpus_checksum"]:
                raise ValueError(f"frozen corpus differs for {encoder}/{case_id}")
            encoder_case = next(
                item for item in encoder_corpus["cases"] if item["id"] == case_id
            )
            if encoder_case != case_by_id[case_id]:
                raise ValueError(f"target case corpus differs for {encoder}/{case_id}")
            rows, footprint = _load_saved_shard(case_id, encoder, group_id, raw)
            saved[(case_id, encoder)] = rows
            shard_footprints.append(footprint)

    score_started_cpu, score_started_wall = time.process_time(), time.perf_counter()
    score_records: list[dict[str, Any]] = []
    state: dict[tuple[str, str], dict[str, Any]] = {}
    for target in targets:
        case_id, group_id = str(target["case"]), str(target["group"])
        case = case_by_id[case_id]
        reference_group = groups[group_id]
        root_indices = [
            index
            for index, candidate in enumerate(case["candidates"])
            if candidate["projection"] == "text"
        ]
        for field in frozen["field_order"]:
            candidate_indices = (
                root_indices
                if field == "root"
                else list(range(len(case["candidates"])))
            )
            candidates = [case["candidates"][index] for index in candidate_indices]
            references: list[Mapping[str, Any]] = []
            for seed_id in reference_group["cases"]:
                seed_case = case_by_id[str(seed_id)]
                seed_expected = set(seed_case.get("expected", {}).get(field, []))
                seed_candidate_ids = {
                    str(candidate["id"]) for candidate in seed_case["candidates"]
                }
                if seed_expected - seed_candidate_ids:
                    raise ValueError(
                        f"seed gold ID absent from source pool: {seed_id}/{field}"
                    )
                references.extend(
                    candidate
                    for candidate in seed_case["candidates"]
                    if candidate["id"] in seed_expected
                )
            query = {"field": field, "description": frozen["queries"][field]}
            scores = methods.score_candidates(
                METHOD, query, candidates, references, REPRESENTATION, None
            )
            ranked, score_groups = build_score_groups(scores, candidates)
            zero_score_ids = sorted(
                str(candidates[index]["id"])
                for index, score in enumerate(scores)
                if float(score) == 0.0
            )
            saved_comparison = _compare_saved_rows(
                {encoder: saved[(case_id, encoder)][field] for encoder in ENCODERS},
                ranked,
                scores,
                candidates,
                score_groups,
            )
            if not saved_comparison["encoder_saved_top5s_identical"]:
                raise ValueError(f"saved encoders rank differently: {case_id}/{field}")
            for encoder in ENCODERS:
                if not saved_comparison[encoder][
                    "saved_top5_matches_recomputed_full_rank"
                ]:
                    raise ValueError(
                        "saved top-5 differs from recomputed ranking: "
                        f"{case_id}/{field}/{encoder}"
                    )
                if not saved_comparison[encoder]["score_equality_certificate_matches"]:
                    raise ValueError(
                        "saved top score/margin/tie count differs: "
                        f"{case_id}/{field}/{encoder}"
                    )
            record = {
                "case_id": case_id,
                "family": target["family"],
                "reference_group": group_id,
                "field": field,
                "candidate_index_space": "text-only root subset"
                if field == "root"
                else "full field candidate list",
                "candidate_count": len(candidates),
                "positive_score_candidate_count": len(ranked),
                "zero_score_candidate_count": len(zero_score_ids),
                "zero_score_candidate_ids": zero_score_ids,
                "global_candidate_indices": candidate_indices,
                "candidate_ids_sha256": _canonical_hash(
                    [str(c["id"]) for c in candidates]
                ),
                "score_vector_sha256": _canonical_hash(
                    [float(score) for score in scores]
                ),
                "score_group_count": len(score_groups),
                "tied_score_group_count": sum(
                    group["candidate_count"] > 1 for group in score_groups
                ),
                "rank1_tie_count": score_groups[0]["candidate_count"]
                if score_groups
                else 0,
                "deterministic_top5": saved_comparison["recomputed_top5"],
                "full_score_groups": score_groups,
                "saved_rows": saved_comparison,
            }
            score_records.append(record)
            state[(case_id, field)] = {
                "scores": scores,
                "ranked": ranked,
                "groups": score_groups,
                "candidates": candidates,
                "saved_rows": {
                    encoder: saved[(case_id, encoder)][field] for encoder in ENCODERS
                },
            }
    score_cpu = time.process_time() - score_started_cpu
    score_wall = time.perf_counter() - score_started_wall
    if len(score_records) != 6 * len(frozen["field_order"]):
        raise ValueError("did not recompute all seven fields for all six heldouts")
    meta = {
        "frozen": frozen,
        "case_by_id": case_by_id,
        "root_identity": root_identity,
        "shard_footprints": shard_footprints,
        "score_cpu_seconds": score_cpu,
        "score_wall_seconds": score_wall,
        "frozen_sha256": _sha256_bytes(frozen_bytes),
        "corpus_sha256": _sha256_bytes(corpus_bytes),
    }
    return score_records, state, meta


def _resume_from_score_groups(
    score_document: Mapping[str, Any],
    target_plan: Mapping[str, Any],
    wave_complete: Mapping[str, Any],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    """Validate a persisted unlabelled score partition without rescoring."""
    targets = target_plan.get("targets", [])
    case_ids = [str(target["case"]) for target in targets]
    raw_by_key = {
        (str(entry["case"]), str(entry["model"])): Path(entry["raw_source_directory"])
        for entry in wave_complete.get("completed", [])
    }
    primary_raw = raw_by_key[(case_ids[0], ENCODERS[0])]
    frozen_bytes = (primary_raw / "frozen.json").read_bytes()
    corpus_bytes = (primary_raw / "corpus.json").read_bytes()
    frozen, corpus = json.loads(frozen_bytes), json.loads(corpus_bytes)
    if run_matrix.checksum(corpus.get("cases")) != frozen.get("corpus_checksum"):
        raise ValueError("resumed score source corpus checksum mismatch")
    root_identity = _root_code_identity(frozen)
    if score_document.get("root_code_identity") != root_identity:
        raise ValueError("persisted score groups use a different root code identity")
    if score_document.get("target_gold_read") is not False:
        raise ValueError("persisted score groups do not certify gold-blind scoring")
    if score_document.get("target_cases") != case_ids:
        raise ValueError("persisted score groups target list differs from the plan")
    if score_document.get("method") != METHOD:
        raise ValueError("persisted score groups use a different method")

    case_by_id = {str(case["id"]): case for case in corpus["cases"]}
    saved_rows: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    shard_footprints = []
    for target in targets:
        case_id, group_id = str(target["case"]), str(target["group"])
        for encoder in ENCODERS:
            raw = raw_by_key[(case_id, encoder)]
            rows, footprint = _load_saved_shard(case_id, encoder, group_id, raw)
            saved_rows[(case_id, encoder)] = rows
            shard_footprints.append(footprint)

    state: dict[tuple[str, str], dict[str, Any]] = {}
    target_by_id = {str(target["case"]): target for target in targets}
    for record in score_document.get("records", []):
        case_id, field = str(record["case_id"]), str(record["field"])
        target = target_by_id.get(case_id)
        if target is None:
            raise ValueError(
                f"persisted score record is outside the target plan: {case_id}"
            )
        case = case_by_id[case_id]
        candidates = (
            [
                candidate
                for candidate in case["candidates"]
                if candidate["projection"] == "text"
            ]
            if field == "root"
            else case["candidates"]
        )
        candidate_ids = [str(candidate["id"]) for candidate in candidates]
        if int(record["candidate_count"]) != len(candidates):
            raise ValueError(f"score group candidate count changed: {case_id}/{field}")
        expected_indices = (
            [
                index
                for index, candidate in enumerate(case["candidates"])
                if candidate["projection"] == "text"
            ]
            if field == "root"
            else list(range(len(case["candidates"])))
        )
        if record.get("global_candidate_indices") != expected_indices:
            raise ValueError(
                f"score group candidate index space changed: {case_id}/{field}"
            )
        if record["candidate_ids_sha256"] != _canonical_hash(candidate_ids):
            raise ValueError(f"score group candidate index changed: {case_id}/{field}")
        zero_ids = set(
            str(candidate_id) for candidate_id in record["zero_score_candidate_ids"]
        )
        score_by_id: dict[str, float] = {}
        group_list = record["full_score_groups"]
        for group in group_list:
            score = float(group["score"])
            if score <= 0.0:
                raise ValueError(
                    "persisted retrievable tie group contains a zero score"
                )
            for candidate_id in group["candidate_ids"]:
                candidate_id = str(candidate_id)
                if candidate_id in score_by_id:
                    raise ValueError(
                        f"candidate occurs in two saved score groups: {candidate_id}"
                    )
                score_by_id[candidate_id] = score
        if set(score_by_id) & zero_ids or set(score_by_id) | zero_ids != set(
            candidate_ids
        ):
            raise ValueError(
                f"positive/zero groups do not partition candidates: {case_id}/{field}"
            )
        scores = [score_by_id.get(candidate_id, 0.0) for candidate_id in candidate_ids]
        if (
            _canonical_hash([float(score) for score in scores])
            != record["score_vector_sha256"]
        ):
            raise ValueError(
                f"persisted score vector hash is inconsistent: {case_id}/{field}"
            )
        ranked, rebuilt_groups = build_score_groups(scores, candidates)
        if rebuilt_groups != group_list:
            raise ValueError(
                "persisted exact score groups do not match reconstructed vector: "
                f"{case_id}/{field}"
            )
        if int(record["positive_score_candidate_count"]) != len(ranked):
            raise ValueError(f"positive score count is inconsistent: {case_id}/{field}")
        if int(record["zero_score_candidate_count"]) != len(zero_ids):
            raise ValueError(f"zero score count is inconsistent: {case_id}/{field}")
        comparison = _compare_saved_rows(
            {encoder: saved_rows[(case_id, encoder)][field] for encoder in ENCODERS},
            ranked,
            scores,
            candidates,
            rebuilt_groups,
        )
        if comparison != record["saved_rows"]:
            raise ValueError(
                f"persisted score/save-row comparison differs: {case_id}/{field}"
            )
        if comparison["recomputed_top5"] != record.get("deterministic_top5"):
            raise ValueError(f"saved deterministic top-5 differs: {case_id}/{field}")
        state[(case_id, field)] = {
            "scores": scores,
            "ranked": ranked,
            "groups": rebuilt_groups,
            "candidates": candidates,
            "saved_rows": {
                encoder: saved_rows[(case_id, encoder)][field] for encoder in ENCODERS
            },
        }
    expected_records = len(case_ids) * len(frozen["field_order"])
    if len(state) != expected_records:
        raise ValueError(
            "persisted score groups contain "
            f"{len(state)} rows; expected {expected_records}"
        )
    return state, {
        "frozen": frozen,
        "case_by_id": case_by_id,
        "root_identity": root_identity,
        "shard_footprints": shard_footprints,
        "frozen_sha256": _sha256_bytes(frozen_bytes),
        "corpus_sha256": _sha256_bytes(corpus_bytes),
        "score_reused_from_existing_artifact": True,
    }


def _verify_qualified_witnesses(
    case_by_id: Mapping[str, Mapping[str, Any]], case_ids: Sequence[str]
) -> tuple[dict[tuple[str, str], set[str]], dict[str, Any]]:
    annotation_bytes = QUALIFIED_MAP.read_bytes()
    annotation = json.loads(annotation_bytes)
    input_paths = {
        "corpus_sha256": FRESH_ROOT / "corpus-v1.json",
        "labels_sha256": FRESH_ROOT / "labels.json",
        "manifest_sha256": FRESH_ROOT / "manifest.json",
    }
    current_hashes = {key: _sha256_file(path) for key, path in input_paths.items()}
    for key, digest in current_hashes.items():
        if annotation.get("input_provenance", {}).get(key) != digest:
            raise ValueError(f"qualified witness input hash mismatch: {key}")
    manifest = json.loads(input_paths["manifest_sha256"].read_text(encoding="utf-8"))
    page_by_id = {str(page["id"]): page for page in manifest["pages"]}
    qualified: dict[tuple[str, str], set[str]] = defaultdict(set)
    verified_pages: set[str] = set()
    verified_entries = 0
    for case_id in case_ids:
        case = case_by_id[case_id]
        case_annotation = annotation.get("cases", {}).get(case_id)
        if case_annotation is None:
            raise ValueError(f"qualified witness case missing: {case_id}")
        source_id = str(case.get("source_id", case_id))
        page = page_by_id.get(source_id)
        if page is None:
            raise ValueError(f"qualified source manifest page missing: {source_id}")
        source_path = FRESH_ROOT / str(page["file"])
        source_digest = _sha256_file(source_path)
        if (
            source_digest != page["sha256"]
            or source_digest != case.get("provenance", {}).get("source_html_sha256")
            or source_digest != case_annotation.get("source_sha256")
        ):
            raise ValueError(f"qualified source HTML hash mismatch: {case_id}")
        candidate_by_id = {
            str(candidate["id"]): candidate for candidate in case["candidates"]
        }
        owner = str(case["owning_root_id"])
        for field, field_record in case_annotation.get("fields", {}).items():
            for entry in field_record.get("qualified_alternatives", []):
                if entry.get("decision") != "qualified" or not entry.get(
                    "include_in_qualified_alternative_set"
                ):
                    raise ValueError(f"nonqualified witness in set: {case_id}/{field}")
                candidate_id = str(entry["candidate_id"])
                candidate = candidate_by_id.get(candidate_id)
                if candidate is None or (
                    str(candidate["node_id"]) != str(entry["candidate_node_id"])
                    or candidate["projection"] != entry["projection"]
                    or candidate.get("text", "") != entry["candidate_exact_value"]
                    or entry.get("source_sha256") != source_digest
                ):
                    raise ValueError(
                        f"qualified candidate coordinate changed: {candidate_id}"
                    )
                if str(candidate["node_id"]) != owner and owner not in {
                    str(ancestor) for ancestor in candidate.get("ancestors", [])
                }:
                    raise ValueError(
                        f"qualified candidate outside owner: {candidate_id}"
                    )
                qualified[(case_id, str(field))].add(candidate_id)
                verified_entries += 1
        verified_pages.add(case_id)
    return dict(qualified), {
        "status": "verified",
        "verified_page_count": len(verified_pages),
        "qualified_candidate_count": verified_entries,
        **current_hashes,
        "annotation_sha256": _sha256_bytes(annotation_bytes),
        "uncertain_candidates_included": False,
    }


def _aggregate_metrics(
    details: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    versions = (
        "canonical_target",
        "original_alias_gold",
        "qualified_witness_plus_alias",
    )
    for version in versions:
        rows = [row for row in details if row["gold_candidate_counts"][version] > 0]
        per_k = {}
        for k in CUTOFFS:
            measures = [row["tie_metrics_by_version"][version][k] for row in rows]
            count = len(measures)
            per_k[str(k)] = {
                "field_trials": count,
                "actual_hit_count": sum(int(item["actual_hit"]) for item in measures),
                "actual_hit_rate": sum(int(item["actual_hit"]) for item in measures)
                / count
                if count
                else None,
                "expected_uniform_tie_hit_count": sum(
                    float(item["expected_hit_probability"]) for item in measures
                ),
                "expected_uniform_tie_hit_rate": sum(
                    float(item["expected_hit_probability"]) for item in measures
                )
                / count
                if count
                else None,
                "worst_tie_order_hit_count": sum(
                    int(item["worst_hit"]) for item in measures
                ),
                "worst_tie_order_hit_rate": sum(
                    int(item["worst_hit"]) for item in measures
                )
                / count
                if count
                else None,
                "best_tie_order_hit_count": sum(
                    int(item["best_hit"]) for item in measures
                ),
                "best_tie_order_hit_rate": sum(
                    int(item["best_hit"]) for item in measures
                )
                / count
                if count
                else None,
                "actual_fractional_recall_mean": sum(
                    float(item["actual_recall"] or 0.0) for item in measures
                )
                / count
                if count
                else None,
                "expected_fractional_recall_mean": sum(
                    float(item["expected_recall"] or 0.0) for item in measures
                )
                / count
                if count
                else None,
                "worst_fractional_recall_mean": sum(
                    float(item["worst_recall"] or 0.0) for item in measures
                )
                / count
                if count
                else None,
                "best_fractional_recall_mean": sum(
                    float(item["best_recall"] or 0.0) for item in measures
                )
                / count
                if count
                else None,
                "rows_with_cutoff_tie": sum(
                    item["cutoff_tie"] is not None for item in measures
                ),
            }
        output[version] = {"field_trials": len(rows), "metrics": per_k}
    return output


def _evaluate_gold(
    target_records: Sequence[Mapping[str, Any]],
    case_by_id: Mapping[str, Mapping[str, Any]],
    state: Mapping[tuple[str, str], Mapping[str, Any]],
    qualified: Mapping[tuple[str, str], set[str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    details: list[dict[str, Any]] = []
    saved_hit_mismatches = []
    for target in target_records:
        case_id = str(target["case"])
        case = case_by_id[case_id]
        for field in ("root", "color", "id", "material", "name", "price", "stock"):
            if case.get("expected_status", {}).get(field) != "present_dom":
                continue
            score_state = state[(case_id, field)]
            candidates = score_state["candidates"]
            scores = score_state["scores"]
            ranked = score_state["ranked"]
            groups = score_state["groups"]
            canonical_gold = set(case.get("canonical_expected", {}).get(field, []))
            alias_gold = set(case.get("expected", {}).get(field, []))
            gold_versions = {
                "canonical_target": canonical_gold,
                "original_alias_gold": alias_gold,
                "qualified_witness_plus_alias": alias_gold
                | qualified.get((case_id, field), set()),
            }
            metrics = {
                version: tie_sensitivity(scores, candidates, gold, ranked, groups)
                for version, gold in gold_versions.items()
            }
            candidate_ids = {str(candidate["id"]) for candidate in candidates}
            all_gold_ties = {}
            for version, gold_ids in gold_versions.items():
                all_gold_ties[version] = [
                    {
                        "score_group_index": group_index,
                        "score": group["score"],
                        "rank_start": group["rank_start"],
                        "rank_end": group["rank_end"],
                        "full_group_candidate_count": group["candidate_count"],
                        "full_group_gold_count": len(
                            set(group["candidate_ids"]) & gold_ids
                        ),
                        "gold_candidate_ids": sorted(
                            set(group["candidate_ids"]) & gold_ids
                        ),
                    }
                    for group_index, group in enumerate(groups)
                    if set(group["candidate_ids"]) & gold_ids
                ]
            saved_alias_hits = {}
            for encoder, row in score_state["saved_rows"].items():
                saved_alias_hits[encoder] = row.get("hit", {})
                for k in CUTOFFS:
                    if (
                        bool(row.get("hit", {}).get(str(k), False))
                        != metrics["original_alias_gold"][k]["actual_hit"]
                    ):
                        saved_hit_mismatches.append(
                            {
                                "case_id": case_id,
                                "field": field,
                                "encoder": encoder,
                                "k": k,
                            }
                        )
            details.append(
                {
                    "case_id": case_id,
                    "family": target["family"],
                    "reference_group": target["group"],
                    "field": field,
                    "candidate_count": len(candidates),
                    "gold_candidate_counts": {
                        version: len(gold) for version, gold in gold_versions.items()
                    },
                    "gold_candidates_in_score_universe": {
                        version: len(gold & candidate_ids)
                        for version, gold in gold_versions.items()
                    },
                    "gold_candidate_ids_missing_from_score_universe": {
                        version: sorted(gold - candidate_ids)
                        for version, gold in gold_versions.items()
                    },
                    "full_score_tie_groups_containing_gold": all_gold_ties,
                    "tie_metrics_by_version": metrics,
                    "saved_alias_hit_crosscheck": saved_alias_hits,
                }
            )
    if saved_hit_mismatches:
        raise ValueError(
            "saved alias hit values mismatch recomputed rank: "
            f"{saved_hit_mismatches[:5]}"
        )
    if len(details) != 26:
        raise ValueError(
            f"expected 26 present heldout fields including root, got {len(details)}"
        )
    return details, {
        "saved_alias_hit_mismatch_count": len(saved_hit_mismatches),
        "metrics_by_gold_version": _aggregate_metrics(details),
    }


def run_audit(output_directory: Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Recompute full score groups, persist them, then evaluate target gold."""
    resolved = output_directory.resolve()
    if not resolved.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ValueError("output must stay under the declared generated directory")
    score_path, summary_path = resolved / "score-groups.json", resolved / "summary.json"
    if summary_path.exists():
        raise FileExistsError("refusing to overwrite an existing tie-audit summary")
    target_plan_bytes, wave_bytes = TARGET_PLAN.read_bytes(), WAVE_COMPLETE.read_bytes()
    target_plan, wave_complete = json.loads(target_plan_bytes), json.loads(wave_bytes)
    reused_score_groups = score_path.exists()
    if reused_score_groups:
        # Preserve and validate the complete unlabelled partition from the prior
        # attempt; do not rerun or replace the measured score artifact.
        score_bytes = score_path.read_bytes()
        score_document = json.loads(score_bytes)
        if score_document.get("format") != "same-site-structural-score-groups-v1":
            raise ValueError("existing score-group artifact has an unknown format")
        score_records = score_document.get("records", [])
        state, source_meta = _resume_from_score_groups(
            score_document, target_plan, wave_complete
        )
        score_cpu = float(score_document["score_cpu_seconds"])
        score_wall = float(score_document["score_wall_seconds"])
    else:
        score_start_cpu, score_start_wall = time.process_time(), time.perf_counter()
        score_records, state, source_meta = _load_and_score(target_plan, wave_complete)
        score_cpu = time.process_time() - score_start_cpu
        score_wall = time.perf_counter() - score_start_wall
        for record in score_records:
            if not record["saved_rows"]["encoder_saved_top5s_identical"]:
                raise ValueError(
                    "saved encoder top-5 rankings differ: "
                    f"{record['case_id']}/{record['field']}"
                )
            for encoder in ENCODERS:
                if not record["saved_rows"][encoder][
                    "saved_top5_matches_recomputed_full_rank"
                ]:
                    raise ValueError(
                        "saved top-5 differs from recomputation: "
                        f"{record['case_id']}/{record['field']}/{encoder}"
                    )
                if not record["saved_rows"][encoder][
                    "score_equality_certificate_matches"
                ]:
                    raise ValueError(
                        "saved score certificate differs: "
                        f"{record['case_id']}/{record['field']}/{encoder}"
                    )
        score_document = {
            "format": "same-site-structural-score-groups-v1",
            "target_gold_read": False,
            "method": METHOD,
            "representation": REPRESENTATION,
            "selection_mode": MODE,
            "target_cases": [str(target["case"]) for target in target_plan["targets"]],
            "fields_scored_per_case": list(source_meta["frozen"]["field_order"]),
            "rank_order": (
                "score descending; exact-score ties by candidate ID ascending"
            ),
            "tie_definition": (
                "exact float equality over the full candidate score vector"
            ),
            "score_cpu_seconds": score_cpu,
            "score_wall_seconds": score_wall,
            "root_code_identity": source_meta["root_identity"],
            "records": score_records,
        }
        resolved.mkdir(parents=True, exist_ok=True)
        score_bytes = (json.dumps(score_document, indent=2) + "\n").encode("utf-8")
        score_path.write_bytes(score_bytes)

    qualified, qualified_provenance = _verify_qualified_witnesses(
        source_meta["case_by_id"], score_document["target_cases"]
    )
    details, evaluation = _evaluate_gold(
        target_plan["targets"], source_meta["case_by_id"], state, qualified
    )
    summary = {
        "format": "same-site-structural-jaccard-tie-audit-v1",
        "claim_scope": (
            "Six originals from three toy templates; exact tie "
            "sensitivity, not a population benchmark."
        ),
        "method": METHOD,
        "representation": REPRESENTATION,
        "selection_mode": MODE,
        "target_cases": score_document["target_cases"],
        "reference_groups": {
            str(target["case"]): str(target["group"])
            for target in target_plan["targets"]
        },
        "present_field_count_including_root": len(details),
        "encoder_rows_compared": list(ENCODERS),
        "score_recomputation": {
            "vectors_recomputed": len(score_records),
            "all_seven_fields_scored_for_each_case": True,
            "score_group_file_reused_without_rescoring": reused_score_groups,
            "target_gold_read_after_score_groups_written": True,
            "cpu_seconds": score_cpu,
            "wall_seconds": score_wall,
            "models_or_embeddings_used": False,
            "full_score_group_file": score_path.name,
            "full_score_group_file_sha256": _sha256_bytes(score_bytes),
            "target_source_hashes": {
                "frozen_sha256": source_meta["frozen_sha256"],
                "corpus_sha256": source_meta["corpus_sha256"],
                "methods_py_sha256": source_meta["root_identity"]["hashes"][
                    "methods.py"
                ],
                "run_matrix_py_sha256": source_meta["root_identity"]["hashes"][
                    "run_matrix.py"
                ],
            },
        },
        "saved_row_verification": {
            "certificates_verified": len(source_meta["shard_footprints"]),
            "saved_original_rows_verified": sum(
                int(item["selected_original_rows"])
                for item in source_meta["shard_footprints"]
            ),
            "top5_order_score_margin_and_tie_count_match_recomputed": True,
            "saved_alias_hit_mismatches": evaluation["saved_alias_hit_mismatch_count"],
            "encoders_saved_top5s_identical": all(
                record["saved_rows"][ENCODERS[0]]["saved_top5"]
                == record["saved_rows"][ENCODERS[1]]["saved_top5"]
                for record in score_records
            ),
            "shards": source_meta["shard_footprints"],
        },
        "tie_policy": {
            "tie_definition": "Exact equal raw floats across the full score vector.",
            "actual_order": (
                "Score descending, candidate ID ascending, matching run_matrix.rank."
            ),
            "uniform_order": (
                "Uniform permutation only within a tie; no score perturbation"
                " or Monte Carlo."
            ),
            "expected_hit_probability": (
                "Exact hypergeometric probability for a boundary tie group."
            ),
            "worst_best": (
                "Bounds vary only the ordering of candidates within the "
                "boundary tie group."
            ),
            "full_score_groups_written": True,
        },
        "gold_versions": {
            "canonical_target": "canonical_expected coordinate IDs",
            "original_alias_gold": "existing expected candidate ID sets",
            "qualified_witness_plus_alias": (
                "original alias IDs plus separately source-hash-verified "
                "qualified witnesses"
            ),
        },
        "qualified_witness_provenance": qualified_provenance,
        "metrics_by_gold_version": evaluation["metrics_by_gold_version"],
        "per_case_field_results": details,
        "input_hashes": {
            "target_plan_sha256": _sha256_bytes(target_plan_bytes),
            "wave_complete_sha256": _sha256_bytes(wave_bytes),
            "tie_audit_py_sha256": _sha256_file(Path(__file__)),
            "test_tie_audit_py_sha256": _sha256_file(
                Path(__file__).with_name("test_tie_audit.py")
            ),
        },
        "limitations": [
            (
                "One template per site confounds host and template; these six"
                " pages are not a broad sample."
            ),
            (
                "The source is agent-annotated saved HTML, not blind human "
                "gold or a live browser DOM."
            ),
            (
                "Descendant aliases can be correlated witnesses; field trials"
                " are not independent."
            ),
            (
                "Qualified witness results are a separate, agent-reviewed "
                "metric and do not replace canonical or original alias "
                "results."
            ),
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    result = run_audit(args.output)
    print(
        json.dumps(
            {
                "case_count": len(result["target_cases"]),
                "present_field_count_including_root": result[
                    "present_field_count_including_root"
                ],
                "score_cpu_seconds": result["score_recomputation"]["cpu_seconds"],
                "score_wall_seconds": result["score_recomputation"]["wall_seconds"],
                "qualified_witness_status": result["qualified_witness_provenance"][
                    "status"
                ],
                "output": str(args.output / "summary.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
