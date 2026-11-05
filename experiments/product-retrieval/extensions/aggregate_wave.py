"""Merge disjoint completed page shards using counts, never averaged rates."""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

COUNT_KEYS = {
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
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aggregate(wave, output):
    groups = defaultdict(
        lambda: {
            "counts": Counter(),
            "statuses": Counter(),
            "cases": set(),
            "median_ms": [],
        }
    )
    sources = []
    completed_wave = wave / "wave-complete.json"
    if not completed_wave.exists():
        raise ValueError(
            "wave is not terminal; do not summarize incomplete cohorts as complete"
        )
    expected = json.loads(completed_wave.read_text())["completed"]
    if len({(s["model"], s["case"]) for s in expected}) != len(expected):
        raise ValueError("duplicate completed page shards would inflate evidence")
    for shard in expected:
        directory = wave / shard["model"] / shard["case"]
        cert_file = directory / "shard-complete.json"
        certificate = json.loads(cert_file.read_text())
        path = directory / "summary.json"
        if sha(path) != certificate["output_sha256"]["summary.json"]:
            raise ValueError("shard summary changed")
        data = json.loads(path.read_text())
        if (
            data["rows"] != certificate["rows"]
            or data["filters"] != certificate["filters"]
        ):
            raise ValueError("shard identity mismatch")
        sources.append(
            {
                "model": shard["model"],
                "case": shard["case"],
                "summary": str(path),
                "summary_sha256": sha(path),
                "certificate_sha256": sha(cert_file),
                "rows": data["rows"],
                "score_failures": data["score_failure_count"],
            }
        )
        for entry in data["metrics"]:
            key = (
                shard["model"],
                entry["method"],
                entry["representation"],
                entry["mode"],
                entry["condition"],
                entry["field"],
            )
            group = groups[key]
            group["cases"].add(shard["case"])
            for name in COUNT_KEYS:
                if name in entry:
                    group["counts"][name] += entry[name]
            group["statuses"].update(entry["score_status_counts"])
            median = entry.get("all_attempt_scoring_median_ms")
            if median is not None:
                group["median_ms"].append(median)
    rows = []
    for key, group in sorted(groups.items()):
        count = group["counts"]
        row = dict(
            zip(
                ["encoder", "method", "representation", "mode", "condition", "field"],
                key,
                strict=True,
            )
        )
        row.update(count)
        row["unique_cases"] = len(group["cases"])
        row["score_status_counts"] = dict(group["statuses"])

        def rate(numerator, denominator, counts=count):
            return (
                counts[numerator] / counts[denominator] if counts[denominator] else None
            )

        row["accuracy"] = rate("correct", "evaluable")
        row["canonical_top1_accuracy"] = rate("canonical1", "canonical_evaluable")
        row["owner_accuracy"] = rate("owner_correct", "present")
        row["absent_false_positive_rate"] = rate("false_positive", "absent")
        provided = count["evaluable"] - count["abstained"]
        row["provided_candidate_precision"] = (
            count["hit1"] / provided if provided else None
        )
        row["provided_candidate_coverage"] = (
            provided / count["evaluable"] if count["evaluable"] else None
        )
        for k in (1, 3, 5):
            row[f"recall_at_{k}"] = rate(f"hit{k}", "present")
            row[f"operational_complete_recall_at_{k}"] = rate(
                f"operational_hit{k}", "operational_present"
            )
        row["page_median_scoring_ms_min"] = min(group["median_ms"], default=None)
        row["page_median_scoring_ms_max"] = max(group["median_ms"], default=None)
        rows.append(row)
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "kind": "completed-page-shard-aggregate-v1",
        "sources": sources,
        "raw_rows": sum(s["rows"] for s in sources),
        "score_failure_count": sum(s["score_failures"] for s in sources),
        "metrics": rows,
        "notes": [
            (
                "Disjoint page counts/numerators are summed; rates "
                "are recomputed, never averaged."
            ),
            (
                "No pooled latency quantile is inferred from "
                "per-shard quantiles; the range of page medians is "
                "descriptive only."
            ),
            (
                "Conditional complete quality, operating coverage, "
                "partial proposals and node/projection correctness "
                "are different outcomes."
            ),
            (
                "One-case cold engine startup differs from the "
                "earlier monolithic timing protocol."
            ),
            (
                "Agent-annotated source HTML and toy shop layouts do "
                "not establish blind production generalization."
            ),
        ],
    }
    (output / "summary.json").write_text(json.dumps(result, indent=2))
    columns = sorted({key for row in rows for key in row})
    with (output / "matrix.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(
            {
                key: json.dumps(value, sort_keys=True)
                if isinstance(value, dict)
                else value
                for key, value in row.items()
            }
            for row in rows
        )
    print(
        json.dumps(
            {
                "completed_shards": len(sources),
                "rows": result["raw_rows"],
                "metric_groups": len(rows),
                "output": str(output),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    aggregate(args.wave, args.output)
