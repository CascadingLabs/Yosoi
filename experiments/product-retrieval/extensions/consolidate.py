"""Normalize measured permutation tables without merging incompatible populations."""

import argparse
import csv
import hashlib
import json
from pathlib import Path


def read(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def consolidate(repo, destination):
    generated = repo / ".generated"
    rows = []
    sources = []

    def emit(path, digest, experiment, table, entry, population, encoder, basis):
        row = {
            "experiment": experiment,
            "table": table,
            "encoder": encoder,
            "population": population,
            "quality_basis": basis,
            "source": str(path.relative_to(repo)),
            "source_sha256": digest,
        }
        # Retain all numeric denominators and categorical axes, not only maxima.
        for key, value in entry.items():
            row[key] = (
                json.dumps(value, sort_keys=True)
                if isinstance(value, (dict, list))
                else value
            )
        rows.append(row)

    for slug, encoder in (("minilm", "MiniLM"), ("bge", "BGE-small")):
        path = generated / f"product-retrieval-{slug}-v3/summary.json"
        if not path.exists():
            continue
        data, digest = read(path)
        sources.append({"path": str(path.relative_to(repo)), "sha256": digest})
        for table in ("matrix", "splits", "circumstances", "fields", "families"):
            for entry in data[table]:
                dependent = entry["method"].startswith(("semantic", "hybrid"))
                if slug == "bge" and not dependent:
                    continue  # Identical reused controls are not independent trials.
                emit(
                    path,
                    digest,
                    "controlled-baseline-v3",
                    table,
                    entry,
                    (
                        "six-source controlled development; original "
                        "self-seeds excluded; source-derived mutants retained"
                    ),
                    encoder if dependent else "shared nonsemantic control",
                    (
                        "alias-aware field ranking; canonical metrics "
                        "separate; local score timings"
                    ),
                )

    for depth in (6, 12):
        path = generated / f"product-retrieval-rerank-v1/minilm-l{depth}-summary.json"
        if not path.exists():
            continue
        data, digest = read(path)
        sources.append({"path": str(path.relative_to(repo)), "sha256": digest})
        for entry in data["per_field"]:
            emit(
                path,
                digest,
                "cross-encoder-v1",
                "per_field",
                entry,
                (
                    "60-case controlled development including "
                    "self-reference cases; no fresh-site evidence"
                ),
                f"cross-encoder MiniLM L{depth}",
                (
                    "pool recall and post-rerank field recall are "
                    "separate; raw logits uncalibrated"
                ),
            )

    path = generated / "product-retrieval-projection-v1/summary.json"
    if path.exists():
        data, digest = read(path)
        sources.append({"path": str(path.relative_to(repo)), "sha256": digest})
        for entry in data["metrics"]:
            emit(
                path,
                digest,
                "seed-projection-v1",
                "metrics",
                entry,
                (
                    "controlled/source-derived cases; use stratum for "
                    "exact population; candidate-ID ties"
                ),
                entry["model"],
                (
                    "node localization and materialized value accuracy "
                    "separate; extra reads counted; zero new inference"
                ),
            )

    path = generated / "product-retrieval-expanded-v1/summary.json"
    if path.exists():
        data, digest = read(path)
        sources.append({"path": str(path.relative_to(repo)), "sha256": digest})
        for entry in data["metrics"]:
            emit(
                path,
                digest,
                "fresh-nonsemantic-v1",
                "metrics",
                entry,
                (
                    "12 agent-annotated source-HTML pages/three "
                    "templates; QScrape two-reference group only; "
                    "non-blind"
                ),
                "no semantic model",
                (
                    "conditional-complete quality; operational "
                    "complete-result recall separate; partial proposals "
                    "not validated results"
                ),
            )

    for folder, experiment, population in (
        (
            "product-retrieval-expanded-semantic-aggregate-v1",
            "fresh-semantic-foreign-v1",
            (
                "12 agent-annotated source-HTML pages; manually "
                "supplied QScrape two-reference group"
            ),
        ),
        (
            "product-retrieval-same-site-v1/same-site-aggregate",
            "fresh-semantic-same-site-v1",
            (
                "six target pages disjoint from two same-site "
                "references; one template/site confounded; not blind"
            ),
        ),
        (
            "product-retrieval-same-site-v1/foreign-aggregate",
            "fresh-semantic-matched-foreign-v1",
            (
                "same six target pages as same-site contrast; "
                "QScrape two-reference group; reused completed "
                "outputs"
            ),
        ),
    ):
        path = generated / folder / "summary.json"
        if not path.exists():
            continue
        data, digest = read(path)
        sources.append({"path": str(path.relative_to(repo)), "sha256": digest})
        for entry in data["metrics"]:
            emit(
                path,
                digest,
                experiment,
                "metrics",
                entry,
                population,
                entry["encoder"],
                (
                    "counts merged over disjoint pages; "
                    "complete-only/operational metrics separate; latency "
                    "is range of page medians, not pooled p95"
                ),
            )

    for slug in ("minilm", "bge-small"):
        path = generated / f"product-retrieval-expanded-input/{slug}-v1.json"
        if path.exists():
            # Costs are campaign-level quantities; never repeat them as per-row prices.
            data, digest = read(path)
            ledger_path = path.with_suffix(".batches.jsonl")
            events = (
                [json.loads(line) for line in ledger_path.read_text().splitlines()]
                if ledger_path.exists()
                else []
            )
            if (
                not events
                or events[-1].get("kind") != "run_complete"
                or events[-1].get("artifact_sha256") != digest
            ):
                # Atomic publication can precede the final ledger record.
                continue
            sources.append({"path": str(path.relative_to(repo)), "sha256": digest})
            emit(
                path,
                digest,
                "expanded-embedding-v1",
                "cost",
                {
                    key: value
                    for key, value in data["ledger"].items()
                    if key != "batches"
                },
                (
                    "exact frozen input list; cached and newly computed "
                    "inputs distinguished"
                ),
                slug,
                (
                    "whole-run cost ledger; hardware unknown; "
                    "interrupted prior cost may be unknown"
                ),
            )

    for cohort in ("one-reference", "two-reference"):
        path = (
            generated
            / "product-retrieval-reference-count-v1"
            / (cohort + "-aggregate/summary.json")
        )
        if not path.exists():
            continue
        data, digest = read(path)
        sources.append({"path": str(path.relative_to(repo)), "sha256": digest})
        for entry in data["metrics"]:
            emit(
                path,
                digest,
                "matched-reference-count-v1",
                cohort,
                entry,
                "Same three held-out targets; nested one/two same-site seed sets.",
                "minilm",
                "Overlapping paired conditions, not independent pages; "
                "operational completeness separate from conditional recall.",
            )

    for condition in (
        "wide-to-wide",
        "wide-to-narrow",
        "narrow-to-wide",
        "narrow-to-narrow",
    ):
        path = generated / f"product-retrieval-layout-{condition}-v1/summary.json"
        if not path.exists():
            continue
        data, digest = read(path)
        sources.append({"path": str(path.relative_to(repo)), "sha256": digest})
        for metric in data["metrics"]:
            entry = dict(metric)
            for count in (
                "present_dom",
                "absent",
                "unresolved",
                "canonical_hit",
                "qualified_hit",
                "gold_in_universe",
                "absent_nonempty",
            ):
                entry.setdefault(count, 0)
            emit(
                path,
                digest,
                "live-layout-v1",
                condition,
                entry,
                "Four non-blind live pages; directed page/field pairs share sources.",
                "no embedding model",
                "Element localization and fixed proposal pools; "
                "self diagnostics excluded from transfer; "
                "source-verified live ordinals. "
                "Counts overlap across budgets and seed-reference availability slices.",
            )
        emit(
            path,
            digest,
            "live-layout-v1",
            "whole-analysis-cost/" + condition,
            {
                key: data[key]
                for key in (
                    "analysis_cpu_ns",
                    "analysis_wall_ns",
                    "model_inference_calls",
                    "network_calls",
                )
            },
            "One complete analysis, including all configured budgets; "
            "not per-page cost.",
            "no embedding model",
            "CPU/wall of analysis only; live capture and failed "
            "development attempts separate. Hardware cost unmeasured.",
        )

    path = generated / (
        "product-retrieval-layout-pool-ablation-v2/attempt-3-field-hits/coverage.json"
    )
    if path.exists():
        data, digest = read(path)
        sources.append({"path": str(path.relative_to(repo)), "sha256": digest})
        for entry in data["coverage_groups"]:
            emit(
                path,
                digest,
                "layout-pool-ablation-v1",
                "coverage",
                entry,
                "Same four live pages and two viewports; cached top-five lists.",
                "no embedding model",
                "Canonical/qualified field-hit rates are distinct from fractional "
                "witness coverage. No acceptance/discovery claim. Viewport gate "
                "is post-hoc. Budgets and policies are overlapping slices.",
            )

    path = generated / "product-retrieval-review-evaluation-v1/summary.json"
    if path.exists():
        data, digest = read(path)
        sources.append({"path": str(path.relative_to(repo)), "sha256": digest})
        model = next(
            (r["ledger"].get("configured_model") for r in data["requests"]), "unknown"
        )
        population = (
            "Same 210 proposals from four non-blind pages, three views and two repeats."
        )
        basis = (
            "Strict exact-role witness acceptance; not factual semantic accuracy. "
            "Supported decisions need literal selected-ID proof and untruncated text. "
            "Providers vary; repeated requests are not independent facts."
        )
        for entry in data["metrics"]:
            emit(
                path,
                digest,
                "source-grounded-model-review-v1",
                "metrics",
                entry,
                population,
                model,
                basis,
            )
        emit(
            path,
            digest,
            "source-grounded-model-review-v1",
            "whole-campaign-cost",
            data["cost_ledger"],
            population,
            model,
            "Provider-reported charged usage; HTTP round-trip latency, "
            "not workflow latency. "
            "Cost overlaps the per-request ledger table; do not add twice.",
        )
        for request in data["requests"]:
            emit(
                path,
                digest,
                "source-grounded-model-review-v1",
                "per-request-cost",
                {
                    "trial": request["trial"],
                    "request_status": request["status"],
                    **request["ledger"],
                },
                population,
                model,
                "One provider POST receipt, not per-proposal cost; "
                "overlaps campaign total.",
            )

    destination.mkdir(parents=True, exist_ok=False)
    columns = sorted({key for row in rows for key in row})
    with (destination / "results-matrix.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "kind": "fingerprint-measured-permutation-matrix-v1",
        "rows": len(rows),
        "sources": sources,
        "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rules": [
            (
                "Each row retains its own source, axes, "
                "denominators, metric basis and population."
            ),
            (
                "Different tables are overlapping slices; never sum "
                "them as independent samples."
            ),
            (
                "Static controls are included once rather than "
                "counted twice for two encoders."
            ),
            (
                "Null metrics remain null/blank, not zero; partial "
                "scorer coverage stays explicit."
            ),
            (
                "Latency quantiles differ by source protocol; do not "
                "compare as common end-to-end latency."
            ),
            "Cost tables state whole-run or single-request scope; "
            "never sum overlapping ledgers.",
            (
                "Frozen or implemented methods without results are "
                "not presented as measured."
            ),
        ],
    }
    (destination / "producer.py").write_bytes(Path(__file__).read_bytes())
    (destination / "matrix-manifest.json").write_text(json.dumps(manifest, indent=2))
    print(
        json.dumps(
            {"rows": len(rows), "sources": len(sources), "output": str(destination)}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[3]
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    consolidate(args.repo, args.output)
