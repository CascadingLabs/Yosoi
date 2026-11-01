"""Cached local semantic embeddings for product retrieval experiments.

This experiment adapter uses FastEmbed's CPU ONNX models. It fails clearly when
the selected backend is unavailable; it never substitutes lexical similarity.
The vector cache is keyed by exact UTF-8 input and the full declared model and
runtime identity so that results from different encoders cannot be mixed.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import tempfile
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

_CACHE_SCHEMA = 1
_FASTEMBED_BACKEND = "fastembed"


class EmbeddingBackendUnavailable(RuntimeError):
    """Raised when the requested semantic embedding backend cannot run."""


class EmbeddingCacheError(RuntimeError):
    """Raised when a cached vector is malformed or belongs to another input."""


def embed_texts(
    texts: list[str],
    cache_dir: Path,
    backend: str,
    model: str,
    *,
    batch_size: int = 32,
    normalize: bool = True,
    model_revision: str | None = None,
) -> dict[str, Any]:
    """Embed exact input strings with a local model and a persistent cache.

    Args:
        texts: Texts to encode. Repeated exact strings share one embedding.
        cache_dir: Directory for this experiment's vector cache.
        backend: Must be ``fastembed``; unsupported backends raise an error.
        model: A model name listed by ``fastembed.TextEmbedding``.
        batch_size: Maximum number of cache misses passed to each embed call.
        normalize: L2-normalize vectors before returning and caching them.
        model_revision: Optional immutable upstream model revision for identity.

    Returns:
        A mapping with ``vectors`` keyed by the exact original strings,
        ``metadata`` describing the model and cache behavior, and a ``ledger``
        separating model setup from embedding CPU time, calls, and token counts.

    Raises:
        TypeError: If inputs are not strings or ``cache_dir`` is not a Path.
        ValueError: If the backend, model, or batch size is invalid.
        EmbeddingBackendUnavailable: If FastEmbed or ONNX Runtime is missing.
        EmbeddingCacheError: If an existing cache entry fails integrity checks.
    """
    if backend != _FASTEMBED_BACKEND:
        raise ValueError(
            f"Unsupported embedding backend {backend!r}; expected 'fastembed'."
        )
    if not isinstance(cache_dir, Path):
        raise TypeError("cache_dir must be a pathlib.Path")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty model name")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if any(not isinstance(text, str) for text in texts):
        raise TypeError("texts must contain only strings")

    runtime = _runtime_identity(model)
    identity = {
        "backend": backend,
        "model": model,
        "model_revision": model_revision,
        "runtime": runtime,
        "configuration": {
            "batch_size": batch_size,
            "normalize": normalize,
            "onnx_intra_op_threads": 1,
            "onnx_inter_op_threads": 1,
            "parallel_workers": 1,
        },
    }
    identity_key = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
    entries_dir = cache_dir / "vectors" / identity_key
    unique_texts = list(dict.fromkeys(texts))
    vectors: dict[str, list[float]] = {}
    input_map: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for text in unique_texts:
        entry = _read_cache_entry(entries_dir, text, identity, runtime.get("dimension"))
        if entry is None:
            missing.append(text)
        else:
            vectors[text], input_map[text] = entry

    setup_wall_ms = 0.0
    setup_cpu_ms = 0.0
    model_cache_bytes_added: int | None = 0
    batch_ledger: list[dict[str, Any]] = []
    inference_wall_ms = 0.0
    inference_cpu_ms = 0.0
    token_counting_wall_ms = 0.0
    input_tokens: int | None = 0

    if missing:
        model_cache = _model_cache_path()
        before_bytes = _tree_bytes(model_cache) if model_cache is not None else None
        setup_wall_start = time.perf_counter()
        setup_cpu_start = time.process_time()
        encoder = _load_encoder(model)
        setup_wall_ms = (time.perf_counter() - setup_wall_start) * 1000
        setup_cpu_ms = (time.process_time() - setup_cpu_start) * 1000
        after_bytes = _tree_bytes(model_cache) if model_cache is not None else None
        if before_bytes is None or after_bytes is None:
            model_cache_bytes_added = None
        else:
            model_cache_bytes_added = max(0, after_bytes - before_bytes)

        prepared_inputs, prepared_records = _prepare_inputs(encoder, missing)
        for start in range(0, len(missing), batch_size):
            batch = prepared_inputs[start : start + batch_size]
            original_batch = missing[start : start + batch_size]
            record_batch = prepared_records[start : start + batch_size]
            token_count, token_wall_ms = _count_tokens(encoder, batch)
            token_counting_wall_ms += token_wall_ms
            if token_count is None:
                input_tokens = None
            elif input_tokens is not None:
                input_tokens += token_count

            wall_start = time.perf_counter()
            cpu_start = time.process_time()
            raw_vectors = list(
                encoder.embed(batch, batch_size=batch_size, parallel=None)
            )
            wall_ms = (time.perf_counter() - wall_start) * 1000
            cpu_ms = (time.process_time() - cpu_start) * 1000
            inference_wall_ms += wall_ms
            inference_cpu_ms += cpu_ms
            if len(raw_vectors) != len(batch):
                raise RuntimeError(
                    "FastEmbed returned a different number of vectors than inputs"
                )

            batch_tokens = token_count
            batch_ledger.append(
                {
                    "input_count": len(batch),
                    "input_tokens": batch_tokens,
                    "wall_ms": wall_ms,
                    "cpu_ms": cpu_ms,
                }
            )
            for text, prepared_text, input_record, raw_vector in zip(
                original_batch, batch, record_batch, raw_vectors, strict=True
            ):
                vector = _validated_vector(
                    raw_vector,
                    expected_dimension=runtime.get("dimension"),
                    normalize=normalize,
                )
                _write_cache_entry(
                    entries_dir, text, vector, identity, prepared_text, input_record
                )
                vectors[text] = vector
                input_map[text] = input_record

    ordered_vectors = {text: vectors[text] for text in texts}
    cache_hits = len(unique_texts) - len(missing)
    metadata = {
        "cache_schema": _CACHE_SCHEMA,
        "identity": identity,
        "identity_sha256": identity_key,
        "dimension": runtime.get("dimension"),
        "input_count": len(texts),
        "unique_input_count": len(unique_texts),
        "duplicate_input_count": len(texts) - len(unique_texts),
        "cache_hits": cache_hits,
        "cache_misses": len(missing),
        "input_map": {text: input_map[text] for text in unique_texts},
    }
    ledger = {
        "model_setup_wall_ms": setup_wall_ms,
        "model_setup_cpu_ms": setup_cpu_ms,
        "model_cache_bytes_added": model_cache_bytes_added,
        "inference_wall_ms": inference_wall_ms,
        "inference_cpu_ms": inference_cpu_ms,
        "token_counting_wall_ms": token_counting_wall_ms,
        "logical_embedding_calls": len(batch_ledger),
        "input_tokens": input_tokens,
        "batches": batch_ledger,
        "api_cost_usd": 0.0,
        "hardware_cost_usd": None,
        "cost_note": (
            "Local CPU inference has no API charge; hardware cost is unmeasured."
        ),
    }
    return {"vectors": ordered_vectors, "metadata": metadata, "ledger": ledger}


def _runtime_identity(model: str) -> dict[str, Any]:
    """Return stable package, runtime, and model-registry identity fields."""
    _configure_cpu_thread_limits()
    try:
        import onnxruntime
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise EmbeddingBackendUnavailable(
            "The fastembed backend is unavailable. Use the authorized UV command "
            "with Python 3.12 and the fastembed package."
        ) from exc

    description: dict[str, Any] | None = None
    for item in TextEmbedding.list_supported_models():
        if item.get("model", "").casefold() == model.casefold():
            description = {
                key: item.get(key)
                for key in ("model", "sources", "model_file", "dim", "additional_files")
            }
            break
    if description is None:
        raise ValueError(f"FastEmbed does not support model {model!r}")
    return {
        "fastembed_version": importlib.metadata.version("fastembed"),
        "onnxruntime_version": onnxruntime.__version__,
        "model_registry": description,
        "dimension": description.get("dim"),
    }


def _load_encoder(model: str) -> Any:
    """Load one FastEmbed model with single-thread CPU inference settings."""
    _configure_cpu_thread_limits()
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise EmbeddingBackendUnavailable(
            "The fastembed backend is unavailable. Use the authorized UV command "
            "with Python 3.12 and the fastembed package."
        ) from exc
    return TextEmbedding(model_name=model, threads=1, cuda=False)


def _configure_cpu_thread_limits() -> None:
    """Limit ONNX Runtime and tokenizer work before their runtimes are imported."""
    os.environ["ORT_INTRA_OP_NUM_THREADS"] = "1"
    os.environ["ORT_INTER_OP_NUM_THREADS"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"


def _prepare_inputs(
    encoder: Any, texts: Sequence[str]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Make model token truncation explicit and retain hashes for both texts."""
    model = getattr(encoder, "model", None)
    tokenizer = getattr(model, "tokenizer", None)
    if tokenizer is None:
        ensure_tokenizer = getattr(model, "_ensure_tokenizer", None)
        if not callable(ensure_tokenizer):
            raise EmbeddingBackendUnavailable(
                "FastEmbed does not expose the tokenizer needed to record truncation."
            )
        ensure_tokenizer()
        tokenizer = getattr(model, "tokenizer", None)
    if tokenizer is None:
        raise EmbeddingBackendUnavailable("FastEmbed did not initialize its tokenizer.")

    truncation = getattr(tokenizer, "truncation", None) or {}
    truncation_limit = truncation.get("max_length")
    prepared_texts: list[str] = []
    records: list[dict[str, Any]] = []
    for text in texts:
        encoding = tokenizer.encode(text)
        offsets = getattr(encoding, "offsets", [])
        final_offset = max(
            (end for start, end in offsets if end > start), default=len(text)
        )
        truncated = bool(
            truncation_limit
            and len(encoding.ids) >= truncation_limit
            and final_offset < len(text.rstrip())
        )
        prepared_text = text[:final_offset] if truncated else text
        if truncated and tokenizer.encode(prepared_text).ids != encoding.ids:
            raise RuntimeError(
                "Could not reproduce FastEmbed's truncated token "
                "sequence from its text prefix"
            )
        prepared_texts.append(prepared_text)
        token_ids = [int(token_id) for token_id in encoding.ids]
        records.append(
            {
                "original_sha256": _sha256_text(text),
                "embedding_input": prepared_text,
                "embedding_input_sha256": _sha256_text(prepared_text),
                "token_ids_sha256": _sha256_json(token_ids),
                "token_count": len(token_ids),
                "truncation_limit_tokens": truncation_limit,
                "truncated": truncated,
            }
        )
    return prepared_texts, records


def _count_tokens(encoder: Any, texts: Sequence[str]) -> tuple[int | None, float]:
    """Count encoded input tokens when FastEmbed exposes its tokenizer counter."""
    counter = getattr(encoder, "token_count", None)
    if not callable(counter):
        return None, 0.0
    started = time.perf_counter()
    try:
        count = int(counter(texts))
    except (AttributeError, NotImplementedError):
        return None, (time.perf_counter() - started) * 1000
    return count, (time.perf_counter() - started) * 1000


def _validated_vector(
    values: Iterable[Any], *, expected_dimension: int | None, normalize: bool
) -> list[float]:
    """Validate a model vector and optionally apply deterministic L2 normalization."""
    vector = [float(value) for value in values]
    if not vector or any(not math.isfinite(value) for value in vector):
        raise RuntimeError("FastEmbed returned an empty or non-finite vector")
    if expected_dimension is not None and len(vector) != expected_dimension:
        raise RuntimeError(
            f"FastEmbed returned dimension {len(vector)}, expected {expected_dimension}"
        )
    if normalize:
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            raise RuntimeError(
                "FastEmbed returned a zero vector that cannot be normalized"
            )
        vector = [value / norm for value in vector]
    return vector


def _read_cache_entry(
    entries_dir: Path,
    text: str,
    identity: dict[str, Any],
    expected_dimension: int | None,
) -> tuple[list[float], dict[str, Any]] | None:
    """Load one cache record, returning None only when the record is absent."""
    path = entries_dir / f"{hashlib.sha256(text.encode('utf-8')).hexdigest()}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EmbeddingCacheError(
            f"Could not read embedding cache entry {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise EmbeddingCacheError(f"Malformed embedding cache record in {path}")
    if payload.get("cache_schema") != _CACHE_SCHEMA:
        raise EmbeddingCacheError(f"Unsupported embedding cache schema in {path}")
    if payload.get("text") != text or payload.get("identity") != identity:
        raise EmbeddingCacheError(f"Embedding cache identity mismatch in {path}")
    try:
        vector = _validated_vector(
            payload["vector"], expected_dimension=expected_dimension, normalize=False
        )
        input_record = payload["input_record"]
        if not isinstance(input_record, dict):
            raise TypeError("input_record must be a mapping")
        if input_record.get("original_sha256") != _sha256_text(text):
            raise ValueError("cached original text digest does not match")
        if input_record.get("embedding_input") != payload.get("embedding_input"):
            raise ValueError("cached prepared input does not match its record")
        return vector, input_record
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise EmbeddingCacheError(f"Malformed embedding vector in {path}") from exc


def _write_cache_entry(
    entries_dir: Path,
    text: str,
    vector: list[float],
    identity: dict[str, Any],
    embedding_input: str,
    input_record: dict[str, Any],
) -> None:
    """Atomically persist one exact-text vector and its model identity."""
    entries_dir.mkdir(parents=True, exist_ok=True)
    target = entries_dir / f"{hashlib.sha256(text.encode('utf-8')).hexdigest()}.json"
    payload = {
        "cache_schema": _CACHE_SCHEMA,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "identity": identity,
        "vector": vector,
        "embedding_input": embedding_input,
        "input_record": input_record,
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


def _canonical_json(value: Any) -> str:
    """Serialize an identity deterministically for its cache namespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    """Hash exact UTF-8 text without normalizing whitespace or Unicode."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    """Hash deterministic JSON data such as the actual token ID sequence."""
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _model_cache_path() -> Path | None:
    """Return FastEmbed's configured model cache path when explicitly set."""
    configured = os.environ.get("FASTEMBED_CACHE_PATH")
    return Path(configured).expanduser() if configured else None


def _tree_bytes(path: Path) -> int:
    """Return bytes currently stored under a model cache directory."""
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
