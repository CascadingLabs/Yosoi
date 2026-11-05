"""Measure useful source proximity separately from exact field extraction.

This is an evaluation-only tree-distance diagnostic. It does not claim measured
Surface steps, semantic equivalence, or that an arbitrary ancestor is a useful
inspection. Candidates must remain within the annotated product root.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def distance(left, right, parents):
    def chain(node):
        result = {node: 0}
        while node in parents:
            node = parents[node]
            if node in result:
                raise ValueError("cycle in evaluated source tree")
            result[node] = len(result)
        return result

    a, b = chain(left), chain(right)
    return min((a[node] + b[node] for node in a.keys() & b.keys()), default=None)


def run(output, destination):
    corpus = json.loads((output / "corpus.json").read_text())
    report = json.loads((output / "report.json").read_text())
    cases = {case["id"]: case for case in corpus["cases"]}
    parents = {
        case["id"]: {
            str(n["id"]): str(n["parent"])
            for n in case["document"]["nodes"]
            if n.get("parent") is not None
        }
        for case in corpus["cases"]
    }
    candidates = {
        case["id"]: {c["id"]: c for c in case["candidates"]} for case in corpus["cases"]
    }
    groups = defaultdict(lambda: defaultdict(int))
    for row in report["rows"]:
        if row["seed_case"] or not row["expected_present"]:
            continue
        case = cases[row["case"]]
        gold_nodes = {
            candidates[case["id"]][identity]["node_id"]
            for identity in case["canonical_expected"].get(row["field"], [])
        }
        if not gold_nodes:
            continue
        distances = []
        for selected in row["top"]:
            candidate = candidates[case["id"]][selected["id"]]
            owned = (
                candidate["node_id"] == case["owning_root_id"]
                or case["owning_root_id"] in candidate["ancestors"]
            )
            values = (
                [
                    distance(candidate["node_id"], node, parents[case["id"]])
                    for node in gold_nodes
                ]
                if owned
                else []
            )
            distances.append(min((v for v in values if v is not None), default=None))
        keys = [
            (row["method"], row["representation"], row["mode"], "all", "all"),
            (
                row["method"],
                row["representation"],
                row["mode"],
                row["variant"],
                row["field"],
            ),
        ]
        for key in keys:
            tally = groups[key]
            tally["trials"] += 1
            tally["exact_top1"] += row["canonical_top1_correct"]
            for k in (1, 3, 5):
                for hops in (0, 2, 4, 6):
                    tally[f"within_{hops}_hops_at_{k}"] += any(
                        d is not None and d <= hops for d in distances[:k]
                    )
    rows = []
    for key, tally in sorted(groups.items()):
        rows.append(
            {
                **dict(
                    zip(
                        ["method", "representation", "mode", "variant", "field"],
                        key,
                        strict=True,
                    )
                ),
                **dict(tally),
                "rates": {
                    name: value / tally["trials"]
                    for name, value in tally.items()
                    if name != "trials"
                },
            }
        )
    result = {
        "kind": "product-candidate-locality-v1",
        "source_frozen_checksum": report["frozen_checksum"],
        "notes": [
            (
                "Evaluation-only distance to canonical source node, "
                "ignoring projection at distance zero."
            ),
            (
                "Same annotated owner required; no above-root "
                "whole-page candidate gets proximity credit."
            ),
            (
                "Counts describe fixed DOM-hop neighborhoods, not "
                "actual returned context coverage or measured "
                "Surface operations."
            ),
            (
                "A nearby wrong value remains an exact-extraction "
                "error; this diagnostic measures a possible "
                "discovery starting point."
            ),
        ],
        "metrics": rows,
    }
    destination.write_text(json.dumps(result, indent=2))
    print(json.dumps({"groups": len(rows), "output": str(destination)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.destination)
