"""Focused tests for the semantic embedding cache and its telemetry."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import semantic


class _Encoding:
    def __init__(self, ids: list[int], offsets: list[tuple[int, int]]) -> None:
        self.ids = ids
        self.offsets = offsets


class _Tokenizer:
    truncation = {"max_length": 4}

    def encode(self, text: str) -> _Encoding:
        matches = list(re.finditer(r"\S+", text))
        # Model-style special tokens count toward the configured maximum.
        kept = matches[: max(0, self.truncation["max_length"] - 2)]
        ids = [101, *(index + 1 for index, _ in enumerate(kept)), 102]
        offsets = [(0, 0), *(match.span() for match in kept), (0, 0)]
        return _Encoding(ids, offsets)


class _FakeModel:
    def __init__(self) -> None:
        self.tokenizer = _Tokenizer()

    def _token_count(self, texts: list[str]) -> int:
        return sum(len(self.tokenizer.encode(text).ids) for text in texts)


class _FakeEncoder:
    def __init__(self) -> None:
        self.model = _FakeModel()
        self.calls: list[list[str]] = []

    def token_count(self, texts: list[str]) -> int:
        return self.model._token_count(texts)

    def embed(
        self, texts: list[str], *, batch_size: int, parallel: int | None
    ) -> list[list[float]]:
        assert parallel is None
        assert len(texts) <= batch_size
        self.calls.append(list(texts))
        return [[float(len(text)), 1.0] for text in texts]


def _configure_backend(monkeypatch: pytest.MonkeyPatch) -> _FakeEncoder:
    encoder = _FakeEncoder()
    monkeypatch.setattr(
        semantic,
        "_runtime_identity",
        lambda model: {
            "fastembed_version": "test",
            "onnxruntime_version": "test",
            "model_registry": {"model": model, "dim": 2},
            "dimension": 2,
        },
    )
    monkeypatch.setattr(semantic, "_load_encoder", lambda model: encoder)
    return encoder


def test_batches_unique_exact_texts_and_caches_vectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    encoder = _configure_backend(monkeypatch)
    texts = ["alpha beta", "alpha beta", "gamma delta", "epsilon"]

    first = semantic.embed_texts(
        texts, tmp_path, "fastembed", "test/model", batch_size=2
    )

    assert list(first["vectors"]) == ["alpha beta", "gamma delta", "epsilon"]
    vector = first["vectors"]["alpha beta"]
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0)
    assert len(encoder.calls) == 2
    assert first["metadata"]["unique_input_count"] == 3
    assert first["metadata"]["duplicate_input_count"] == 1
    assert first["metadata"]["cache_misses"] == 3
    assert first["ledger"]["logical_embedding_calls"] == 2
    assert first["ledger"]["input_tokens"] == 11
    assert first["ledger"]["api_cost_usd"] == 0.0
    assert first["ledger"]["hardware_cost_usd"] is None

    second = semantic.embed_texts(
        texts, tmp_path, "fastembed", "test/model", batch_size=2
    )

    assert second["vectors"] == first["vectors"]
    assert second["metadata"]["cache_hits"] == 3
    assert second["metadata"]["cache_misses"] == 0
    assert second["ledger"]["logical_embedding_calls"] == 0
    assert len(encoder.calls) == 2


def test_records_exact_truncated_input_and_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    encoder = _configure_backend(monkeypatch)
    text = "one two three four five"

    result = semantic.embed_texts([text], tmp_path, "fastembed", "test/model")
    record = result["metadata"]["input_map"][text]

    assert record["truncated"] is True
    assert record["embedding_input"] == "one two"
    assert record["original_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert record["embedding_input_sha256"] == hashlib.sha256(b"one two").hexdigest()
    assert len(record["token_ids_sha256"]) == 64
    assert encoder.calls == [["one two"]]

    cached = semantic.embed_texts([text], tmp_path, "fastembed", "test/model")
    assert cached["metadata"]["input_map"][text] == record
    assert cached["ledger"]["logical_embedding_calls"] == 0


def test_model_revision_is_part_of_cache_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    encoder = _configure_backend(monkeypatch)

    semantic.embed_texts(
        ["same text"],
        tmp_path,
        "fastembed",
        "test/model",
        model_revision="revision-a",
    )
    result = semantic.embed_texts(
        ["same text"],
        tmp_path,
        "fastembed",
        "test/model",
        model_revision="revision-b",
    )

    assert result["metadata"]["cache_misses"] == 1
    assert len(encoder.calls) == 2


def test_unsupported_backend_never_falls_back_to_lexical_similarity(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="expected 'fastembed'"):
        semantic.embed_texts(["text"], tmp_path, "lexical", "some/model")


def test_rejects_malformed_cached_vectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_backend(monkeypatch)
    result = semantic.embed_texts(["cache me"], tmp_path, "fastembed", "test/model")
    identity_key = result["metadata"]["identity_sha256"]
    text_key = hashlib.sha256(b"cache me").hexdigest()
    cache_path = tmp_path / "vectors" / identity_key / f"{text_key}.json"
    payload: dict[str, Any] = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["vector"] = [float("nan"), 1.0]
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        semantic.EmbeddingCacheError, match="Malformed embedding vector"
    ):
        semantic.embed_texts(["cache me"], tmp_path, "fastembed", "test/model")
