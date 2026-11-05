"""Bounded cached cross-encoder reranking for retrieval experiment pools."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from methods import REPRESENTATIONS, representation_text

_CACHE_SCHEMA = 1
_MAX_POOL_SIZE = 50
_SUPPORTED_MODELS = {
    "Xenova/ms-marco-MiniLM-L-6-v2",
    "Xenova/ms-marco-MiniLM-L-12-v2",
}
_INPUT_FILE_NAMES = (
    "config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)


class RerankBackendUnavailable(RuntimeError):
    """Raised when the requested local FastEmbed reranker cannot run."""


class RerankCacheError(RuntimeError):
    """Raised when a cached pair score is malformed or belongs to other inputs."""


def rerank_pairs(
    query: str,
    candidates: list[dict[str, Any]],
    pool_indices: list[int],
    cache_dir: Path,
    model: str,
    representation: str = "context",
    *,
    batch_size: int = 16,
) -> dict[str, Any]:
    """Rerank only the supplied bounded candidate pool with a local cross-encoder.

    Args:
        query: Exact field intent text to pair with each candidate.
        candidates: Candidate mappings in their original corpus order.
        pool_indices: Unique original candidate indices selected by a separate
            retrieval stage. At most 50 indices are accepted; candidates outside
            this pool are not inspected or scored.
        cache_dir: Directory for exact query/document score cache entries.
        model: Supported FastEmbed cross-encoder model name. This adapter supports
            the registered MiniLM-L-6 and MiniLM-L-12 rerankers.
        representation: Representation passed to
            ``methods.representation_text`` for every pooled candidate.
        batch_size: Number of uncached pairs sent to each local inference call.

    Returns:
        A mapping containing raw ``scores`` keyed by original candidate index,
        a stable descending ``ranked`` list, model/pool/input metadata, and a
        ledger with setup, cache, token, inference, latency, and cost fields.
        Scores are raw cross-encoder logits, not calibrated probabilities.

    Raises:
        TypeError: If an argument has the wrong type.
        ValueError: If the query, pool, model, or representation is invalid.
        RerankBackendUnavailable: If FastEmbed or ONNX Runtime is missing.
        RerankCacheError: If a persistent cache entry fails integrity checks.
    """
    adapter_started = time.perf_counter()
    _validate_arguments(
        query, candidates, pool_indices, cache_dir, model, representation, batch_size
    )
    runtime = _runtime_identity(model)
    identity = {
        "backend": "fastembed.TextCrossEncoder",
        "model": model,
        "runtime": runtime,
        "configuration": {
            "representation": representation,
            "batch_size": batch_size,
            "onnx_intra_op_threads": 1,
            "onnx_inter_op_threads": 1,
            "parallel_workers": 1,
            "score_type": "raw_cross_encoder_logit",
        },
    }
    cache_identity = {key: identity[key] for key in ("backend", "model", "runtime")}
    cache_key = _sha256_json(cache_identity)
    entries_dir = cache_dir / "pairs" / cache_key

    selected: list[dict[str, Any]] = []
    unique_pairs: list[tuple[str, str]] = []
    input_records: dict[int, dict[str, Any]] = {}
    seen_pairs: dict[str, tuple[str, str]] = {}
    for index in pool_indices:
        candidate = candidates[index]
        candidate_id = candidate.get("id")
        if not isinstance(candidate_id, (str, int)) or isinstance(candidate_id, bool):
            raise ValueError(f"candidate at index {index} needs a string or integer id")
        document_text = representation_text(candidate, representation)
        pair = (query, document_text)
        pair_key = _pair_key(*pair)
        selected.append(
            {
                "pool_index": index,
                "candidate_id": candidate_id,
                "node_id": candidate.get("node_id"),
                "query": query,
                "representation": representation,
                "representation_text": document_text,
                "pair_sha256": pair_key,
            }
        )
        input_records[index] = selected[-1]
        if pair_key not in seen_pairs:
            seen_pairs[pair_key] = pair
            unique_pairs.append(pair)

    cache_read_start = time.perf_counter()
    scores_by_pair: dict[str, float] = {}
    pair_telemetry: dict[str, dict[str, Any]] = {}
    resolved_artifact: dict[str, Any] | None = None
    missing: list[tuple[str, str]] = []
    for pair in unique_pairs:
        pair_key = _pair_key(*pair)
        entry = _read_cache_entry(entries_dir, pair_key, pair, cache_identity)
        if entry is None:
            missing.append(pair)
        else:
            score, telemetry, artifact = entry
            scores_by_pair[pair_key] = score
            pair_telemetry[pair_key] = telemetry
            if artifact is not None:
                if resolved_artifact is not None and artifact != resolved_artifact:
                    raise RerankCacheError(
                        "resolved model artifact differs across cached pairs"
                    )
                resolved_artifact = artifact
    cache_read_wall_ms = (time.perf_counter() - cache_read_start) * 1000

    setup_wall_ms = 0.0
    setup_cpu_ms = 0.0
    model_cache_bytes_added: int | None = 0
    inference_wall_ms = 0.0
    inference_cpu_ms = 0.0
    token_counting_wall_ms = 0.0
    inference_calls = 0
    input_tokens = 0
    truncated_pairs = 0
    batch_ledger: list[dict[str, Any]] = []
    cache_write_wall_ms = 0.0

    if missing:
        model_cache = _model_cache_path()
        before_bytes = _tree_bytes(model_cache) if model_cache is not None else None
        setup_started = time.perf_counter()
        setup_cpu_started = time.process_time()
        encoder = _load_encoder(model)
        setup_wall_ms = (time.perf_counter() - setup_started) * 1000
        setup_cpu_ms = (time.process_time() - setup_cpu_started) * 1000
        after_bytes = _tree_bytes(model_cache) if model_cache is not None else None
        if before_bytes is None or after_bytes is None:
            model_cache_bytes_added = None
        else:
            model_cache_bytes_added = max(0, after_bytes - before_bytes)
        resolved_artifact = _resolved_model_artifact(encoder, runtime)

        prepared_records, token_counting_wall_ms = _pair_telemetry(encoder, missing)
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            records = prepared_records[start : start + batch_size]
            batch_token_count = sum(record["model_input_tokens"] for record in records)
            input_tokens += batch_token_count
            inference_started = time.perf_counter()
            inference_cpu_started = time.process_time()
            raw_scores = list(
                encoder.rerank_pairs(batch, batch_size=batch_size, parallel=None)
            )
            wall_ms = (time.perf_counter() - inference_started) * 1000
            cpu_ms = (time.process_time() - inference_cpu_started) * 1000
            inference_wall_ms += wall_ms
            inference_cpu_ms += cpu_ms
            inference_calls += 1
            if len(raw_scores) != len(batch):
                raise RuntimeError(
                    "FastEmbed returned a different number of scores than input pairs"
                )
            batch_ledger.append(
                {
                    "pair_count": len(batch),
                    "input_tokens": batch_token_count,
                    "wall_ms": wall_ms,
                    "cpu_ms": cpu_ms,
                }
            )
            write_started = time.perf_counter()
            for pair, record, raw_score in zip(batch, records, raw_scores, strict=True):
                score = float(raw_score)
                if not math.isfinite(score):
                    raise RuntimeError("FastEmbed returned a non-finite reranker score")
                pair_key = _pair_key(*pair)
                _write_cache_entry(
                    entries_dir,
                    pair_key,
                    pair,
                    score,
                    record,
                    cache_identity,
                    resolved_artifact,
                )
                scores_by_pair[pair_key] = score
                pair_telemetry[pair_key] = record
                truncated_pairs += int(record["truncated"])
            cache_write_wall_ms += (time.perf_counter() - write_started) * 1000

    for pair in unique_pairs:
        pair_key = _pair_key(*pair)
        record = pair_telemetry.get(pair_key)
        if record is not None and pair_key not in {_pair_key(*p) for p in missing}:
            input_tokens += int(record["model_input_tokens"])
            truncated_pairs += int(record["truncated"])

    pool_scores: dict[int, float] = {}
    for record in selected:
        pool_scores[record["pool_index"]] = scores_by_pair[record["pair_sha256"]]
    ranked = [
        {
            **record,
            "raw_score": pool_scores[record["pool_index"]],
        }
        for record in selected
    ]
    pool_order = {index: position for position, index in enumerate(pool_indices)}
    ranked.sort(key=lambda item: (-item["raw_score"], pool_order[item["pool_index"]]))
    for rank, record in enumerate(ranked, start=1):
        record["rank"] = rank

    identity_with_pool = {
        **identity,
        "pool_indices": list(pool_indices),
        "pool_candidate_ids": [record["candidate_id"] for record in selected],
        "input_pairs_sha256": _sha256_json(
            [[record["query"], record["representation_text"]] for record in selected]
        ),
    }
    metadata = {
        "cache_schema": _CACHE_SCHEMA,
        "identity": identity_with_pool,
        "run_identity_sha256": _sha256_json(identity_with_pool),
        "cache_identity_sha256": cache_key,
        "model_identity": runtime,
        "resolved_model_artifact": resolved_artifact,
        "representation": representation,
        "query": query,
        "pool_indices": list(pool_indices),
        "pool_count": len(pool_indices),
        "candidate_count": len(candidates),
        "pool_inputs": selected,
        "pair_telemetry": pair_telemetry,
        "scores_are_calibrated_confidence": False,
        "pool_was_selected_outside_reranker": True,
    }
    ledger = {
        "cache_hits": len(unique_pairs) - len(missing),
        "cache_misses": len(missing),
        "cache_read_wall_ms": cache_read_wall_ms,
        "cache_write_wall_ms": cache_write_wall_ms,
        "model_setup_wall_ms": setup_wall_ms,
        "model_setup_cpu_ms": setup_cpu_ms,
        "model_cache_bytes_added": model_cache_bytes_added,
        "inference_calls": inference_calls,
        "inference_wall_ms": inference_wall_ms,
        "inference_cpu_ms": inference_cpu_ms,
        "token_counting_wall_ms": token_counting_wall_ms,
        "input_pairs": len(unique_pairs),
        "input_tokens": input_tokens,
        "truncated_pairs": truncated_pairs,
        "batches": batch_ledger,
        "api_cost_usd": 0.0,
        "hardware_cost_usd": None,
        "cost_note": (
            "Local CPU inference has no API charge; hardware cost is unmeasured."
        ),
        "model_cache_bytes_added_note": (
            "Recursive file-size delta under FastEmbed cache; snapshot links may count "
            "underlying blobs more than once and are not network bytes."
        ),
    }
    ledger["adapter_wall_ms"] = (time.perf_counter() - adapter_started) * 1000
    return {
        "scores": pool_scores,
        "ranked": ranked,
        "metadata": metadata,
        "ledger": ledger,
    }


def _validate_arguments(
    query: str,
    candidates: list[dict[str, Any]],
    pool_indices: list[int],
    cache_dir: Path,
    model: str,
    representation: str,
    batch_size: int,
) -> None:
    """Reject malformed or unbounded requests before reading the pool."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty field intent string")
    if not isinstance(candidates, list) or any(
        not isinstance(candidate, dict) for candidate in candidates
    ):
        raise TypeError("candidates must be a list of candidate dictionaries")
    if not isinstance(pool_indices, list):
        raise TypeError("pool_indices must be a list of original candidate indices")
    if len(pool_indices) > _MAX_POOL_SIZE:
        raise ValueError(f"pool_indices is bounded to {_MAX_POOL_SIZE} candidates")
    if any(type(index) is not int for index in pool_indices):
        raise TypeError("pool_indices must contain integers")
    if len(set(pool_indices)) != len(pool_indices):
        raise ValueError("pool_indices must not contain duplicates")
    if any(index < 0 or index >= len(candidates) for index in pool_indices):
        raise ValueError("pool_indices contains an out-of-range candidate index")
    if not isinstance(cache_dir, Path):
        raise TypeError("cache_dir must be a pathlib.Path")
    if not isinstance(model, str):
        raise TypeError("model must be a registered model name string")
    if representation not in REPRESENTATIONS:
        raise ValueError(f"unknown representation: {representation}")
    if model not in _SUPPORTED_MODELS:
        raise ValueError(
            f"Unsupported reranker {model!r}; supported models are "
            f"{sorted(_SUPPORTED_MODELS)}"
        )
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")


def _runtime_identity(model: str) -> dict[str, Any]:
    """Describe the supported model and runtime without initializing weights."""
    _configure_cpu_thread_limits()
    try:
        import onnxruntime
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError as exc:
        raise RerankBackendUnavailable(
            "FastEmbed TextCrossEncoder and ONNX Runtime are required; use the "
            "authorized UV-managed Python 3.12 runtime."
        ) from exc

    registered: dict[str, Any] | None = None
    for item in TextCrossEncoder.list_supported_models():
        if item.get("model", "").casefold() == model.casefold():
            registered = {
                key: item.get(key)
                for key in (
                    "model",
                    "sources",
                    "model_file",
                    "additional_files",
                    "size_in_GB",
                    "license",
                    "description",
                )
            }
            break
    if registered is None:
        raise ValueError(f"FastEmbed does not support reranker {model!r}")
    return {
        "fastembed_version": importlib.metadata.version("fastembed"),
        "onnxruntime_version": onnxruntime.__version__,
        "model_registry": registered,
    }


def _load_encoder(model: str) -> Any:
    """Load the registered reranker on CPU with one ONNX thread per pool."""
    _configure_cpu_thread_limits()
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError as exc:
        raise RerankBackendUnavailable(
            "FastEmbed TextCrossEncoder is unavailable in this runtime."
        ) from exc
    return TextCrossEncoder(model_name=model, threads=1, cuda=False)


def _configure_cpu_thread_limits() -> None:
    """Set process-wide ONNX and tokenizer thread limits before import/use."""
    os.environ["ORT_INTRA_OP_NUM_THREADS"] = "1"
    os.environ["ORT_INTER_OP_NUM_THREADS"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"


def _pair_telemetry(
    encoder: Any, pairs: Sequence[tuple[str, str]]
) -> tuple[list[dict[str, Any]], float]:
    """Record truncated model token IDs and whether the pair exceeded its limit."""
    tokenizer = getattr(getattr(encoder, "model", None), "tokenizer", None)
    if tokenizer is None:
        model = getattr(encoder, "model", None)
        ensure_tokenizer = getattr(model, "_ensure_tokenizer", None)
        if not callable(ensure_tokenizer):
            raise RerankBackendUnavailable(
                "FastEmbed did not expose its tokenizer for truncation telemetry."
            )
        ensure_tokenizer()
        tokenizer = getattr(model, "tokenizer", None)
    if tokenizer is None:
        raise RerankBackendUnavailable("FastEmbed did not initialize its tokenizer.")

    started = time.perf_counter()
    truncation = getattr(tokenizer, "truncation", None) or {}
    max_length = truncation.get("max_length")
    try:
        from tokenizers import Tokenizer

        untruncated_tokenizer = Tokenizer.from_str(tokenizer.to_str())
        untruncated_tokenizer.no_truncation()
    except (ImportError, AttributeError, ValueError) as exc:
        raise RerankBackendUnavailable(
            "Could not clone FastEmbed's tokenizer to measure pair truncation."
        ) from exc

    records: list[dict[str, Any]] = []
    for query, document in pairs:
        model_encoding = tokenizer.encode(query, document)
        full_encoding = untruncated_tokenizer.encode(query, document)
        model_tokens = [int(token) for token in model_encoding.ids]
        full_token_count = len(full_encoding.ids)
        model_token_count = len(model_tokens)
        records.append(
            {
                "query_sha256": _sha256_text(query),
                "document_sha256": _sha256_text(document),
                "model_input_tokens": model_token_count,
                "untruncated_input_tokens": full_token_count,
                "max_input_tokens": max_length,
                "truncated": full_token_count > model_token_count,
                "model_token_ids_sha256": _sha256_json(model_tokens),
            }
        )
    return records, (time.perf_counter() - started) * 1000


def _resolved_model_artifact(
    encoder: Any, runtime: dict[str, Any]
) -> dict[str, Any] | None:
    """Record the actual model snapshot and hashes for weights and tokenizer files."""
    underlying = getattr(encoder, "model", None)
    model_dir_value = getattr(underlying, "_model_dir", None)
    if model_dir_value is None:
        return None
    model_dir = Path(model_dir_value).resolve()
    if not model_dir.is_dir():
        return None
    revision = model_dir.name if model_dir.parent.name == "snapshots" else None
    registry = runtime["model_registry"]
    wanted = {
        registry["model_file"],
        *_INPUT_FILE_NAMES,
        *registry.get("additional_files", []),
    }
    files: dict[str, dict[str, Any]] = {}
    for relative in sorted(wanted):
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
    }


def _read_cache_entry(
    entries_dir: Path,
    pair_key: str,
    pair: tuple[str, str],
    identity: dict[str, Any],
) -> tuple[float, dict[str, Any], dict[str, Any] | None] | None:
    """Read and verify one cached query/document score."""
    path = entries_dir / f"{pair_key}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RerankCacheError(f"Could not read reranker cache entry {path}") from exc
    if not isinstance(payload, dict) or payload.get("cache_schema") != _CACHE_SCHEMA:
        raise RerankCacheError(f"Malformed reranker cache entry {path}")
    if payload.get("identity") != identity or payload.get("pair") != list(pair):
        raise RerankCacheError(f"Reranker cache identity mismatch in {path}")
    if payload.get("pair_sha256") != pair_key:
        raise RerankCacheError(f"Reranker cache digest mismatch in {path}")
    try:
        score = float(payload["raw_score"])
        telemetry = payload["telemetry"]
        artifact = payload.get("resolved_model_artifact")
        if not math.isfinite(score) or not isinstance(telemetry, dict):
            raise ValueError("invalid score or telemetry")
        return score, telemetry, artifact
    except (KeyError, TypeError, ValueError) as exc:
        raise RerankCacheError(f"Malformed cached score in {path}") from exc


def _write_cache_entry(
    entries_dir: Path,
    pair_key: str,
    pair: tuple[str, str],
    score: float,
    telemetry: dict[str, Any],
    identity: dict[str, Any],
    resolved_artifact: dict[str, Any] | None,
) -> None:
    """Atomically save one raw score and the exact pair/model evidence."""
    entries_dir.mkdir(parents=True, exist_ok=True)
    target = entries_dir / f"{pair_key}.json"
    payload = {
        "cache_schema": _CACHE_SCHEMA,
        "identity": identity,
        "pair": list(pair),
        "pair_sha256": pair_key,
        "raw_score": score,
        "telemetry": telemetry,
        "resolved_model_artifact": resolved_artifact,
    }
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=entries_dir,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, allow_nan=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _pair_key(query: str, document: str) -> str:
    """Hash the exact unnormalized query and candidate text pair."""
    return _sha256_json([query, document])


def _sha256_text(value: str) -> str:
    """Hash exact UTF-8 text without normalizing whitespace or Unicode."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    """Hash JSON-compatible values deterministically."""
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _model_cache_path() -> Path | None:
    """Return FastEmbed's configured model cache path when explicitly set."""
    configured = os.environ.get("FASTEMBED_CACHE_PATH")
    return Path(configured).expanduser() if configured else None


def _tree_bytes(path: Path) -> int:
    """Return the recursive sum of file sizes in a model cache directory."""
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
