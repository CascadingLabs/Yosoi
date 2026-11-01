"""Post-evaluate unchanged predictions against strict and reviewed witness labels."""

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def qualified_map(annotation, cases):
    result = {}
    for identity, case in annotation["cases"].items():
        source = cases[identity]
        candidates = {c["id"]: c for c in source["candidates"]}
        for field, review in case["fields"].items():
            selected = set()
            for alternative in review["qualified_alternatives"]:
                if (
                    alternative["decision"] != "qualified"
                    or not alternative["include_in_qualified_alternative_set"]
                ):
                    raise ValueError("unqualified evidence in qualified label set")
                candidate = candidates[alternative["candidate_id"]]
                if (
                    candidate["node_id"] != alternative["candidate_node_id"]
                    or candidate["projection"] != alternative["projection"]
                    or candidate["text"] != alternative["candidate_exact_value"]
                ):
                    raise ValueError(
                        "reviewed witness disagrees with retained source candidate"
                    )
                if (
                    candidate["node_id"] != source["owning_root_id"]
                    and source["owning_root_id"] not in candidate["ancestors"]
                ):
                    raise ValueError("reviewed witness is outside product owner")
                selected.add(candidate["id"])
            result[(identity, field)] = selected
    return result


def evaluate(wave, corpus_path, annotation_path, output):
    corpus = json.loads(corpus_path.read_text())
    cases = {case["id"]: case for case in corpus["cases"]}
    annotation = json.loads(annotation_path.read_text())
    alternatives = qualified_map(annotation, cases)
    if annotation["review"]["model_predictions_or_rankings_used"]:
        raise ValueError("label review was not independent of ranked predictions")
    completed = json.loads((wave / "wave-complete.json").read_text())["completed"]
    totals = defaultdict(lambda: defaultdict(int))
    sources = []
    for shard in completed:
        directory = Path(
            shard.get("raw_source_directory", wave / shard["model"] / shard["case"])
        )
        rows_file = directory / "rows.jsonl.gz"
        certificate = json.loads((directory / "shard-complete.json").read_text())
        rows_hash = hashlib.sha256(rows_file.read_bytes()).hexdigest()
        if rows_hash != certificate["output_sha256"]["rows.jsonl.gz"]:
            raise ValueError("ranked predictions changed after the completed run")
        sources.append(
            {
                "encoder": shard["model"],
                "case": shard["case"],
                "rows_sha256": rows_hash,
                "directory": str(directory),
            }
        )
        with gzip.open(rows_file, "rt") as stream:
            for line in stream:
                row = json.loads(line)
                case = cases[row["case"]]
                field = row["field"]
                status = case["expected_status"][field]
                top = [entry["id"] for entry in row["top"]]
                strict = set(case["expected"].get(field, []))
                qualified = strict | alternatives.get((case["id"], field), set())
                for field_key in ("all", field):
                    count = totals[
                        (
                            shard["model"],
                            row["method"],
                            row["representation"],
                            row["mode"],
                            row["condition"],
                            row["score_status"],
                            field_key,
                        )
                    ]
                    count["trials"] += 1
                    if status == "absent":
                        count["absent"] += 1
                        count["false_positive"] += bool(top)
                    elif status == "present_dom":
                        count["present"] += 1
                        for k in (1, 3, 5):
                            count[f"strict_hit{k}"] += bool(strict & set(top[:k]))
                            count[f"qualified_hit{k}"] += bool(qualified & set(top[:k]))
                    else:
                        count["unavailable"] += 1
    metrics = []
    for key, count in sorted(totals.items()):
        row = dict(
            zip(
                [
                    "encoder",
                    "method",
                    "representation",
                    "mode",
                    "condition",
                    "score_status",
                    "field",
                ],
                key,
                strict=True,
            )
        )
        row.update(count)
        for k in (1, 3, 5):
            row[f"strict_recall_at_{k}"] = (
                count[f"strict_hit{k}"] / count["present"] if count["present"] else None
            )
            row[f"qualified_recall_at_{k}"] = (
                count[f"qualified_hit{k}"] / count["present"]
                if count["present"]
                else None
            )
        metrics.append(row)
    result = {
        "kind": "unchanged-prediction-witness-evaluation-v2",
        "annotation_sha256": hashlib.sha256(annotation_path.read_bytes()).hexdigest(),
        "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "prediction_sources": sources,
        "review": annotation["review"],
        "metrics": metrics,
        "notes": [
            (
                "Scores, source documents, training references and "
                "original gold labels are unchanged."
            ),
            (
                "Qualified alternatives are a separate "
                "agent-reviewed evaluation contract, not a model "
                "improvement or independent human gold."
            ),
            (
                "Source role and exact-value support were reviewed; "
                "uncertain tag links remain excluded."
            ),
            (
                "Partial proposals retain their scorer status; they "
                "are not complete validated results."
            ),
        ],
    }
    output.write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                "shards": len(sources),
                "metric_groups": len(metrics),
                "output": str(output),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.wave, args.corpus, args.annotations, args.output)
