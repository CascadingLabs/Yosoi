"""Projection campaign assembly must retain distinct reference-group trials."""

import json

from projection_campaign import run
from run_matrix import checksum


def test_two_reference_groups_are_not_collapsed(tmp_path):
    baseline, rerank, output = [tmp_path / p for p in ("base", "rerank", "out")]
    baseline.mkdir()
    rerank.mkdir()
    fields = ["root", "id", "name", "price", "color", "material", "stock"]

    def case(identity, split):
        candidates = [
            {
                "id": f"{identity}-{field}",
                "node_id": "r" if field in ("root", "id") else field,
                "projection": "@identity" if field == "id" else "text",
                "text": field,
                "ancestors": [] if field in ("root", "id") else ["r"],
            }
            for field in fields
        ]
        expected = {field: [f"{identity}-{field}"] for field in fields}
        return {
            "id": identity,
            "split": split,
            "candidates": candidates,
            "expected": expected,
            "canonical_expected": expected,
            "owning_root_id": "r",
            "variant": "original",
        }

    data = {"cases": [case("seed", "development"), case("target", "controlled")]}
    frozen = {
        "corpus_checksum": checksum(data),
        "reference_groups": [{"id": g, "cases": ["seed"]} for g in ("one", "two")],
    }
    jobs = [
        {
            "case_id": "target",
            "seed_group": g,
            "field": field,
            "pool_builder": "mock",
            "pool_budget": 5,
            "pool_items": [{"candidate_id": f"target-{field}", "pair_sha256": field}],
        }
        for g in ("one", "two")
        for field in fields
    ]
    (baseline / "corpus.json").write_text(json.dumps(data))
    (baseline / "frozen.json").write_text(json.dumps(frozen))
    (rerank / "plan.json").write_text(
        json.dumps({"dataset": {"corpus_checksum": checksum(data)}, "jobs": jobs})
    )
    (rerank / "mock-scores.json").write_text(
        json.dumps({"model": "mock", "scores": {field: -3.0 for field in fields}})
    )
    run(baseline, rerank, output)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["model_inference_calls"] == 0
    assert summary["rows"] == 78
    assert all(record["trials"] == 2 for record in summary["complete_records"])
    assert all(record["correct"] == 2 for record in summary["complete_records"])
