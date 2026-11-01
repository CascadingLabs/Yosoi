"""Measure fixed candidate unions from unchanged channel rankings, without reranking."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import itertools
import json
import time
from collections import defaultdict
from pathlib import Path

from evaluate_witnesses import qualified_map

CHANNELS = {
    "structure": "structural_jaccard",
    "lexical": "lexical_char_ngram_cosine_reference",
    "semantic_reference": "semantic_reference",
    "semantic_query": "semantic_query",
    "semantic_prefix": "semantic_query_retrieval_prefix",
}
BUDGETS = (1, 3, 5, 10, 15)


def pool(rankings, order, budget):
    """Round-robin fixed top-five lists; neither labels nor scores enter fusion."""
    if budget < 0 or len(set(order)) != len(order):
        raise ValueError("invalid budget or repeated channel")
    result = []
    seen = set()
    for rank in range(max((len(rankings[name]) for name in order), default=0)):
        for name in order:
            if rank >= len(rankings[name]):
                continue
            identity = rankings[name][rank]
            if identity not in seen and len(result) < budget:
                result.append(identity)
                seen.add(identity)
    return result


def policies():
    result = [(name,) for name in CHANNELS]
    result.extend(itertools.permutations(("structure", "lexical")))
    for semantic in ("semantic_reference", "semantic_query", "semantic_prefix"):
        result.extend(itertools.permutations(("structure", "lexical", semantic)))
    return result


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(wave, corpus_path, labels_path, output):
    if output.exists():
        raise ValueError("refusing to overwrite measured pool evidence")
    started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    corpus = json.loads(corpus_path.read_text())
    corpus_hash = sha(corpus_path)
    cases = {case["id"]: case for case in corpus["cases"]}
    labels = json.loads(labels_path.read_text())
    if labels["review"]["model_predictions_or_rankings_used"]:
        raise ValueError(
            "qualified labels must be reviewed independently of predictions"
        )
    qualified = qualified_map(labels, cases)
    completed = json.loads((wave / "wave-complete.json").read_text())["completed"]
    totals = defaultdict(lambda: defaultdict(int))
    sources = []
    selected_policies = policies()
    for shard in completed:
        directory = Path(
            shard.get("raw_source_directory", wave / shard["model"] / shard["case"])
        )
        path = directory / "rows.jsonl.gz"
        certificate = json.loads((directory / "shard-complete.json").read_text())
        if sha(directory / "corpus.json") != corpus_hash:
            raise ValueError("evaluation corpus differs from scored corpus")
        if sha(directory / "frozen.json") != certificate["configuration_sha256"]:
            raise ValueError("completed prediction configuration changed")
        actual_hash = sha(path)
        if certificate["output_sha256"][path.name] != actual_hash:
            raise ValueError("completed predictions changed")
        sources.append(
            {"model": shard["model"], "case": shard["case"], "rows_sha256": actual_hash}
        )
        selected = {}
        with gzip.open(path, "rt") as stream:
            for line in stream:
                row = json.loads(line)
                if (
                    row["representation"] != "context"
                    or row["mode"] != "global"
                    or row["method"] not in CHANNELS.values()
                ):
                    continue
                if row["score_status"] != "complete":
                    raise ValueError(
                        "candidate-pool profile requires complete channels"
                    )
                key = row["field"], row["method"]
                if key in selected:
                    raise ValueError("multiple reference groups in one selected shard")
                selected[key] = [item["id"] for item in row["top"]]
        case = cases[shard["case"]]
        candidates = {item["id"]: item for item in case["candidates"]}
        for field, status in case["expected_status"].items():
            rankings = {
                name: selected[field, method] for name, method in CHANNELS.items()
            }
            strict = set(case["expected"].get(field, []))
            reviewed = strict | qualified.get((case["id"], field), set())
            for order in selected_policies:
                for budget in BUDGETS:
                    proposals = pool(rankings, order, budget)
                    key = shard["model"], "+".join(order), budget
                    count = totals[key]
                    count["trials"] += 1
                    count["proposals"] += len(proposals)
                    count["context_bytes"] += sum(
                        len(candidates[identity]["context"].encode())
                        for identity in proposals
                    )
                    if status == "present_dom":
                        count["present"] += 1
                        count["strict_hit"] += bool(strict & set(proposals))
                        count["qualified_hit"] += bool(reviewed & set(proposals))
                    elif status == "absent":
                        count["absent"] += 1
                        count["absent_nonempty_pool"] += bool(proposals)
                    else:
                        count["external_unavailable"] += 1
    metrics = []
    for (model, policy, budget), counts in sorted(totals.items()):
        metrics.append(
            {
                "encoder": model,
                "policy": policy,
                "candidate_budget": budget,
                **counts,
                "strict_proposal_recall": counts["strict_hit"] / counts["present"]
                if counts["present"]
                else None,
                "qualified_proposal_recall": counts["qualified_hit"] / counts["present"]
                if counts["present"]
                else None,
            }
        )
    result = {
        "kind": "fixed-channel-proposal-pool-complementarity-v1",
        "producer_sha256": sha(Path(__file__)),
        "corpus_sha256": corpus_hash,
        "qualified_labels_sha256": sha(labels_path),
        "sources": sources,
        "channels": CHANNELS,
        "budgets": BUDGETS,
        "metrics": metrics,
        "analysis_cpu_ns": time.process_time_ns() - cpu_started,
        "analysis_wall_ns": time.perf_counter_ns() - started,
        "new_model_inference_calls": 0,
        "notes": [
            "All declared orders are retained; no policy is chosen using gold.",
            (
                "Proposal-pool coverage is not accepted-value accuracy "
                "or discovery savings."
            ),
            "Original scores, top-five lists, references and labels are unchanged.",
            "Qualified witness evaluation differs from strict coordinate evaluation.",
            "Root and field proposals are pooled independently; no ownership repair.",
            (
                "Context bytes sum candidate contexts, including "
                "overlapping source content."
            ),
            "Analysis timing excludes original channel scoring and model inference.",
        ],
    }
    output.mkdir(parents=True)
    (output / "producer.py").write_bytes(Path(__file__).read_bytes())
    (output / "summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"shards": len(sources), "metric_groups": len(metrics)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.wave, args.corpus, args.labels, args.output)
