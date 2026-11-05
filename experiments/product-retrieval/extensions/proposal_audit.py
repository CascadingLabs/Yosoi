"""Inspect useful partial proposals without relabeling them complete results."""

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def audit(directory, destination):
    corpus_file = directory / "corpus.json"
    rows_file = directory / "rows.jsonl.gz"
    cases = {case["id"]: case for case in json.loads(corpus_file.read_text())["cases"]}
    groups = defaultdict(lambda: defaultdict(int))
    row_count = 0
    with gzip.open(rows_file, "rt") as stream:
        for line in stream:
            row = json.loads(line)
            row_count += 1
            case = cases[row["case"]]
            field = row["field"]
            if (
                not case["expected_present"][field]
                or case["expected_status"][field] != "present_dom"
            ):
                continue
            gold = set(case["expected"].get(field, []))
            canonical = set(case["canonical_expected"].get(field, []))
            top = [candidate["id"] for candidate in row["top"]]
            for label in ("all", field):
                tally = groups[
                    (
                        row["method"],
                        row["score_status"],
                        row["representation"],
                        row["mode"],
                        label,
                    )
                ]
                tally["dom_present_trials"] += 1
                tally["nonempty_proposals"] += bool(top)
                for k in (1, 3, 5):
                    tally[f"proposed_gold_at_{k}"] += bool(gold & set(top[:k]))
                    tally[f"proposed_canonical_at_{k}"] += bool(
                        canonical & set(top[:k])
                    )
    metrics = []
    for key, tally in sorted(groups.items()):
        metrics.append(
            {
                **dict(
                    zip(
                        ["method", "score_status", "representation", "mode", "field"],
                        key,
                        strict=True,
                    )
                ),
                **dict(tally),
                "proposal_hit_rates": {
                    name: value / tally["dom_present_trials"]
                    for name, value in tally.items()
                    if name.startswith("proposed_")
                },
            }
        )
    result = {
        "kind": "partial-proposal-audit-v1",
        "input_sha256": {
            "corpus.json": hashlib.sha256(corpus_file.read_bytes()).hexdigest(),
            "rows.jsonl.gz": hashlib.sha256(rows_file.read_bytes()).hexdigest(),
        },
        "rows_inspected": row_count,
        "notes": [
            (
                "Partial and budget-limited proposals can contain "
                "useful source evidence; they are not complete or "
                "validated rankings."
            ),
            (
                "These diagnostic hit rates retain the original "
                "score_status and do not alter complete-only quality "
                "or operating-policy metrics."
            ),
            (
                "Target annotation coordinates enter only this "
                "post-hoc evaluation, never candidate scoring."
            ),
            "No inference, network or Surface operations are performed.",
        ],
        "metrics": metrics,
    }
    destination.write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {"rows": row_count, "groups": len(metrics), "output": str(destination)}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    audit(args.directory, args.destination)
