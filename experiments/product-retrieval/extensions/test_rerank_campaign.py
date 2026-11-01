"""Mocked tests for blind pool planning, global pair reuse and evaluation."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

rerank = importlib.import_module("rerank")
campaign = importlib.import_module("rerank_campaign")


def _candidate(
    identity: str,
    text: str,
    *,
    projection: str = "text",
    node_id: str | None = None,
    ancestors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": identity,
        "node_id": node_id or identity,
        "projection": projection,
        "text": text,
        "context": f"context {text}",
        "tag": "span",
        "path": ["html", "body", "span"],
        "motifs": ["label-value"],
        "attributes": {},
        "ancestors": ancestors or [],
    }


def _score_map(
    candidates: list[dict[str, Any]], fields: list[str], groups: list[str], digest: str
):
    result = {}
    for field in fields:
        if field == "root":
            count = sum(candidate["projection"] == "text" for candidate in candidates)
        else:
            count = len(candidates)
        baseline = [float(index + 1) / max(1, count) for index in range(count)]
        for group in groups:
            for method in (
                "hierarchical_jaccard",
                "lexical_char_ngram_cosine_reference",
                "semantic_reference",
            ):
                result[
                    json.dumps(
                        [
                            field,
                            method,
                            group,
                            "context",
                            digest if method == "semantic_reference" else None,
                        ]
                    )
                ] = {"scores": baseline}
        for method in ("bm25", "semantic_query"):
            result[
                json.dumps(
                    [
                        field,
                        method,
                        "query_only",
                        "context",
                        digest if method == "semantic_query" else None,
                    ]
                )
            ] = {"scores": baseline}
    return result


def test_rrf_pool_uses_only_positive_union_and_deduplicates_identity() -> None:
    candidates = [
        _candidate("a", "Alpha"),
        _candidate("b", "Beta"),
        _candidate("c", "Gamma"),
    ]
    pool, fused = campaign.build_rrf_pool(
        candidates,
        [("structure", [0.9, 0.7, 0.0]), ("text", [0.0, 0.8, 0.6])],
        3,
    )

    assert [candidates[index]["id"] for index in pool] == ["b", "a", "c"]
    assert set(fused) == {"a", "b", "c"}
    assert fused["b"] > fused["a"] > fused["c"]


def test_root_projection_maps_local_indices_to_text_candidates() -> None:
    candidates = [
        _candidate("before", "Before", projection="@class"),
        _candidate("root-a", "Root A"),
        _candidate("attribute", "Attribute", projection="@content"),
        _candidate("root-b", "Root B"),
    ]
    projected = campaign.candidate_universe(candidates, "root")
    pool, _ = campaign.build_rrf_pool(projected, [("seed", [0.1, 0.9])], 1)

    assert [candidate["id"] for candidate in projected] == ["root-a", "root-b"]
    assert pool == [1]
    assert projected[pool[0]]["id"] == "root-b"


def test_plan_builds_two_seed_groups_budgets_without_copying_gold() -> None:
    candidates = [
        _candidate("field-a", "Field A"),
        _candidate("field-b", "Field B"),
        _candidate("attr-a", "Attr A", projection="@content"),
    ]
    case = {
        "id": "case-a",
        "source_id": "source-a",
        "variant": "original",
        "family": "template-a",
        "split": "development",
        "candidates": candidates,
        "expected": {"name": ["gold-only"], "root": ["gold-root"]},
        "canonical_expected": {},
    }
    frozen = {
        "corpus_checksum": "frozen-corpus",
        "field_order": ["root", "name"],
        "queries": {"root": "Root intent", "name": "Name intent"},
        "reference_groups": [{"id": "lamp"}, {"id": "mug"}],
    }
    plan = campaign.build_plan(
        frozen,
        {"cases": [case]},
        {
            "case-a": _score_map(
                candidates, ["root", "name"], ["lamp", "mug"], "semantic-v1"
            )
        },
        "semantic-v1",
        budgets=(1, 2),
    )

    assert plan["plan"]["reranker_jobs_per_model"] == 16
    assert plan["plan"]["pool_builders"] == list(campaign._POOL_BUILDERS)
    assert (
        plan["plan"]["unique_exact_pairs_per_model"]
        < plan["plan"]["pooled_candidate_occurrences_per_model"]
    )
    assert all(
        job["field"] == "root" or job["candidate_universe"] == "all_candidates"
        for job in plan["jobs"]
    )
    assert all("expected" not in job for job in plan["jobs"])
    serialized = json.dumps(plan)
    assert "gold-only" not in serialized
    assert "gold-root" not in serialized
    assert len({pair["pair_sha256"] for pair in plan["unique_pairs"]}) == len(
        plan["unique_pairs"]
    )


def test_model_executor_scores_each_unique_pair_once_and_enforces_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[tuple[str, str]]] = []
    loader_calls: list[str] = []

    class FakeEncoder:
        model = object()

        def rerank_pairs(self, pairs, *, batch_size, parallel):
            assert parallel is None
            calls.append(list(pairs))
            return [-1.0 - len(document) for _, document in pairs]

    monkeypatch.setattr(
        rerank,
        "_runtime_identity",
        lambda model: {"fastembed_version": "mock", "model_registry": {"model": model}},
    )
    monkeypatch.setattr(
        rerank,
        "_load_encoder",
        lambda model: loader_calls.append(model) or FakeEncoder(),
    )
    monkeypatch.setattr(
        rerank,
        "_resolved_model_artifact",
        lambda encoder, runtime: {"revision": "mock"},
    )
    monkeypatch.setattr(
        rerank,
        "_pair_telemetry",
        lambda encoder, pairs: (
            [
                {
                    "model_input_tokens": 4,
                    "untruncated_input_tokens": 4,
                    "truncated": False,
                    "model_token_ids_sha256": "token-hash",
                }
                for _ in pairs
            ],
            1.0,
        ),
    )
    monkeypatch.setattr(rerank, "_model_cache_path", lambda: None)
    monkeypatch.setattr(
        rerank,
        "_write_cache_entry",
        lambda *args, **kwargs: None,
    )

    plan = {
        "plan": {"models": [campaign._MODELS[0]]},
        "unique_pairs": [
            {"pair_sha256": "p1", "query": "q", "document": "doc1"},
            {"pair_sha256": "p2", "query": "q", "document": "doc2"},
        ],
    }
    with pytest.raises(ValueError, match="authorized cap"):
        campaign.execute_model(
            plan, campaign._MODELS[0], tmp_path, max_new_unique_pairs=1
        )
    assert loader_calls == []

    result = campaign.execute_model(
        plan, campaign._MODELS[0], tmp_path, max_new_unique_pairs=2
    )
    assert loader_calls == [campaign._MODELS[0]]
    assert calls == [[("q", "doc1"), ("q", "doc2")]]
    assert result["scores"] == {"p1": -5.0, "p2": -5.0}
    assert result["ledger"]["inference_calls"] == 1
    assert result["ledger"]["input_tokens"] == 8


def test_scoped_evaluation_uses_predicted_root_not_gold_root() -> None:
    root_candidate = _candidate("root-text", "Product region", node_id="root-node")
    good = _candidate("good", "Name", node_id="root-node")
    decoy = _candidate("decoy", "Other name", node_id="other-root")
    corpus = {
        "cases": [
            {
                "id": "case-a",
                "source_id": "source-a",
                "split": "development",
                "variant": "original",
                "family": "family-a",
                "owning_root_id": "root-node",
                "candidates": [root_candidate, good, decoy],
                "expected": {"root": ["root-text"], "name": ["good"]},
                "canonical_expected": {"root": ["root-text"], "name": ["good"]},
            }
        ]
    }
    plan = {
        "plan": {"fields": ["root", "name"]},
        "jobs": [
            {
                "job_id": "root-job",
                "case_id": "case-a",
                "source_id": "source-a",
                "split": "development",
                "variant": "original",
                "family": "family-a",
                "seed_group": "lamp",
                "pool_builder": "builder",
                "pool_budget": 2,
                "field": "root",
                "pool_count": 1,
                "pool_items": [
                    {
                        "candidate_index": 0,
                        "candidate_id": "root-text",
                        "node_id": "root-node",
                        "pair_sha256": "root-pair",
                        "fusion_score": 1.0,
                    }
                ],
            },
            {
                "job_id": "name-job",
                "case_id": "case-a",
                "source_id": "source-a",
                "split": "development",
                "variant": "original",
                "family": "family-a",
                "seed_group": "lamp",
                "pool_builder": "builder",
                "pool_budget": 2,
                "field": "name",
                "pool_count": 2,
                "pool_items": [
                    {
                        "candidate_index": 2,
                        "candidate_id": "decoy",
                        "node_id": "other-root",
                        "pair_sha256": "decoy-pair",
                        "fusion_score": 2.0,
                    },
                    {
                        "candidate_index": 1,
                        "candidate_id": "good",
                        "node_id": "root-node",
                        "pair_sha256": "good-pair",
                        "fusion_score": 1.0,
                    },
                ],
            },
        ],
    }
    result = campaign.evaluate_model(
        plan,
        corpus,
        {
            "model": campaign._MODELS[0],
            "scores": {"root-pair": 0.2, "decoy-pair": 3.0, "good-pair": -1.0},
        },
    )
    rows = {(row["field"], row["mode"]): row for row in result["job_rows"]}

    assert rows[("root", "global")]["top"][0]["id"] == "root-text"
    assert rows[("name", "global")]["top"][0]["id"] == "decoy"
    assert rows[("name", "predicted_root")]["predicted_root_node_id"] == "root-node"
    assert rows[("name", "predicted_root")]["top"][0]["id"] == "good"
    assert rows[("name", "predicted_root")]["top1_correct"] is True
