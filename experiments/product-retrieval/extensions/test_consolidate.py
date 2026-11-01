"""Measured tables must retain nulls/cohorts and avoid duplicate controls."""

import csv
import json

from consolidate import consolidate


def test_cohorts_nulls_and_shared_controls_remain_distinct(tmp_path):
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    for model in ("minilm", "bge"):
        directory = repo / ".generated" / f"product-retrieval-{model}-v3"
        directory.mkdir(parents=True)
        entries = [
            {"method": "structural_jaccard", "recall_at_1": None, "present_trials": 0},
            {"method": "semantic_query", "recall_at_1": 0.0, "present_trials": 1},
        ]
        value = {
            key: entries
            for key in ("matrix", "splits", "circumstances", "fields", "families")
        }
        (directory / "summary.json").write_text(json.dumps(value))
    consolidate(repo, out)
    with (out / "results-matrix.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 15
    assert len([row for row in rows if row["method"] == "structural_jaccard"]) == 5
    assert all(
        row["recall_at_1"] == ""
        for row in rows
        if row["method"] == "structural_jaccard"
    )
    assert all(
        row["recall_at_1"] == "0.0" for row in rows if row["method"] == "semantic_query"
    )
    assert len({row["table"] for row in rows}) == 5
    assert all(row["source_sha256"] and row["population"] for row in rows)


def test_live_layout_budget_counts_and_whole_run_cost_are_separate(tmp_path):
    repo = tmp_path / "repo"
    directory = repo / ".generated/product-retrieval-layout-wide-to-narrow-v1"
    directory.mkdir(parents=True)
    data = {
        "metrics": [
            {
                "method": "layout_geometry",
                "budget": 5,
                "trials": 36,
                "present_dom": 33,
                "canonical_hit": 1,
            }
        ],
        "analysis_cpu_ns": 100,
        "analysis_wall_ns": 200,
        "model_inference_calls": 0,
        "network_calls": 0,
    }
    (directory / "summary.json").write_text(json.dumps(data))
    consolidate(repo, tmp_path / "out")
    with (tmp_path / "out/results-matrix.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    quality = next(row for row in rows if row["method"])
    cost = next(row for row in rows if not row["method"])
    assert quality["present_dom"] == "33"
    assert quality["canonical_hit"] == "1"
    assert quality["absent"] == "0"
    assert quality["analysis_cpu_ns"] == ""
    assert cost["analysis_cpu_ns"] == "100"


def test_model_receipts_and_total_cost_are_labeled_as_overlapping_tables(tmp_path):
    repo = tmp_path / "repo"
    directory = repo / ".generated/product-retrieval-review-evaluation-v1"
    directory.mkdir(parents=True)
    data = {
        "metrics": [{"view": "local_dom", "repeat": 0, "true_positive": 2}],
        "cost_ledger": {"provider_reported_cost_usd": 0.03},
        "requests": [
            {
                "trial": str(i),
                "status": "completed",
                "ledger": {"configured_model": "test/model", "usage": {"cost": cost}},
            }
            for i, cost in enumerate((0.01, 0.02))
        ],
    }
    (directory / "summary.json").write_text(json.dumps(data))
    consolidate(repo, tmp_path / "out")
    with (tmp_path / "out/results-matrix.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4
    assert sum(row["table"] == "whole-campaign-cost" for row in rows) == 1
    assert sum(row["table"] == "per-request-cost" for row in rows) == 2
    assert sum(row["provider_reported_cost_usd"] == "0.03" for row in rows) == 1
