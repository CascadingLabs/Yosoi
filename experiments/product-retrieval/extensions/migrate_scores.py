"""Reuse measured scalar scores after the v2 field-scheduling evaluator repair."""

import argparse
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from run_matrix import canonical, checksum


def identity(frozen, data, case, repeats):
    cases = {c["id"]: c for c in data["cases"]}
    return checksum(
        {
            "corpus_checksum": frozen["corpus_checksum"],
            "runner_code": frozen["implementation"]["run_matrix.py"],
            "candidate_input": case["candidates"],
            "reference_cases": [cases[r]["candidates"] for r in data["references"]],
            "queries": frozen["queries"],
            "methods_code": frozen["implementation"]["methods.py"],
            "repeats": repeats,
        }
    )


def migrate(previous, current, repeats=1):
    old = json.loads((previous / "frozen.json").read_text())
    new = json.loads((current / "frozen.json").read_text())
    data = json.loads((current / "corpus.json").read_text())
    if (
        checksum(data) != old["corpus_checksum"]
        or checksum(data) != new["corpus_checksum"]
    ):
        raise ValueError("only identical annotated candidate corpora can migrate")
    if old["queries"] != new["queries"] or old["methods"] != new["methods"]:
        raise ValueError("queries or scoring methods changed")
    if old["implementation"]["methods.py"] != new["implementation"]["methods.py"]:
        raise ValueError("scorer code changed")
    migrated = []
    for case in data["cases"]:
        source = (
            previous.parent
            / "scoring-cache"
            / f"{identity(old, data, case, repeats)}.json.gz"
        )
        if not source.exists():
            continue
        destination = (
            current.parent
            / "scoring-cache"
            / f"{identity(new, data, case, repeats)}.json.gz"
        )
        if destination.exists():
            raise ValueError("refusing to replace an existing cache")
        entries = json.loads(gzip.decompress(source.read_bytes()))
        converted = {}
        for key, entry in entries.items():
            parts = json.loads(key)
            if len(parts) != 4 or parts[1].startswith("semantic"):
                raise ValueError("expected v2 nonsemantic cache entries")
            candidates = (
                [c for c in case["candidates"] if c["projection"] == "text"]
                if parts[0] == "root"
                else case["candidates"]
            )
            if len(entry["scores"]) != len(candidates) or any(
                not math.isfinite(s) or s < 0 for s in entry["scores"]
            ):
                raise ValueError("invalid cached score vector")
            entry["timing"]["migration_from_runner_sha256"] = old["implementation"][
                "run_matrix.py"
            ]
            converted[json.dumps([*parts, None])] = entry
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(gzip.compress(canonical(converted), mtime=0))
        migrated.append(
            {
                "case": case["id"],
                "entries": len(converted),
                "from": source.name,
                "to": destination.name,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "destination_sha256": hashlib.sha256(
                    destination.read_bytes()
                ).hexdigest(),
            }
        )
    certificate = {
        "kind": "v2-evaluator-repair-score-migration-v1",
        "reason": (
            "Root now precedes scoped fields; immutable scorer "
            "inputs, method code and score calculations are "
            "unchanged. Selection metrics are recomputed, never "
            "migrated."
        ),
        "from_runner": old["implementation"]["run_matrix.py"],
        "to_runner": new["implementation"]["run_matrix.py"],
        "migration_code_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "cases": migrated,
    }
    (current / "score-migration.json").write_text(json.dumps(certificate, indent=2))
    print(
        json.dumps(
            {
                "migrated_cases": len(migrated),
                "score_vectors": sum(c["entries"] for c in migrated),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    args = parser.parse_args()
    migrate(args.previous, args.current)
