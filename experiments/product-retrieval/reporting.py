"""Readable permutation tables and machine-readable metrics, with denominators."""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    p = (len(values) - 1) * q
    lo = int(p)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (p - lo)


def summarize(rows):
    n = len(rows)
    present = [r for r in rows if r["expected_present"]]
    absent = [r for r in rows if not r["expected_present"]]
    latencies = [r["timing"]["median_ns"] / 1e6 for r in rows]
    out = {
        "trials": n,
        "unique_cases": len({r["case"] for r in rows}),
        "source_pages": len({r["source_id"] for r in rows}),
        "present_trials": len(present),
        "absent_trials": len(absent),
        "top1_correct": sum(r["top1_correct"] for r in rows),
        "top1_accuracy": sum(r["top1_correct"] for r in rows) / n if n else None,
        "present_top1_accuracy": sum(r["top1_correct"] for r in present) / len(present)
        if present
        else None,
        "absent_false_positive": sum(not r["abstained"] for r in absent),
        "abstentions": sum(r["abstained"] for r in rows),
        "owner_accuracy": sum(r["owner_correct"] for r in present) / len(present)
        if present
        else None,
        "candidate_recall": sum(r["candidate_present"] for r in present) / len(present)
        if present
        else None,
        "mean_gold_aliases": statistics.mean(r["gold_candidates"] for r in present)
        if present
        else None,
        "canonical_top1_accuracy": statistics.mean(
            r["canonical_top1_correct"] for r in rows
        )
        if rows
        else None,
        "mrr": statistics.mean(r["reciprocal_rank"] for r in present)
        if present
        else None,
        "latency_ms_median": percentile(latencies, 0.5),
        "latency_ms_p95": percentile(latencies, 0.95),
        "latency_ms_p99": percentile(latencies, 0.99),
        "mean_context_bytes_top5": statistics.mean(
            r["context_bytes_top5"] for r in rows
        )
        if rows
        else None,
    }
    for k in (1, 3, 5):
        hits = sum(r["hit"][str(k)] for r in present)
        out[f"hits_at_{k}"] = hits
        out[f"recall_at_{k}"] = hits / len(present) if present else None
        out[f"canonical_recall_at_{k}"] = (
            sum(r["canonical_hit"][str(k)] for r in present) / len(present)
            if present
            else None
        )
    # Complete root + all fields in an individual case/configuration.
    records = defaultdict(list)
    for row in rows:
        key = tuple(
            row[k] for k in ("case", "group", "representation", "method", "mode")
        )
        records[key].append(row)
    complete = [
        rs
        for rs in records.values()
        if len(rs) == 7
        and {r["field"] for r in rs}
        == {"root", "id", "name", "price", "color", "material", "stock"}
    ]
    out["record_decision_trials"] = len(complete)
    out["record_decision_correct"] = sum(
        all(r["top1_correct"] for r in rs) for rs in complete
    )
    full_records = [rs for rs in complete if all(r["expected_present"] for r in rs)]
    out["complete_record_trials"] = len(full_records)
    out["complete_record_correct"] = sum(
        all(r["top1_correct"] for r in rs) for rs in full_records
    )
    return out


def grouped(rows, dimensions):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[d] for d in dimensions)].append(row)
    return [
        {**dict(zip(dimensions, key, strict=True)), **summarize(group)}
        for key, group in sorted(groups.items())
    ]


def risk_curves(rows):
    """Empirical curves on this corpus, never calibrated acceptance thresholds."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row["method"], row["representation"], row["mode"])].append(row)
    curves = []
    for key, group in sorted(groups.items()):
        scores = [r["top_score"] for r in group]
        for q in (0, 0.25, 0.5, 0.75, 0.9):
            threshold = percentile(scores, q)
            accepted = [
                r for r in group if not r["abstained"] and r["top_score"] >= threshold
            ]
            curves.append(
                {
                    "method": key[0],
                    "representation": key[1],
                    "mode": key[2],
                    "threshold_quantile": q,
                    "threshold": threshold,
                    "trials": len(group),
                    "accepted": len(accepted),
                    "coverage": len(accepted) / len(group),
                    "accepted_errors": sum(not r["top1_correct"] for r in accepted),
                    "accepted_accuracy": statistics.mean(
                        r["top1_correct"] for r in accepted
                    )
                    if accepted
                    else None,
                }
            )
    return curves


def render(output: Path, report):
    rows = [r for r in report["rows"] if not r["seed_case"]]
    tables = {
        "methods": grouped(rows, ["method"]),
        "matrix": grouped(rows, ["method", "representation", "mode", "group"]),
        "circumstances": grouped(rows, ["method", "variant", "representation", "mode"]),
        "fields": grouped(rows, ["method", "field", "representation", "mode"]),
        "families": grouped(rows, ["method", "family", "representation", "mode"]),
        "splits": grouped(rows, ["method", "split", "representation", "mode"]),
    }
    summary = {
        "version": 1,
        "rows_including_seeds": len(report["rows"]),
        "evaluated_rows": len(rows),
        "failures": report["failures"],
        "skipped_methods": report["skipped_methods"],
        "elapsed_seconds": report["elapsed_ns"] / 1e9,
        "semantic": report["semantic"],
        "notes": [
            (
                "Repeated reference/representation/method trials are "
                "not independent pages."
            ),
            (
                "Original seed pages excluded; mutations derived from "
                "seeds remain controlled development cases."
            ),
            (
                "P95/P99 describe measured local samples on this "
                "corpus, not population tails."
            ),
            (
                "Query scoring times exclude feature preparation and "
                "embedding acquisition, recorded separately."
            ),
            (
                "Hybrid time includes member scoring plus fusion; "
                "component overlap is not charged as independent "
                "evidence."
            ),
            (
                "No discovery agent has been run; Surface-step savings "
                "and model repair cost are unmeasured."
            ),
            (
                "API cost is zero for offline scoring; "
                "hardware/electricity/operator cost unmeasured."
            ),
            (
                "Recall is whether any equivalent annotated candidate "
                "appears in top-k, not token overlap."
            ),
            (
                "Canonical target-node scores are also reported; "
                "equivalent descendant aliases can increase alias-aware "
                "recall."
            ),
            (
                "Candidate-universe coverage is guaranteed by "
                "construction here; this is a ranking test, not learned "
                "candidate-proposal recall."
            ),
            (
                "Missing field trials measure false positive behavior "
                "separately from present-field recall."
            ),
            (
                "Risk curves are descriptive development sweeps, not "
                "calibrated confidence or held-out policies."
            ),
        ],
        **tables,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    for name, table in tables.items():
        if not table:
            continue
        with (output / f"{name}.csv").open("w") as f:
            writer = csv.DictWriter(f, fieldnames=list(table[0]))
            writer.writeheader()
            writer.writerows(table)
    curves = risk_curves(rows)
    (output / "risk-curves.json").write_text(json.dumps(curves, indent=2))
    lines = [
        "# Product evidence retrieval matrix",
        "",
        "Development evidence; no production or universal-generalization claim.",
        "",
        f"{len(rows):,} scored field/configuration trials across "
        f"{len({r['case'] for r in rows})} cases; "
        f"{len(report['failures'])} scorer failures.",
        "",
        (
            "| Method | Trials | R@1 | R@3 | R@5 | Owner | "
            "Missing-field false positives | Median ms | P95 ms |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def fmt(value):
        return "—" if value is None else f"{value:.3f}"

    for row in sorted(tables["methods"], key=lambda r: -(r["recall_at_5"] or 0)):
        lines.append(
            f"| {row['method']} | {row['trials']} | "
            f"{fmt(row['recall_at_1'])} | {fmt(row['recall_at_3'])} | "
            f"{fmt(row['recall_at_5'])} | {fmt(row['owner_accuracy'])} | "
            f"{row['absent_false_positive']}/{row['absent_trials']} | "
            f"{fmt(row['latency_ms_median'])} | {fmt(row['latency_ms_p95'])} |"
        )
    lines += [
        "",
        "## How to interpret",
        "",
        *[f"- {note}" for note in summary["notes"]],
        "",
        (
            "Full permutations: matrix.csv; mutations: "
            "circumstances.csv; per-field: fields.csv; layout "
            "families: families.csv. Raw candidate rankings and "
            "diagnostics are in report.json. Risk/coverage sweeps "
            "are in risk-curves.json."
        ),
        "",
        "## Skips and failures",
        "",
        f"Skipped methods: {', '.join(report['skipped_methods']) or 'none'}.",
        f"Scorer failures: {len(report['failures'])}; "
        "exact case/configuration/error records in summary.json.",
    ]
    (output / "results.md").write_text("\n".join(lines) + "\n")
