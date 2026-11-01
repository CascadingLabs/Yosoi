"""Shard rates are recomputed from evidence counts, not averaged."""

import hashlib
import json

import pytest
from aggregate_wave import aggregate


def test_unequal_page_populations_use_weighted_counts(tmp_path):
    wave = tmp_path / "wave"
    completed = []
    for case, n, hit in (("one", 1, 1), ("nine", 9, 0)):
        directory = wave / "minilm" / case
        directory.mkdir(parents=True)
        filters = {"case": case}
        metric = {
            "method": "test",
            "representation": "context",
            "mode": "global",
            "condition": "test",
            "field": "all",
            "trials": n,
            "evaluable": n,
            "present": n,
            "absent": 0,
            "correct": hit,
            "hit1": hit,
            "hit3": hit,
            "hit5": hit,
            "canonical1": hit,
            "canonical_evaluable": n,
            "abstained": 0,
            "operational_present": n,
            "operational_hit1": hit,
            "operational_hit3": hit,
            "operational_hit5": hit,
            "score_status_counts": {"complete": n},
            "all_attempt_scoring_median_ms": n,
        }
        summary = {
            "rows": n,
            "filters": filters,
            "score_failure_count": 0,
            "metrics": [metric],
        }
        path = directory / "summary.json"
        path.write_text(json.dumps(summary))
        (directory / "shard-complete.json").write_text(
            json.dumps(
                {
                    "rows": n,
                    "filters": filters,
                    "output_sha256": {
                        "summary.json": hashlib.sha256(path.read_bytes()).hexdigest()
                    },
                }
            )
        )
        completed.append({"model": "minilm", "case": case})
    (wave / "wave-complete.json").write_text(json.dumps({"completed": completed}))
    out = tmp_path / "out"
    aggregate(wave, out)
    result = json.loads((out / "summary.json").read_text())
    row = result["metrics"][0]
    assert result["raw_rows"] == 10
    assert row["recall_at_1"] == 0.1
    assert row["accuracy"] == 0.1
    assert row["page_median_scoring_ms_min"] == 1
    assert row["page_median_scoring_ms_max"] == 9
    (wave / "wave-complete.json").write_text(
        json.dumps({"completed": completed + completed})
    )
    with pytest.raises(ValueError, match="duplicate"):
        aggregate(wave, out)
