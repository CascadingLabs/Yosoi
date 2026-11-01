"""Matched MiniLM one-versus-two-reference wave over three heldout templates.

This driver uses the frozen expanded-v1 inputs, reuses completed same-site
two-reference shards, and runs only the matching one-reference shards. Both
cohorts are aggregated independently with the existing count-aware adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import aggregate_wave
import run_wave

ROOT = Path(__file__).resolve().parents[3]
PRODUCT_ROOT = ROOT / "experiments" / "product-retrieval"
EXTENSIONS = PRODUCT_ROOT / "extensions"
SOURCE = ROOT / ".generated" / "product-retrieval-expanded-v1"
MODEL_ARTIFACT = (
    ROOT / ".generated" / "product-retrieval-expanded-input" / "minilm-v1.json"
)
SAME_SITE_ROOT = ROOT / ".generated" / "product-retrieval-same-site-v1"
SAME_SITE_TARGET_PLAN = SAME_SITE_ROOT / "target-plan.json"
SAME_SITE_WAVE = SAME_SITE_ROOT / "same-site-view" / "wave-complete.json"
OUTPUT_ROOT = ROOT / ".generated" / "product-retrieval-reference-count-v1"
SPLIT = "fresh_cross_site"

COUNT_FIELDS = (
    "trials",
    "complete_score_trials",
    "incomplete_score_trials",
    "evaluable",
    "present",
    "absent",
    "correct",
    "owner_correct",
    "false_positive",
    "abstained",
    "hit1",
    "hit3",
    "hit5",
    "canonical1",
    "canonical_evaluable",
    "operational_present",
    "operational_owner_correct",
    "operational_hit1",
    "operational_hit3",
    "operational_hit5",
    "latency_all_count",
    "latency_quality_count",
)
RATE_FIELDS = (
    "accuracy",
    "canonical_top1_accuracy",
    "owner_accuracy",
    "absent_false_positive_rate",
    "provided_candidate_precision",
    "provided_candidate_coverage",
    "recall_at_1",
    "recall_at_3",
    "recall_at_5",
    "operational_complete_recall_at_1",
    "operational_complete_recall_at_3",
    "operational_complete_recall_at_5",
)
ROW_KEY_FIELDS = ("encoder", "method", "representation", "mode", "condition", "field")


def sha256_file(path: Path) -> str:
    """Hash a retained input or artifact file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_checksum(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def select_matched_targets(
    target_plan: Mapping[str, Any], frozen: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Choose the first declared heldout per family and verify /1 ⊂ /2."""
    groups = {str(group["id"]): group for group in frozen.get("reference_groups", [])}
    selected: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for target in target_plan.get("targets", []):
        family = str(target["family"])
        if family in seen_families:
            continue
        case_id = str(target["case"])
        one_id, two_id = f"{family}/1", f"{family}/2"
        if str(target.get("group")) != two_id:
            raise ValueError(
                f"same-site target is not declared in the /2 group: {case_id}"
            )
        one_group, two_group = groups.get(one_id), groups.get(two_id)
        if one_group is None or two_group is None:
            raise ValueError(f"frozen reference groups are missing for {family}")
        one_cases = list(one_group.get("cases", []))
        two_cases = list(two_group.get("cases", []))
        if len(one_cases) != 1 or len(two_cases) != 2:
            raise ValueError(f"expected one and two reference cases for {family}")
        if not set(one_cases) < set(two_cases):
            raise ValueError(
                f"/1 references are not a strict subset of /2 for {family}"
            )
        if case_id in one_cases or case_id in two_cases:
            raise ValueError(
                f"heldout target must be disjoint from both reference sets: {case_id}"
            )
        selected.append(
            {
                "case": case_id,
                "family": family,
                "one_reference_group": one_id,
                "one_reference_cases": one_cases,
                "two_reference_group": two_id,
                "two_reference_cases": two_cases,
                "selection_rule": (
                    "first target in the existing same-site target-plan order "
                    "for this family"
                ),
            }
        )
        seen_families.add(family)
    if len(selected) != 3:
        raise ValueError(f"expected three fresh templates, selected {len(selected)}")
    return selected


def _aggregate_row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(row[field]) for field in ROW_KEY_FIELDS)


def match_aggregate_rows(
    one_reference: Mapping[str, Any], two_references: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Join aggregate rows without merging cohort counts, statuses, or timings."""
    one_rows = {
        _aggregate_row_key(row): row for row in one_reference.get("metrics", [])
    }
    two_rows = {
        _aggregate_row_key(row): row for row in two_references.get("metrics", [])
    }
    if set(one_rows) != set(two_rows):
        missing_two = sorted(set(one_rows) - set(two_rows))
        missing_one = sorted(set(two_rows) - set(one_rows))
        raise ValueError(
            f"one/two aggregate row keys differ (missing_two={missing_two[:3]}, "
            f"missing_one={missing_one[:3]})"
        )
    matched = []
    for key in sorted(one_rows):
        one, two = one_rows[key], two_rows[key]
        count_deltas = {
            field: int(two.get(field, 0)) - int(one.get(field, 0))
            for field in COUNT_FIELDS
            if field in one or field in two
        }
        rate_deltas = {
            field: (
                None
                if one.get(field) is None or two.get(field) is None
                else float(two[field]) - float(one[field])
            )
            for field in RATE_FIELDS
            if field in one or field in two
        }
        matched.append(
            {
                "key": dict(zip(ROW_KEY_FIELDS, key, strict=True)),
                "one_reference": dict(one),
                "two_references": dict(two),
                "count_delta_two_minus_one": count_deltas,
                "rate_delta_two_minus_one": rate_deltas,
                "score_status_counts_by_cohort": {
                    "one_reference": dict(one.get("score_status_counts", {})),
                    "two_references": dict(two.get("score_status_counts", {})),
                },
                "page_median_scoring_ms_range_by_cohort": {
                    "one_reference": {
                        "min": one.get("page_median_scoring_ms_min"),
                        "max": one.get("page_median_scoring_ms_max"),
                    },
                    "two_references": {
                        "min": two.get("page_median_scoring_ms_min"),
                        "max": two.get("page_median_scoring_ms_max"),
                    },
                },
            }
        )
    return matched


def _verify_frozen_source() -> dict[str, Any]:
    frozen_path = SOURCE / "frozen.json"
    corpus_path = SOURCE / "corpus.json"
    preparation_path = SOURCE / "preparation.json"
    frozen_bytes = frozen_path.read_bytes()
    frozen = json.loads(frozen_bytes)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if _canonical_checksum(corpus.get("cases")) != frozen.get("corpus_checksum"):
        raise ValueError("expanded-v1 case list does not match its frozen checksum")
    if not (SOURCE / "implementation").is_dir():
        raise ValueError("expanded-v1 implementation snapshot is missing")
    mismatches = []
    for relative, expected_hash in frozen.get("code_identity", {}).items():
        path = SOURCE / "implementation" / relative
        if not path.is_file() or sha256_file(path) != expected_hash:
            mismatches.append(relative)
    if mismatches:
        raise ValueError(f"frozen expanded-v1 implementation changed: {mismatches[:5]}")
    if len(corpus.get("cases", [])) != 72:
        raise ValueError("expanded-v1 corpus case population changed")
    model_hash = run_wave.ready_artifact(MODEL_ARTIFACT)
    return {
        "source_dir": str(SOURCE.relative_to(ROOT)),
        "frozen_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
        "corpus_sha256": sha256_file(corpus_path),
        "preparation_sha256": sha256_file(preparation_path),
        "frozen_corpus_checksum": frozen.get("corpus_checksum"),
        "frozen_implementation_hashes": dict(frozen.get("code_identity", {})),
        "model_artifact": str(MODEL_ARTIFACT.relative_to(ROOT)),
        "model_artifact_sha256": model_hash,
        "embedding_inference_performed": False,
        "frozen": frozen,
        "corpus": corpus,
    }


def _verify_two_reference_reuse(
    selected: Sequence[Mapping[str, Any]],
    frozen: Mapping[str, Any],
    model_hash: str,
) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    wave = json.loads(SAME_SITE_WAVE.read_text(encoding="utf-8"))
    available = {
        (str(item["case"]), str(item["model"])): item
        for item in wave.get("completed", [])
    }
    config_hash = run_wave.digest(SOURCE / "frozen.json")
    shards: dict[str, Path] = {}
    footprints = []
    for target in selected:
        case_id = str(target["case"])
        entry = available.get((case_id, "minilm"))
        if entry is None:
            raise ValueError(f"same-site /2 MiniLM shard is missing for {case_id}")
        raw_directory = Path(entry["raw_source_directory"]).resolve()
        expected_directory = (
            SAME_SITE_ROOT / "cases" / case_id / "minilm" / case_id
        ).resolve()
        if raw_directory != expected_directory:
            raise ValueError(f"same-site raw shard path changed for {case_id}")
        filters = {
            "group": str(target["two_reference_group"]),
            "case": case_id,
            "split": SPLIT,
        }
        if not run_wave.verified_shard(raw_directory, config_hash, model_hash, filters):
            raise ValueError(
                f"same-site /2 shard failed certificate verification for {case_id}"
            )
        certificate = json.loads((raw_directory / "shard-complete.json").read_text())
        shards[case_id] = raw_directory
        footprints.append(
            {
                "case": case_id,
                "model": "minilm",
                "reference_group": filters["group"],
                "raw_source_directory": str(raw_directory.relative_to(ROOT)),
                "configuration_sha256": certificate["configuration_sha256"],
                "semantic_sha256": certificate["semantic_sha256"],
                "rows": certificate["rows"],
                "shard_certificate_sha256": sha256_file(
                    raw_directory / "shard-complete.json"
                ),
                "rows_sha256": certificate["output_sha256"]["rows.jsonl.gz"],
                "reused": True,
            }
        )
    return shards, footprints


def _write_wave_complete(
    directory: Path, completed: Sequence[Mapping[str, Any]]
) -> None:
    (directory / "wave-complete.json").write_text(
        json.dumps({"completed": list(completed)}, indent=2) + "\n", encoding="utf-8"
    )


def _link_two_reference_shards(
    wave_directory: Path,
    selected: Sequence[Mapping[str, Any]],
    reused_shards: Mapping[str, Path],
) -> list[dict[str, Any]]:
    completed = []
    for target in selected:
        case_id = str(target["case"])
        raw = reused_shards[case_id]
        link_path = wave_directory / "minilm" / case_id
        link_path.parent.mkdir(parents=True, exist_ok=True)
        if link_path.exists() or link_path.is_symlink():
            raise FileExistsError(f"two-reference output already exists: {link_path}")
        os.symlink(raw, link_path, target_is_directory=True)
        certificate = json.loads((raw / "shard-complete.json").read_text())
        completed.append(
            {
                "model": "minilm",
                "case": case_id,
                "rows": certificate["rows"],
                "reused_complete_shard": True,
            }
        )
    _write_wave_complete(wave_directory, completed)
    return completed


def _aggregate_condition(wave_dir: Path, output_dir: Path) -> dict[str, Any]:
    aggregate_wave.aggregate(wave_dir, output_dir)
    return json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))


def execute_reference_count_wave(
    output_directory: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    """Run exactly three new /1 MiniLM shards and aggregate matched /1,/2."""
    output_directory = output_directory.resolve()
    if not output_directory.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ValueError("output directory must stay under the declared generated path")
    if output_directory.exists():
        raise FileExistsError(
            "refusing to overwrite or resume partial reference-count output"
        )
    frozen_meta = _verify_frozen_source()
    same_site_plan_bytes = SAME_SITE_TARGET_PLAN.read_bytes()
    same_site_plan = json.loads(same_site_plan_bytes)
    selected = select_matched_targets(same_site_plan, frozen_meta["frozen"])
    reused_shards, reused_footprints = _verify_two_reference_reuse(
        selected, frozen_meta["frozen"], frozen_meta["model_artifact_sha256"]
    )
    driver_provenance = {
        **{
            key: value
            for key, value in frozen_meta.items()
            if key not in {"frozen", "corpus"}
        },
        "same_site_target_plan_sha256": hashlib.sha256(
            same_site_plan_bytes
        ).hexdigest(),
        "same_site_wave_complete_sha256": sha256_file(SAME_SITE_WAVE),
        "run_wave_py_sha256": sha256_file(EXTENSIONS / "run_wave.py"),
        "aggregate_wave_py_sha256": sha256_file(EXTENSIONS / "aggregate_wave.py"),
        "driver_py_sha256": sha256_file(Path(__file__)),
        "test_py_sha256": sha256_file(
            Path(__file__).with_name("test_reference_count_wave.py")
        ),
        "one_reference_new_shard_count": 3,
        "two_reference_reused_shard_count": 3,
        "models": ["minilm"],
        "target_selection_rule": (
            "first existing same-site heldout in target-plan order per family; "
            "no target gold used"
        ),
    }
    output_directory.mkdir(parents=True, exist_ok=False)
    (output_directory / "run-plan.json").write_text(
        json.dumps(
            {
                "format": "reference-count-wave-plan-v1",
                "references": [
                    {
                        **target,
                        "two_reference_reuse": reused_footprints[index],
                    }
                    for index, target in enumerate(selected)
                ],
                "producer_provenance": driver_provenance,
                "execution": {
                    "one_reference_shards_to_run": [
                        target["case"] for target in selected
                    ],
                    "two_reference_shards_to_reuse": [
                        target["case"] for target in selected
                    ],
                    "worker_concurrency": 1,
                    "embedding_inference": False,
                    "network_access": False,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    one_wave = output_directory / "one-reference"
    one_wave.mkdir()
    one_completed = []
    models = {"minilm": MODEL_ARTIFACT}
    for target in selected:
        case_id = str(target["case"])
        run_wave.run(
            SOURCE,
            models,
            one_wave,
            split=SPLIT,
            group=str(target["one_reference_group"]),
            case=case_id,
        )
        shard = one_wave / "minilm" / case_id
        filters = {
            "group": str(target["one_reference_group"]),
            "case": case_id,
            "split": SPLIT,
        }
        config_hash = run_wave.digest(SOURCE / "frozen.json")
        if not run_wave.verified_shard(
            shard, config_hash, frozen_meta["model_artifact_sha256"], filters
        ):
            raise ValueError(f"new /1 shard did not verify: {case_id}")
        certificate = json.loads((shard / "shard-complete.json").read_text())
        one_completed.append(
            {
                "model": "minilm",
                "case": case_id,
                "rows": certificate["rows"],
                "directory": str(shard),
                "newly_run": True,
            }
        )
        (one_wave / "progress.json").write_text(
            json.dumps({"completed": one_completed}, indent=2) + "\n",
            encoding="utf-8",
        )
    _write_wave_complete(one_wave, one_completed)

    two_wave = output_directory / "two-references"
    two_wave.mkdir()
    two_completed = _link_two_reference_shards(two_wave, selected, reused_shards)

    one_aggregate_dir = output_directory / "one-reference-aggregate"
    two_aggregate_dir = output_directory / "two-reference-aggregate"
    one_summary = _aggregate_condition(one_wave, one_aggregate_dir)
    two_summary = _aggregate_condition(two_wave, two_aggregate_dir)
    matched = match_aggregate_rows(one_summary, two_summary)
    comparison = {
        "format": "matched-reference-count-comparison-v1",
        "target_cases": [target["case"] for target in selected],
        "same_target_population": True,
        "one_reference": {
            "group_by_family": {
                target["family"]: target["one_reference_group"] for target in selected
            },
            "completed": one_completed,
            "aggregate_directory": str(one_aggregate_dir.relative_to(ROOT)),
            "aggregate_population": {
                "raw_rows": one_summary["raw_rows"],
                "score_failure_count": one_summary["score_failure_count"],
                "metric_group_count": len(one_summary["metrics"]),
                "source_case_count": len(one_summary["sources"]),
            },
        },
        "two_references": {
            "group_by_family": {
                target["family"]: target["two_reference_group"] for target in selected
            },
            "completed": two_completed,
            "aggregate_directory": str(two_aggregate_dir.relative_to(ROOT)),
            "aggregate_population": {
                "raw_rows": two_summary["raw_rows"],
                "score_failure_count": two_summary["score_failure_count"],
                "metric_group_count": len(two_summary["metrics"]),
                "source_case_count": len(two_summary["sources"]),
            },
        },
        "metric_key_count": len(matched),
        "matched_metric_rows": matched,
        "interpretation": [
            (
                "The same three target pages are evaluated under nested "
                "one- and two-reference groups."
            ),
            (
                "Each cohort keeps its own counts, score-status distribution, "
                "population, and page-median timing range."
            ),
            (
                "Aggregate rates are recomputed from disjoint page counts by "
                "aggregate_wave; one/two rates are not pooled or treated as "
                "independent model runs."
            ),
            (
                "No gold labels were used to choose targets; targets are the "
                "first existing heldout per template in same-site plan order."
            ),
            (
                "MiniLM embeddings are reused from the frozen input artifact; "
                "no embedding inference is performed."
            ),
        ],
        "producer_provenance": driver_provenance,
    }
    (output_directory / "matched-comparison.json").write_text(
        json.dumps(comparison, indent=2) + "\n", encoding="utf-8"
    )
    return comparison


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    result = execute_reference_count_wave(args.output)
    print(
        json.dumps(
            {
                "target_cases": result["target_cases"],
                "new_one_reference_shards": len(result["one_reference"]["completed"]),
                "reused_two_reference_shards": len(
                    result["two_references"]["completed"]
                ),
                "matched_metric_rows": result["metric_key_count"],
                "output": str(args.output / "matched-comparison.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
