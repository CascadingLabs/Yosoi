"""Re-evaluate cached reranker pools with seed-supported projection policies."""

import argparse
import gzip
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from projection import POLICIES, apply_projection_policy, reference_projection_hints
from run_matrix import canonical


def _quality(result, case, field):
    expected = set(case["expected"].get(field, []))
    exact = set(case["canonical_expected"].get(field, []))
    rows = result["results"]
    ids = [row["candidate_id"] for row in rows]
    gold_nodes = {c["node_id"] for c in case["candidates"] if c["id"] in exact}
    nodes = [node["node_id"] for node in result["node_ranking"]]
    first = rows[0]["candidate"] if rows else None
    return {
        "present": bool(expected),
        "correct": bool(expected & set(ids[:1])) if expected else not ids,
        "canonical_correct": bool(exact & set(ids[:1])) if expected else not ids,
        "hit": {str(k): bool(expected & set(ids[:k])) for k in (1, 3, 5)},
        "node_hit": {str(k): bool(gold_nodes & set(nodes[:k])) for k in (1, 3, 5)},
        "false_positive": not expected and bool(ids),
        "owner_correct": bool(
            first
            and (
                first["node_id"] == case["owning_root_id"]
                or case["owning_root_id"] in first["ancestors"]
            )
        ),
        "abstained": not ids,
        "top_ids": ids,
        "top_node_ids": nodes,
    }


def run(baseline, rerank_directory, output):
    if output.exists():
        raise ValueError("projection campaign requires a new output")
    plan_path = rerank_directory / "plan.json"
    plan = json.loads(plan_path.read_text())
    data = json.loads((baseline / "corpus.json").read_text())
    frozen = json.loads((baseline / "frozen.json").read_text())
    cases = {case["id"]: case for case in data["cases"]}
    groups = {group["id"]: group["cases"] for group in frozen["reference_groups"]}
    if plan["dataset"]["corpus_checksum"] != frozen["corpus_checksum"]:
        raise ValueError("reranker plan uses different evidence")
    output.mkdir(parents=True)
    source_files = [
        plan_path,
        baseline / "corpus.json",
        baseline / "frozen.json",
        *sorted(rerank_directory.glob("*-scores.json")),
    ]
    manifest = {
        "kind": "seed-projection-campaign-v1",
        "input_sha256": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files
        },
        "code_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__), Path(__file__).with_name("projection.py"))
        },
        "policies": list(POLICIES),
        "score_transform": (
            "per-pool subtract minimum logit then add one, "
            "solely to preserve ordering for a positive-score "
            "policy API; no probabilities"
        ),
        "extra_projection_reads": (
            "node localization may materialize a same-node "
            "projection outside the original model pool; not "
            "original-pool recall"
        ),
        "network_calls": 0,
        "model_inference_calls": 0,
    }
    (output / "frozen.json").write_text(json.dumps(manifest, indent=2))
    totals = defaultdict(lambda: defaultdict(int))
    complete = defaultdict(dict)
    row_count = 0
    started = time.perf_counter_ns()
    with gzip.open(output / "rows.jsonl.gz", "wt") as stream:
        for score_path in sorted(rerank_directory.glob("*-scores.json")):
            model = json.loads(score_path.read_text())
            raw_scores = model["scores"]
            roots = {}
            for job in plan["jobs"]:
                case = cases[job["case_id"]]
                source_by_id = {c["id"]: c for c in case["candidates"]}
                pool = [
                    source_by_id[item["candidate_id"]] for item in job["pool_items"]
                ]
                logits = [raw_scores[item["pair_sha256"]] for item in job["pool_items"]]
                if any(not math.isfinite(value) for value in logits):
                    raise ValueError("non-finite reranker score")
                offset = min(logits, default=0.0)
                shifted = [value - offset + 1 for value in logits]
                seeds = [cases[identity] for identity in groups[job["seed_group"]]]
                hints = reference_projection_hints(
                    [
                        c
                        for seed in seeds
                        for c in seed["candidates"]
                        if c["id"] in seed["expected"].get(job["field"], [])
                    ],
                    job["field"],
                )
                root_key = (
                    case["id"],
                    job["seed_group"],
                    job["pool_builder"],
                    job["pool_budget"],
                )
                source_is_reference = case["id"] in groups[job["seed_group"]]
                for policy in POLICIES:
                    for mode in (
                        ["global"]
                        if job["field"] == "root"
                        else ["global", "predicted_root"]
                    ):
                        selected_pool, selected_scores = pool, shifted
                        if mode == "predicted_root":
                            root = roots.get((root_key, policy))
                            eligible = [
                                i
                                for i, candidate in enumerate(pool)
                                if root is not None
                                and (
                                    candidate["node_id"] == root
                                    or root in candidate["ancestors"]
                                )
                            ]
                            selected_pool = [pool[i] for i in eligible]
                            selected_scores = [shifted[i] for i in eligible]
                        result = apply_projection_policy(
                            policy,
                            selected_scores,
                            selected_pool,
                            hints,
                            source_candidates=case["candidates"],
                            top_k=5,
                            top_nodes=5,
                        )
                        if job["field"] == "root":
                            roots[(root_key, policy)] = (
                                result["results"][0]["node_id"]
                                if result["results"]
                                else None
                            )
                        quality = _quality(result, case, job["field"])
                        row = {
                            "model": model["model"],
                            "case": case["id"],
                            "split": case["split"],
                            "variant": case["variant"],
                            "field": job["field"],
                            "group": job["seed_group"],
                            "pool_builder": job["pool_builder"],
                            "pool_budget": job["pool_budget"],
                            "policy": policy,
                            "mode": mode,
                            "status": result["status"],
                            "projection_scores_are_probabilities": result[
                                "projection_scores_are_probabilities"
                            ],
                            "source_projection_reads": result[
                                "source_projection_reads"
                            ],
                            "extra_source_projection_reads": result[
                                "extra_source_projection_reads"
                            ],
                            "absent_projection_count": result[
                                "absent_projection_count"
                            ],
                            "reference_self": source_is_reference,
                            **quality,
                        }
                        stream.write(canonical(row).decode() + "\n")
                        row_count += 1
                        strata = ["all_nonself"] if not source_is_reference else []
                        if case["split"] == "controlled":
                            strata.append("controlled")
                        for stratum in strata:
                            key = (
                                model["model"],
                                job["pool_builder"],
                                job["pool_budget"],
                                policy,
                                mode,
                                stratum,
                            )
                            for field_key in ("all", job["field"]):
                                counter = totals[(*key, field_key)]
                                counter["trials"] += 1
                                counter["present"] += quality["present"]
                                counter["absent"] += not quality["present"]
                                counter["correct"] += quality["correct"]
                                counter["canonical_correct"] += quality[
                                    "canonical_correct"
                                ]
                                counter["false_positive"] += quality["false_positive"]
                                counter["owner_correct"] += (
                                    quality["present"] and quality["owner_correct"]
                                )
                                counter["projection_reads"] += result[
                                    "source_projection_reads"
                                ]
                                counter["extra_projection_reads"] += result[
                                    "extra_source_projection_reads"
                                ]
                                for k in (1, 3, 5):
                                    counter[f"hit{k}"] += (
                                        quality["present"] and quality["hit"][str(k)]
                                    )
                                    counter[f"node_hit{k}"] += (
                                        quality["present"]
                                        and quality["node_hit"][str(k)]
                                    )
                            record_modes = (
                                ("global", "predicted_root")
                                if job["field"] == "root"
                                else (mode,)
                            )
                            for record_mode in record_modes:
                                complete[
                                    (
                                        case["id"],
                                        job["seed_group"],
                                        *key[:4],
                                        record_mode,
                                        stratum,
                                    )
                                ][job["field"]] = quality
            print(json.dumps({"model": model["model"], "rows": row_count}), flush=True)
    metrics = []
    for key, counter in sorted(totals.items()):
        values = dict(counter)
        values["accuracy"] = counter["correct"] / counter["trials"]
        values["canonical_accuracy"] = counter["canonical_correct"] / counter["trials"]
        for k in (1, 3, 5):
            values[f"recall_at_{k}"] = (
                counter[f"hit{k}"] / counter["present"] if counter["present"] else None
            )
            values[f"node_recall_at_{k}"] = (
                counter[f"node_hit{k}"] / counter["present"]
                if counter["present"]
                else None
            )
        metrics.append(
            {
                **dict(
                    zip(
                        [
                            "model",
                            "pool_builder",
                            "pool_budget",
                            "policy",
                            "mode",
                            "stratum",
                            "field",
                        ],
                        key,
                        strict=True,
                    )
                ),
                **values,
            }
        )
    record_counts = defaultdict(lambda: defaultdict(int))
    for key, fields in complete.items():
        if len(fields) != 7:
            raise ValueError("incomplete evaluation record assembly")
        if all(field["present"] for field in fields.values()):
            counter = record_counts[key[2:]]
            counter["trials"] += 1
            counter["correct"] += all(field["correct"] for field in fields.values())
    summary = {
        "kind": "seed-projection-campaign-v1",
        "rows": row_count,
        "elapsed_ns": time.perf_counter_ns() - started,
        "model_inference_calls": 0,
        "metrics": metrics,
        "complete_records": [
            {"configuration": key, **dict(value)}
            for key, value in sorted(record_counts.items())
        ],
        "notes": [
            "Controlled/source-derived evidence only, no cross-site claim.",
            (
                "Node scores localize nodes; source-materialized "
                "projected values remain unscored."
            ),
            (
                "Exact value/projection accuracy, node localization, "
                "and source reads are separate outcomes."
            ),
            (
                "No target annotations enter policies; gold is used "
                "only by the evaluation after each policy output."
            ),
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({"rows": row_count, "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--rerank", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.baseline, args.rerank, args.output)
