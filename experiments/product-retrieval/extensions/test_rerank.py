"""Mocked tests for bounded cross-encoder reranking and pair caching."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from extensions import rerank


class _Encoding:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids


class _Tokenizer:
    truncation = {"max_length": 6}

    def __init__(self) -> None:
        self.limit = self.truncation["max_length"]

    def to_str(self) -> str:
        return str(self.limit)

    def no_truncation(self) -> None:
        self.limit = 0

    def encode(self, query: str, document: str) -> _Encoding:
        query_tokens = re.findall(r"\S+", query)
        document_tokens = re.findall(r"\S+", document)
        tokens = [101, *(len(token) for token in query_tokens), 102]
        tokens.extend(len(token) for token in document_tokens)
        tokens.append(102)
        if self.limit:
            tokens = tokens[: self.limit]
        return _Encoding(tokens)


class _FakeEncoder:
    def __init__(self) -> None:
        self.model = SimpleNamespace(tokenizer=_Tokenizer(), _model_dir=None)
        self.calls: list[list[tuple[str, str]]] = []

    def rerank_pairs(
        self,
        pairs: list[tuple[str, str]],
        *,
        batch_size: int,
        parallel: int | None,
    ) -> list[float]:
        assert parallel is None
        assert len(pairs) <= batch_size
        self.calls.append(list(pairs))
        return [float(len(document)) - 10.0 for _, document in pairs]


class _TokenizerFactory:
    @staticmethod
    def from_str(value: str) -> _Tokenizer:
        return _Tokenizer()


def _candidate(
    identifier: str, text: str, context: str, *, node_id: str | None = None
) -> dict[str, Any]:
    return {
        "id": identifier,
        "node_id": node_id or identifier,
        "text": text,
        "context": context,
        "tag": "input",
        "path": ["html", "body", "input"],
        "motifs": ["form-control"],
        "attributes": {"name": "field"},
        "expected": ["gold-label-must-not-be-used"],
    }


def _configure_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[_FakeEncoder], list[str]]:
    encoders: list[_FakeEncoder] = []
    load_calls: list[str] = []

    def runtime_identity(model: str) -> dict[str, Any]:
        return {
            "fastembed_version": "test",
            "onnxruntime_version": "test",
            "model_registry": {
                "model": model,
                "sources": {"hf": f"Xenova/{model.rsplit('/', 1)[-1]}"},
                "model_file": "onnx/model.onnx",
                "additional_files": [],
                "size_in_GB": 0.08 if model.endswith("L-6-v2") else 0.12,
                "license": "apache-2.0",
                "description": "test model",
            },
        }

    def load_encoder(model: str) -> _FakeEncoder:
        load_calls.append(model)
        encoder = _FakeEncoder()
        encoders.append(encoder)
        return encoder

    monkeypatch.setattr(rerank, "_runtime_identity", runtime_identity)
    monkeypatch.setattr(rerank, "_load_encoder", load_encoder)
    monkeypatch.setitem(
        sys.modules, "tokenizers", SimpleNamespace(Tokenizer=_TokenizerFactory)
    )
    return encoders, load_calls


def test_scores_only_the_bounded_pool_and_preserves_raw_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    encoders, load_calls = _configure_backend(monkeypatch)
    candidates = [
        _candidate("candidate-a", "First", "Short context"),
        _candidate("outside-pool", "Never", "Must not be inspected"),
        _candidate("candidate-c", "Third", "A much longer context here"),
    ]

    result = rerank.rerank_pairs(
        "destination field",
        candidates,
        [2, 0],
        tmp_path,
        "Xenova/ms-marco-MiniLM-L-6-v2",
    )

    assert len(load_calls) == 1
    assert encoders[0].calls == [
        [
            ("destination field", "Third\nA much longer context here"),
            ("destination field", "First\nShort context"),
        ]
    ]
    assert set(result["scores"]) == {0, 2}
    assert [item["candidate_id"] for item in result["ranked"]] == [
        "candidate-c",
        "candidate-a",
    ]
    assert result["ranked"][0]["raw_score"] > result["ranked"][1]["raw_score"]
    assert result["metadata"]["pool_indices"] == [2, 0]
    assert result["metadata"]["pool_count"] == 2
    assert result["metadata"]["scores_are_calibrated_confidence"] is False
    assert "expected" not in json.dumps(result["metadata"]["pool_inputs"])
    assert result["ledger"]["inference_calls"] == 1
    assert result["ledger"]["input_pairs"] == 2
    assert result["ledger"]["api_cost_usd"] == 0.0
    assert result["ledger"]["hardware_cost_usd"] is None


def test_cache_reuses_exact_query_document_pair_and_keeps_current_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    encoders, load_calls = _configure_backend(monkeypatch)
    first_candidates = [_candidate("old-id", "Name", "Product name")]
    second_candidates = [_candidate("new-id", "Name", "Product name")]
    model = "Xenova/ms-marco-MiniLM-L-6-v2"

    first = rerank.rerank_pairs("product name", first_candidates, [0], tmp_path, model)
    second = rerank.rerank_pairs(
        "product name", second_candidates, [0], tmp_path, model
    )

    assert len(load_calls) == 1
    assert first["scores"][0] == second["scores"][0]
    assert second["ranked"][0]["candidate_id"] == "new-id"
    assert second["ledger"]["cache_hits"] == 1
    assert second["ledger"]["cache_misses"] == 0
    assert second["ledger"]["inference_calls"] == 0
    assert len(encoders[0].calls) == 1


def test_records_pair_tokenization_and_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_backend(monkeypatch)
    candidate = _candidate("long", "one two three four five", "six seven eight")

    result = rerank.rerank_pairs(
        "query words",
        [candidate],
        [0],
        tmp_path,
        "Xenova/ms-marco-MiniLM-L-6-v2",
    )
    pair_record = result["metadata"]["pool_inputs"][0]
    cache_record = next((tmp_path / "pairs").rglob("*.json"))
    cached = json.loads(cache_record.read_text(encoding="utf-8"))
    telemetry = result["metadata"]["pair_telemetry"][pair_record["pair_sha256"]]

    assert (
        pair_record["pair_sha256"]
        == hashlib.sha256(
            json.dumps(
                ["query words", "one two three four five\nsix seven eight"],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    assert cached["telemetry"]["truncated"] is True
    assert telemetry == cached["telemetry"]
    assert (
        cached["telemetry"]["untruncated_input_tokens"]
        > cached["telemetry"]["model_input_tokens"]
    )
    assert len(cached["telemetry"]["model_token_ids_sha256"]) == 64
    assert result["ledger"]["truncated_pairs"] == 1


def test_model_identity_separates_l6_and_l12_cache_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _encoders, load_calls = _configure_backend(monkeypatch)
    candidates = [_candidate("one", "Name", "A name field")]

    rerank.rerank_pairs(
        "name field", candidates, [0], tmp_path, "Xenova/ms-marco-MiniLM-L-6-v2"
    )
    rerank.rerank_pairs(
        "name field", candidates, [0], tmp_path, "Xenova/ms-marco-MiniLM-L-12-v2"
    )

    assert load_calls == [
        "Xenova/ms-marco-MiniLM-L-6-v2",
        "Xenova/ms-marco-MiniLM-L-12-v2",
    ]


def test_empty_pool_does_not_initialize_a_model_and_bad_representation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _encoders, load_calls = _configure_backend(monkeypatch)

    empty = rerank.rerank_pairs(
        "field intent", [], [], tmp_path, "Xenova/ms-marco-MiniLM-L-6-v2"
    )

    assert empty["scores"] == {}
    assert empty["ranked"] == []
    assert empty["ledger"]["inference_calls"] == 0
    assert load_calls == []
    with pytest.raises(ValueError, match="unknown representation"):
        rerank.rerank_pairs(
            "field intent",
            [],
            [],
            tmp_path,
            "Xenova/ms-marco-MiniLM-L-6-v2",
            representation="invalid",
        )


@pytest.mark.parametrize(
    ("pool", "message"),
    [
        ([0, 0], "duplicates"),
        ([-1], "out-of-range"),
        ([1], "out-of-range"),
        (list(range(51)), "bounded"),
        ([True], "integers"),
    ],
)
def test_rejects_invalid_pool_indices(
    tmp_path: Path, pool: list[int], message: str
) -> None:
    candidates = [_candidate("one", "Name", "A name field")]
    with pytest.raises(
        ValueError if message != "integers" else TypeError, match=message
    ):
        rerank.rerank_pairs(
            "name field", candidates, pool, tmp_path, "Xenova/ms-marco-MiniLM-L-6-v2"
        )


def test_unsupported_model_and_malformed_cache_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_backend(monkeypatch)
    candidates = [_candidate("one", "Name", "A name field")]
    with pytest.raises(ValueError, match="Unsupported reranker"):
        rerank.rerank_pairs("name", candidates, [0], tmp_path, "unregistered/model")

    rerank.rerank_pairs(
        "name", candidates, [0], tmp_path, "Xenova/ms-marco-MiniLM-L-6-v2"
    )
    cache_path = next((tmp_path / "pairs").rglob("*.json"))
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["raw_score"] = float("nan")
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(rerank.RerankCacheError, match="Malformed cached score"):
        rerank.rerank_pairs(
            "name", candidates, [0], tmp_path, "Xenova/ms-marco-MiniLM-L-6-v2"
        )
