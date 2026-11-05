"""Preflight and execute an offline-compatible expanded embedding wave."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import semantic

_MODELS = {
    "minilm": "sentence-transformers/all-MiniLM-L6-v2",
    "bge-small": "BAAI/bge-small-en-v1.5",
}
_BATCH_SIZE = 32


class BatchLedgerEncoder:
    """Retain completed model-call costs even if the outer run is interrupted."""

    def __init__(self, encoder, ledger_path, run_id, model):
        self.encoder = encoder
        self.ledger_path = ledger_path
        self.run_id = run_id
        self.model_name = model

    def __getattr__(self, name):
        return getattr(self.encoder, name)

    def embed(self, texts, **kwargs):
        inputs = list(texts)
        wall = time.perf_counter_ns()
        cpu = time.process_time_ns()
        values = list(self.encoder.embed(inputs, **kwargs))
        _append_ledger(
            self.ledger_path,
            {
                "kind": "completed_embedding_batch",
                "run_id": self.run_id,
                "model": self.model_name,
                "inputs": len(inputs),
                "prepared_input_sha256": [
                    hashlib.sha256(t.encode()).hexdigest() for t in inputs
                ],
                "wall_ns": time.perf_counter_ns() - wall,
                "cpu_ns": time.process_time_ns() - cpu,
                "cache_persistence": "outer adapter persists vectors after this record",
            },
        )
        return values


def _append_ledger(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _embedding_identity(model: str, runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "backend": "fastembed",
        "model": model,
        "model_revision": None,
        "runtime": runtime,
        "configuration": {
            "batch_size": _BATCH_SIZE,
            "normalize": True,
            "onnx_intra_op_threads": 1,
            "onnx_inter_op_threads": 1,
            "parallel_workers": 1,
        },
    }


def _resolve_cached_snapshot(
    model: str,
    runtime: dict[str, Any],
    old_artifact: dict[str, Any],
    model_cache_dir: Path,
) -> dict[str, Any]:
    registry = runtime["model_registry"]
    source = registry["sources"]["hf"]
    repo_dir = model_cache_dir / f"models--{source.replace('/', '--')}"
    snapshots_dir = repo_dir / "snapshots"
    if not snapshots_dir.is_dir():
        raise ValueError(f"cached model snapshot is missing for {model}")
    refs_main = repo_dir / "refs" / "main"
    revision = (
        refs_main.read_text(encoding="utf-8").strip() if refs_main.is_file() else None
    )
    snapshot = snapshots_dir / revision if revision else None
    if snapshot is None or not snapshot.is_dir():
        available = sorted(path for path in snapshots_dir.iterdir() if path.is_dir())
        if len(available) != 1:
            raise ValueError(f"cannot select a unique cached snapshot for {model}")
        snapshot = available[0]
        revision = snapshot.name
    model_file = registry["model_file"]
    files = {}
    names = {
        model_file,
        "config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        *registry.get("additional_files", []),
    }
    for relative in sorted(names):
        path = snapshot / relative
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as source_file:
            while block := source_file.read(1024 * 1024):
                digest.update(block)
        files[relative] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    artifact = {
        "upstream_repo": source,
        "resolved_snapshot_revision": revision,
        "model_file": model_file,
        "files": files,
        "tokenizer_config": _tokenizer_config_snapshot(snapshot),
    }
    if artifact != old_artifact:
        raise ValueError(
            f"cached snapshot does not match prior {model} vector artifact"
        )
    return {"snapshot_path": str(snapshot.resolve()), "artifact": artifact}


def count_cache_entries(
    texts: list[str],
    old_texts: list[str],
    cache_dir: Path,
    identity: dict[str, Any],
    dimension: int,
) -> dict[str, int]:
    entries_dir = cache_dir / "vectors" / semantic._sha256_json(identity)
    hits = sum(
        semantic._read_cache_entry(entries_dir, text, identity, dimension) is not None
        for text in set(texts)
    )
    old_hits = sum(
        semantic._read_cache_entry(entries_dir, text, identity, dimension) is not None
        for text in set(old_texts)
    )
    overlap = len(set(texts) & set(old_texts))
    if old_hits != len(set(old_texts)):
        raise ValueError("one or more prior vectors are absent or invalid")
    if hits < overlap:
        raise ValueError("one or more overlapping prior vectors are absent or invalid")
    return {
        "old_vector_entries_verified": old_hits,
        "new_texts_cached": hits,
        "new_texts_missing": len(set(texts)) - hits,
        "old_texts_retired": len(set(old_texts) - set(texts)),
        "original_exact_overlap": overlap,
        "resumed_expanded_vectors_verified": hits - overlap,
    }


def build_model_preflight(
    texts_path: Path,
    frozen_path: Path,
    old_texts_path: Path,
    old_artifacts_dir: Path,
    model_cache_dir: Path,
) -> dict[str, Any]:
    texts_bytes = Path(texts_path).read_bytes()
    texts = json.loads(texts_bytes)
    if len(texts) != len(set(texts)):
        raise ValueError("expanded semantic inputs must be unique literal strings")
    frozen_bytes = Path(frozen_path).read_bytes()
    frozen = json.loads(frozen_bytes)
    file_sha = hashlib.sha256(texts_bytes).hexdigest()
    if frozen["semantic_input_checksum"] != file_sha:
        raise ValueError(
            "expanded texts do not match the frozen semantic-input checksum"
        )
    if frozen["semantic_input_count"] != len(texts):
        raise ValueError("expanded semantic-input count differs from frozen config")
    old_texts = json.loads(Path(old_texts_path).read_text(encoding="utf-8"))
    old_artifacts_dir = Path(old_artifacts_dir)
    model_cache_dir = Path(model_cache_dir).expanduser().resolve()
    semantic_source = Path(semantic.__file__).resolve()
    executor_source = Path(__file__).resolve()
    entries = []
    for slug, model in _MODELS.items():
        old_artifact_path = old_artifacts_dir / f"{slug}.json"
        old_artifact = json.loads(old_artifact_path.read_text(encoding="utf-8"))
        old_identity = old_artifact["metadata"]["identity"]
        runtime = semantic._runtime_identity(model)
        identity = _embedding_identity(model, runtime)
        if identity != old_identity:
            raise ValueError(
                f"{slug}: runtime/config does not match old vector cache identity"
            )
        if (
            semantic._sha256_json(identity)
            != old_artifact["metadata"]["identity_sha256"]
        ):
            raise ValueError(
                f"{slug}: semantic identity hash does not match old vector cache"
            )
        old_resolved = old_artifact["metadata"]["resolved_model_artifact"]
        snapshot_info = _resolve_cached_snapshot(
            model, runtime, old_resolved, model_cache_dir
        )
        cache_dir = old_artifacts_dir / ".semantic-cache" / slug
        cache_counts = count_cache_entries(
            texts, old_texts, cache_dir, identity, runtime["dimension"]
        )
        entries.append(
            {
                "slug": slug,
                "model": model,
                "identity": identity,
                "identity_sha256": semantic._sha256_json(identity),
                "cache_dir": str(cache_dir.resolve()),
                "cache_counts": cache_counts,
                "old_artifact_sha256": hashlib.sha256(
                    old_artifact_path.read_bytes()
                ).hexdigest(),
                "resolved_model": snapshot_info,
            }
        )
    return {
        "format": "product-retrieval-expanded-semantic-preflight-v1",
        "text_input": {
            "path": str(Path(texts_path)),
            "file_sha256": file_sha,
            "text_array_sha256": semantic._sha256_json(texts),
            "count": len(texts),
            "utf8_bytes": sum(len(text.encode("utf-8")) for text in texts),
            "max_chars": max(map(len, texts), default=0),
            "old_text_count": len(set(old_texts)),
            "exact_overlap_count": len(set(texts) & set(old_texts)),
        },
        "frozen_input": {
            "path": str(Path(frozen_path)),
            "file_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
            "configuration_checksum": frozen["configuration_checksum"],
            "corpus_checksum": frozen["corpus_checksum"],
            "semantic_input_checksum": frozen["semantic_input_checksum"],
            "semantic_query_prefix": frozen.get("semantic_query_prefix"),
            "field_order": frozen["field_order"],
            "representations": frozen["representations"],
            "code_identity": frozen["code_identity"],
        },
        "execution": {
            "python": "UV-managed CPython 3.12",
            "executor_source_sha256": {
                "semantic.py": hashlib.sha256(semantic_source.read_bytes()).hexdigest(),
                "extensions/embed_campaign.py": hashlib.sha256(
                    executor_source.read_bytes()
                ).hexdigest(),
            },
            "fastembed_version": entries[0]["identity"]["runtime"]["fastembed_version"],
            "onnxruntime_version": entries[0]["identity"]["runtime"][
                "onnxruntime_version"
            ],
            "batch_size": _BATCH_SIZE,
            "threads": {"intra_op": 1, "inter_op": 1, "parallel_workers": 1},
            "loader": (
                "local_files_only with verified specific_model_path; HF_HUB_OFFLINE=1"
            ),
            "model_revision": None,
            "prefixing": (
                "use frozen literal text array exactly; no executor-added prefix"
            ),
            "direct_api_cost_usd": 0.0,
            "hardware_cost_usd": None,
            "inference_calls_made": 0,
        },
        "models": entries,
    }


def execute_preflighted_model(
    preflight: dict[str, Any], slug: str, texts_path: Path, output_path: Path
) -> dict[str, Any]:
    entry = next((item for item in preflight["models"] if item["slug"] == slug), None)
    if entry is None:
        raise ValueError(f"unknown preflight model slug: {slug}")
    return execute_model_with_verified_loader(preflight, entry, texts_path, output_path)


def execute_model_with_verified_loader(
    preflight: dict[str, Any],
    entry: dict[str, Any],
    texts_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    output_path = Path(output_path)
    sources = preflight.get("execution", {}).get("executor_source_sha256", {})
    for name, source in {
        "semantic.py": Path(semantic.__file__),
        "extensions/embed_campaign.py": Path(__file__),
    }.items():
        if sources.get(name) != hashlib.sha256(source.read_bytes()).hexdigest():
            raise ValueError(f"executor source changed or not pinned: {name}")
    frozen_input = preflight["frozen_input"]
    if (
        "path" in frozen_input
        and hashlib.sha256(Path(frozen_input["path"]).read_bytes()).hexdigest()
        != frozen_input["file_sha256"]
    ):
        raise ValueError("frozen configuration changed after preflight")
    if output_path.exists():
        raise FileExistsError(f"refusing to replace semantic artifact: {output_path}")
    texts_path = Path(texts_path)
    texts_bytes = texts_path.read_bytes()
    if (
        hashlib.sha256(texts_bytes).hexdigest()
        != preflight["text_input"]["file_sha256"]
    ):
        raise ValueError("expanded text inputs changed after preflight")
    texts = json.loads(texts_bytes)
    model = entry["model"]
    current_runtime = semantic._runtime_identity(model)
    if current_runtime != entry["identity"]["runtime"]:
        raise ValueError("runtime/model registry changed after preflight")
    snapshot_path = Path(entry["resolved_model"]["snapshot_path"])
    expected_artifact = entry["resolved_model"]["artifact"]
    original_loader = semantic._load_encoder
    loaded_artifact: dict[str, Any] = {}
    run_id = str(uuid.uuid4())
    ledger_path = output_path.with_suffix(".batches.jsonl")

    def offline_loader(model_name: str):
        if model_name != model:
            raise ValueError("offline loader received an unplanned encoder")
        from fastembed import TextEmbedding

        encoder = TextEmbedding(
            model_name=model_name,
            threads=1,
            cuda=False,
            local_files_only=True,
            specific_model_path=str(snapshot_path),
        )
        artifact = _resolved_loaded_artifact(encoder, current_runtime)
        if artifact != expected_artifact:
            raise ValueError("loaded weights/tokenizer differ from preflight snapshot")
        loaded_artifact["value"] = artifact
        return BatchLedgerEncoder(encoder, ledger_path, run_id, model)

    old_environment = {
        key: os.environ.get(key) for key in ("HF_HUB_OFFLINE", "FASTEMBED_CACHE_PATH")
    }
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["FASTEMBED_CACHE_PATH"] = str(Path.home() / ".cache" / "fastembed")
    semantic._load_encoder = offline_loader
    _append_ledger(
        ledger_path,
        {
            "kind": "run_start",
            "run_id": run_id,
            "model": model,
            "cache_counts": entry["cache_counts"],
            "preflight_text_sha256": preflight["text_input"]["file_sha256"],
            "note": (
                "Costs before this durable ledger existed are "
                "unmeasured; cached vectors remain verified."
            ),
        },
    )
    started = time.perf_counter()
    try:
        result = semantic.embed_texts(
            texts,
            Path(entry["cache_dir"]),
            "fastembed",
            model,
            batch_size=_BATCH_SIZE,
            normalize=True,
            model_revision=None,
        )
    finally:
        semantic._load_encoder = original_loader
        for key, value in old_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    adapter_wall_ms = (time.perf_counter() - started) * 1000

    if result["metadata"]["identity"] != entry["identity"]:
        raise ValueError("vector cache identity changed during expansion")
    if set(result["vectors"]) != set(texts):
        raise ValueError(
            "expanded artifact does not have exactly the required vector keys"
        )
    if set(result["metadata"]["input_map"]) != set(texts):
        raise ValueError("expanded input metadata does not cover every exact text")
    if result["metadata"]["cache_hits"] != entry["cache_counts"]["new_texts_cached"]:
        raise ValueError("expanded cache hits differ from preflight count")
    if result["metadata"]["cache_misses"] != entry["cache_counts"]["new_texts_missing"]:
        raise ValueError("expanded cache misses differ from preflight count")
    if loaded_artifact and loaded_artifact["value"] != expected_artifact:
        raise ValueError("loaded snapshot metadata differs from preflight")
    result["metadata"]["expanded_wave_preflight"] = {
        "text_input_sha256": preflight["text_input"]["file_sha256"],
        "frozen_input_sha256": preflight["frozen_input"]["file_sha256"],
        "exact_old_vector_cache_hits": entry["cache_counts"].get(
            "original_exact_overlap", entry["cache_counts"]["new_texts_cached"]
        ),
        "resumed_expanded_vectors_verified": entry["cache_counts"].get(
            "resumed_expanded_vectors_verified", 0
        ),
        "new_exact_inputs_embedded": entry["cache_counts"]["new_texts_missing"],
        "old_unused_texts": entry["cache_counts"]["old_texts_retired"],
        "local_files_only": True,
        "resolved_model_artifact": expected_artifact,
    }
    result["ledger"]["api_cost_usd"] = 0.0
    result["ledger"]["hardware_cost_usd"] = None
    result["ledger"]["execution_policy"] = (
        "local_files_only; verified specific_model_path; "
        "HF_HUB_OFFLINE=1; CPU threads=1"
    )
    result["ledger"]["total_adapter_wall_ms"] = adapter_wall_ms
    result["ledger"]["durable_batch_ledger"] = str(ledger_path)
    result["ledger"]["run_id"] = run_id
    result["ledger"]["prior_interrupted_cost"] = (
        "unmeasured; verified resumed vectors are counted separately"
    )
    started_write = time.perf_counter()
    _atomic_json(output_path, result)
    result["ledger"]["artifact_write_wall_ms"] = (
        time.perf_counter() - started_write
    ) * 1000
    result["ledger"]["total_wall_including_artifact_write_ms"] = (
        adapter_wall_ms + result["ledger"]["artifact_write_wall_ms"]
    )
    _atomic_json(output_path, result)
    _append_ledger(
        ledger_path,
        {
            "kind": "run_complete",
            "run_id": run_id,
            "model": model,
            "artifact_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        },
    )
    return result


def _resolved_loaded_artifact(
    encoder: Any, runtime: dict[str, Any]
) -> dict[str, Any] | None:
    """Hash the model snapshot that the offline FastEmbed loader actually opened."""
    underlying = getattr(encoder, "model", None)
    model_dir_value = getattr(underlying, "_model_dir", None)
    if model_dir_value is None:
        return None
    model_dir = Path(model_dir_value).resolve()
    if not model_dir.is_dir():
        return None
    revision = model_dir.name if model_dir.parent.name == "snapshots" else None
    registry = runtime["model_registry"]
    file_names = {
        registry["model_file"],
        "config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        *registry.get("additional_files", []),
    }
    files: dict[str, dict[str, Any]] = {}
    for relative in sorted(file_names):
        path = model_dir / relative
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        files[relative] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    return {
        "upstream_repo": registry.get("sources", {}).get("hf"),
        "resolved_snapshot_revision": revision,
        "model_file": registry["model_file"],
        "files": files,
        "tokenizer_config": _tokenizer_config_snapshot(model_dir),
    }


def _tokenizer_config_snapshot(model_dir: Path) -> dict[str, Any]:
    """Return the tokenizer limits and directions used by the previous artifact."""
    path = model_dir / "tokenizer_config.json"
    if not path.is_file():
        return {}
    config = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: config[key]
        for key in ("model_max_length", "max_length", "truncation_side", "padding_side")
        if key in config
    }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(value, temporary, ensure_ascii=False, allow_nan=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument(
        "--texts",
        type=Path,
        default=Path(".generated/product-retrieval-expanded-input/texts-v1.json"),
    )
    preflight_parser.add_argument(
        "--frozen",
        type=Path,
        default=Path(".generated/product-retrieval-expanded-v1/frozen.json"),
    )
    preflight_parser.add_argument(
        "--old-texts",
        type=Path,
        default=Path(".generated/product-retrieval-input/texts.json"),
    )
    preflight_parser.add_argument(
        "--old-artifacts", type=Path, default=Path(".generated/product-retrieval-input")
    )
    preflight_parser.add_argument(
        "--model-cache", type=Path, default=Path.home() / ".cache" / "fastembed"
    )
    preflight_parser.add_argument(
        "--output",
        type=Path,
        default=Path(".generated/product-retrieval-expanded-input/preflight-v1.json"),
    )

    embed_parser = subparsers.add_parser("embed")
    embed_parser.add_argument(
        "--preflight",
        type=Path,
        default=Path(".generated/product-retrieval-expanded-input/preflight-v1.json"),
    )
    embed_parser.add_argument(
        "--texts",
        type=Path,
        default=Path(".generated/product-retrieval-expanded-input/texts-v1.json"),
    )
    embed_parser.add_argument("--slug", choices=sorted(_MODELS), required=True)
    embed_parser.add_argument("--output", type=Path)

    args = parser.parse_args()
    if args.command == "preflight":
        preflight = build_model_preflight(
            args.texts,
            args.frozen,
            args.old_texts,
            args.old_artifacts,
            args.model_cache,
        )
        _atomic_json(args.output, preflight)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "new_texts": preflight["text_input"]["count"],
                    "models": [
                        {"slug": item["slug"], **item["cache_counts"]}
                        for item in preflight["models"]
                    ],
                    "inference_calls": 0,
                },
                sort_keys=True,
            )
        )
        return
    preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
    output_path = (
        args.output
        or Path(".generated/product-retrieval-expanded-input") / f"{args.slug}-v1.json"
    )
    result = execute_preflighted_model(preflight, args.slug, args.texts, output_path)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "vectors": len(result["vectors"]),
                "dimension": result["metadata"]["dimension"],
                "ledger": result["ledger"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
