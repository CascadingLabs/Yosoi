"""Recompute baseline rankings from restored evidence without inference or network."""

import argparse
import gc
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import run_matrix
from acceleration import ExactCaches

QUALITY_KEYS = [
    "case",
    "group",
    "representation",
    "field",
    "method",
    "mode",
    "evaluation_mode",
    "expected_present",
    "gold_candidates",
    "candidate_present",
    "hit",
    "canonical_hit",
    "top1_correct",
    "owner_correct",
    "canonical_top1_correct",
    "reciprocal_rank",
    "top",
    "top_score",
    "margin",
    "top_tie_count",
    "context_bytes_top5",
    "abstained",
]


def quality_digest(path):
    report = json.loads(path.read_text())
    digest = hashlib.sha256()
    for row in report["rows"]:
        digest.update(run_matrix.canonical({key: row[key] for key in QUALITY_KEYS}))
        digest.update(b"\n")
    result = {
        "rows": len(report["rows"]),
        "failures": len(report["failures"]),
        "sha256": digest.hexdigest(),
    }
    del report
    gc.collect()
    return result


def replay(restored, output, semantic):
    if output.exists():
        raise ValueError("recomputation requires a new output directory")
    # Give each replay a new parent: no score-cache from the measured campaign.
    if (output.parent / "scoring-cache").exists():
        raise ValueError("replay parent already contains cached score vectors")
    expected = quality_digest(restored / "report.json")
    if expected["failures"]:
        raise ValueError("cannot certify a report with scorer failures")
    output.mkdir(parents=True)
    for filename in ("corpus.json", "frozen.json"):
        shutil.copyfile(restored / filename, output / filename)
    if not semantic.is_relative_to(restored):
        raise ValueError("semantic artifact must come from restored evidence")
    with ExactCaches() as caches:
        run_matrix.run(output, semantic)
        ledger = caches.ledger()
    observed = quality_digest(output / "report.json")
    if observed != expected:
        raise ValueError(
            f"recomputed ranking/evidence mismatch: {expected} vs {observed}"
        )
    implementation = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            Path(__file__),
            Path(__file__).with_name("acceleration.py"),
            Path(__file__).with_name("advanced_methods.py"),
        )
    }
    certificate = {
        "kind": "product-retrieval-recomputed-replay-v1",
        "expected": expected,
        "observed": observed,
        "network_calls": 0,
        "embedding_inference_calls": 0,
        "restored_semantic_sha256": hashlib.sha256(semantic.read_bytes()).hexdigest(),
        "replay_implementation_sha256": implementation,
        "exact_cache_ledger": ledger,
        "scope": (
            "All baseline method scores are recomputed from "
            "restored corpus/vectors; rankings, "
            "field/owner/absence metrics and score values match "
            "exactly. Timings are measured anew and are excluded "
            "from the equality digest. Memoization is exact and "
            "bounded; nested miss timings are not additive."
        ),
    }
    run_matrix.save(output / "replay-certificate.json", certificate)
    print(json.dumps(certificate))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restored", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--semantic", type=Path, required=True)
    args = parser.parse_args()
    replay(args.restored, args.output, args.semantic)
