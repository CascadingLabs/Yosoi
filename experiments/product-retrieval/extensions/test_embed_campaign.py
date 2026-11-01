"""Mocked checks for cache reuse and verified offline semantic execution."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import embed_campaign
import pytest
import semantic


def test_completed_batch_cost_is_durable_before_outer_artifact(tmp_path):
    class Encoder:
        model = "verified"

        def embed(self, texts, **kwargs):
            return [[float(len(text)), 1.0] for text in texts]

    ledger = tmp_path / "batches.jsonl"
    wrapped = embed_campaign.BatchLedgerEncoder(Encoder(), ledger, "run", "model")
    assert wrapped.model == "verified"
    assert wrapped.embed(["first", "second"], batch_size=2) == [[5.0, 1.0], [6.0, 1.0]]
    entry = json.loads(ledger.read_text())
    assert entry["kind"] == "completed_embedding_batch"
    assert entry["inputs"] == 2
    assert entry["prepared_input_sha256"] == [
        hashlib.sha256(t.encode()).hexdigest() for t in ["first", "second"]
    ]
    assert entry["cpu_ns"] >= 0


def test_identity_preserves_the_prior_embedder_configuration() -> None:
    runtime = {"fastembed_version": "0.9.1", "onnxruntime_version": "1.31.1"}

    identity = embed_campaign._embedding_identity("some/model", runtime)

    assert identity["model_revision"] is None
    assert identity["configuration"] == {
        "batch_size": 32,
        "normalize": True,
        "onnx_intra_op_threads": 1,
        "onnx_inter_op_threads": 1,
        "parallel_workers": 1,
    }


def test_cache_inventory_reuses_old_vectors_and_counts_new_inputs(
    tmp_path: Path,
) -> None:
    texts = ["old exact text", "new exact text"]
    identity = {"backend": "fastembed", "model": "test/model"}
    entries = tmp_path / "vectors" / semantic._sha256_json(identity)
    record = {
        "original_sha256": semantic._sha256_text(texts[0]),
        "embedding_input": texts[0],
    }
    semantic._write_cache_entry(
        entries, texts[0], [1.0, 0.0], identity, texts[0], record
    )

    counts = embed_campaign.count_cache_entries(
        texts, [texts[0]], tmp_path, identity, dimension=2
    )

    assert counts == {
        "old_vector_entries_verified": 1,
        "new_texts_cached": 1,
        "new_texts_missing": 1,
        "old_texts_retired": 0,
        "original_exact_overlap": 1,
        "resumed_expanded_vectors_verified": 0,
    }

    semantic._write_cache_entry(
        entries,
        texts[1],
        [0.0, 1.0],
        identity,
        texts[1],
        {
            "original_sha256": semantic._sha256_text(texts[1]),
            "embedding_input": texts[1],
        },
    )
    resumed = embed_campaign.count_cache_entries(
        texts, [texts[0]], tmp_path, identity, dimension=2
    )
    assert resumed["new_texts_cached"] == 2
    assert resumed["new_texts_missing"] == 0
    assert resumed["original_exact_overlap"] == 1
    assert resumed["resumed_expanded_vectors_verified"] == 1


def test_cached_snapshot_hashes_must_match_the_old_artifact(tmp_path: Path) -> None:
    source = "local/org-encoder"
    revision = "a1b2c3"
    repo_dir = tmp_path / f"models--{source.replace('/', '--')}"
    snapshot = repo_dir / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (repo_dir / "refs").mkdir()
    (repo_dir / "refs" / "main").write_text(revision, encoding="utf-8")
    (snapshot / "model.onnx").write_bytes(b"model-weights")
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
    (snapshot / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    model_hash = hashlib.sha256(b"model-weights").hexdigest()
    tokenizer_hash = hashlib.sha256(b"{}").hexdigest()
    artifact = {
        "upstream_repo": source,
        "resolved_snapshot_revision": revision,
        "model_file": "model.onnx",
        "tokenizer_config": {},
        "files": {
            "model.onnx": {"bytes": len(b"model-weights"), "sha256": model_hash},
            "tokenizer.json": {"bytes": 2, "sha256": tokenizer_hash},
            "tokenizer_config.json": {"bytes": 2, "sha256": tokenizer_hash},
        },
    }
    runtime = {
        "model_registry": {
            "sources": {"hf": source},
            "model_file": "model.onnx",
            "additional_files": [],
        }
    }

    resolved = embed_campaign._resolve_cached_snapshot(
        "local/model", runtime, artifact, tmp_path
    )
    assert resolved == {"snapshot_path": str(snapshot.resolve()), "artifact": artifact}

    corrupted = dict(artifact)
    corrupted["files"] = {
        **artifact["files"],
        "model.onnx": {"bytes": 1, "sha256": "bad"},
    }
    with pytest.raises(ValueError, match="does not match prior"):
        embed_campaign._resolve_cached_snapshot(
            "local/model", runtime, corrupted, tmp_path
        )


def test_execution_uses_verified_local_model_and_restores_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    texts = ["old", "new"]
    text_bytes = json.dumps(texts, separators=(",", ":")).encode()
    runtime = {"fastembed_version": "mock", "onnxruntime_version": "mock"}
    model = "sentence-transformers/all-MiniLM-L6-v2"
    identity = embed_campaign._embedding_identity(model, runtime)
    artifact = {
        "upstream_repo": "org/model",
        "resolved_snapshot_revision": "revision",
        "model_file": "model.onnx",
        "files": {"model.onnx": {"bytes": 1, "sha256": "hash"}},
    }

    def original_loader(_name):
        return "original-loader"

    monkeypatch.setattr(semantic, "_runtime_identity", lambda name: runtime)
    monkeypatch.setattr(
        embed_campaign, "_resolved_loaded_artifact", lambda encoder, info: artifact
    )
    monkeypatch.setattr(semantic, "_load_encoder", original_loader)
    created: list[dict[str, Any]] = []

    class FakeTextEmbedding:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)
            self.model = SimpleNamespace(_model_dir=Path(kwargs["specific_model_path"]))

    monkeypatch.setitem(
        sys.modules, "fastembed", SimpleNamespace(TextEmbedding=FakeTextEmbedding)
    )

    def fake_embed_texts(input_texts, cache_dir, backend, model_name, **kwargs):
        encoder = semantic._load_encoder(model_name)
        assert encoder.model._model_dir == Path("/verified/snapshot")
        return {
            "vectors": {text: [1.0, 0.0] for text in input_texts},
            "metadata": {
                "identity": identity,
                "input_map": {text: {} for text in input_texts},
                "cache_hits": 1,
                "cache_misses": 1,
                "dimension": 2,
            },
            "ledger": {"api_cost_usd": 0.0, "hardware_cost_usd": None},
        }

    monkeypatch.setattr(semantic, "embed_texts", fake_embed_texts)
    preflight = {
        "text_input": {"file_sha256": hashlib.sha256(text_bytes).hexdigest()},
        "frozen_input": {"file_sha256": "frozen-hash"},
        "execution": {
            "executor_source_sha256": {
                "semantic.py": hashlib.sha256(
                    Path(semantic.__file__).read_bytes()
                ).hexdigest(),
                "extensions/embed_campaign.py": hashlib.sha256(
                    Path(embed_campaign.__file__).read_bytes()
                ).hexdigest(),
            }
        },
    }
    entry = {
        "slug": "minilm",
        "model": model,
        "identity": identity,
        "cache_dir": str(tmp_path / "cache"),
        "cache_counts": {
            "new_texts_cached": 1,
            "new_texts_missing": 1,
            "old_texts_retired": 0,
        },
        "resolved_model": {"snapshot_path": "/verified/snapshot", "artifact": artifact},
        "loader_policy": {"local_files_only": True},
    }
    input_path = tmp_path / "texts.json"
    input_path.write_bytes(text_bytes)
    output_path = tmp_path / "vectors.json"

    result = embed_campaign.execute_model_with_verified_loader(
        preflight, entry, input_path, output_path
    )

    assert set(result["vectors"]) == set(texts)
    assert created == [
        {
            "model_name": model,
            "threads": 1,
            "cuda": False,
            "local_files_only": True,
            "specific_model_path": "/verified/snapshot",
        }
    ]
    assert semantic._load_encoder is original_loader
    assert (
        json.loads(output_path.read_text(encoding="utf-8"))["metadata"][
            "expanded_wave_preflight"
        ]["resolved_model_artifact"]
        == artifact
    )
