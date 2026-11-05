"""Plan and run a bounded cross-encoder retrieval campaign.

Pool construction uses only frozen baseline score arrays and the current
candidate representation. Gold labels are consulted only after all pair scores
are acquired. The executor deduplicates exact query/document pairs across the
full campaign and holds one local CPU model open for each sequential run.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import statistics
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import methods
import rerank
import run_matrix

_FORMAT = "product-retrieval-rerank-campaign-v1"
_MODELS = (
    "Xenova/ms-marco-MiniLM-L-6-v2",
    "Xenova/ms-marco-MiniLM-L-12-v2",
)
_POOL_BUILDERS = {
    "hierarchical_bm25_semantic_query": (
        ("hierarchical_jaccard", "reference"),
        ("bm25", "query"),
        ("semantic_query", "semantic_query"),
    ),
    "char_ngram_semantic_reference": (
        ("lexical_char_ngram_cosine_reference", "reference"),
        ("semantic_reference", "semantic_reference"),
    ),
}
_REPRESENTATION = "context"
_BATCH_SIZE = 16
_DEFAULT_MAX_NEW_PAIRS = 30_000


def load_baseline(
    baseline_dir: Path,
    scoring_cache_dir: Path,
    semantic_artifact: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], str]:
    """Load and verify frozen source/corpus and per-case scalar score caches."""
    baseline_dir = Path(baseline_dir)
    frozen = json.loads((baseline_dir / "frozen.json").read_text(encoding="utf-8"))
    corpus = json.loads((baseline_dir / "corpus.json").read_text(encoding="utf-8"))
    if _sha256_json(corpus) != frozen["corpus_checksum"]:
        raise ValueError("baseline corpus checksum does not match its frozen manifest")

    experiment_root = Path(__file__).resolve().parents[1]
    for name, expected in frozen["implementation"].items():
        source_path = experiment_root / name
        if (
            not source_path.is_file()
            or _sha256_bytes(source_path.read_bytes()) != expected
        ):
            raise ValueError(f"frozen baseline source changed: {name}")

    semantic_metadata = json.loads(Path(semantic_artifact).read_text(encoding="utf-8"))[
        "metadata"
    ]
    semantic_model = semantic_metadata["identity"]["model"]
    if semantic_model != "sentence-transformers/all-MiniLM-L6-v2":
        raise ValueError(
            "pool builders are pinned to the baseline MiniLM semantic scores"
        )
    semantic_digest = _sha256_bytes(Path(semantic_artifact).read_bytes())

    cases = {case["id"]: case for case in corpus["cases"]}
    references = [cases[reference]["candidates"] for reference in corpus["references"]]
    scores_by_case: dict[str, dict[str, Any]] = {}
    missing_cache_files: list[str] = []
    for case in corpus["cases"]:
        identity = _sha256_json(
            {
                "corpus_checksum": frozen["corpus_checksum"],
                "runner_code": frozen["implementation"]["run_matrix.py"],
                "candidate_input": case["candidates"],
                "reference_cases": references,
                "queries": frozen["queries"],
                "methods_code": frozen["implementation"]["methods.py"],
                "repeats": 1,
            }
        )
        cache_path = Path(scoring_cache_dir) / f"{identity}.json.gz"
        if not cache_path.is_file():
            missing_cache_files.append(case["id"])
            continue
        scores_by_case[case["id"]] = json.loads(
            gzip.decompress(cache_path.read_bytes())
        )
    if missing_cache_files:
        raise ValueError(
            f"baseline scalar cache is missing cases: {missing_cache_files[:5]}"
        )

    available_semantic_digests = {
        json.loads(key)[4]
        for score_map in scores_by_case.values()
        for key in score_map
        if json.loads(key)[1] in ("semantic_query", "semantic_reference")
    }
    if semantic_digest not in available_semantic_digests:
        raise ValueError(
            "MiniLM semantic artifact digest does not match baseline score cache keys"
        )
    return frozen, corpus, scores_by_case, semantic_digest


def write_preflight(
    plan_path: Path,
    baseline_dir: Path,
    semantic_artifact: Path,
    output_path: Path,
    model_cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Freeze source, cache, pool, semantic and resolved reranker identities.

    This is read-only with respect to the models: it hashes already cached model
    files but does not instantiate an encoder or run inference.
    """
    plan_path = Path(plan_path)
    baseline_dir = Path(baseline_dir)
    plan = load_campaign_plan(plan_path)
    frozen_bytes = (baseline_dir / "frozen.json").read_bytes()
    frozen = json.loads(frozen_bytes)
    corpus = json.loads((baseline_dir / "corpus.json").read_text(encoding="utf-8"))
    if frozen.get("corpus_checksum") != plan["dataset"]["corpus_checksum"]:
        raise ValueError("preflight corpus does not match the campaign plan")
    if _sha256_json(corpus) != frozen["corpus_checksum"]:
        raise ValueError("baseline corpus checksum does not match its frozen manifest")

    root = Path(__file__).resolve().parents[1]
    for name, expected in frozen["implementation"].items():
        path = root / name
        if not path.is_file() or _sha256_bytes(path.read_bytes()) != expected:
            raise ValueError(f"frozen baseline source changed before inference: {name}")

    semantic_path = Path(semantic_artifact)
    semantic_bytes = semantic_path.read_bytes()
    semantic_digest = _sha256_bytes(semantic_bytes)
    if semantic_digest != plan["dataset"]["semantic_artifact_sha256"]:
        raise ValueError("semantic pool artifact changed after plan generation")
    semantic_metadata = json.loads(semantic_bytes)["metadata"]

    cache_root = Path(scoring_cache_dir_from_plan(plan, baseline_dir))
    cases = {case["id"]: case for case in corpus["cases"]}
    reference_candidates = [
        cases[reference]["candidates"] for reference in corpus["references"]
    ]
    score_cache_provenance: dict[str, dict[str, str]] = {}
    for case in corpus["cases"]:
        identity = _sha256_json(
            {
                "corpus_checksum": frozen["corpus_checksum"],
                "runner_code": frozen["implementation"]["run_matrix.py"],
                "candidate_input": case["candidates"],
                "reference_cases": reference_candidates,
                "queries": frozen["queries"],
                "methods_code": frozen["implementation"]["methods.py"],
                "repeats": 1,
            }
        )
        cache_path = cache_root / f"{identity}.json.gz"
        if not cache_path.is_file():
            raise ValueError(f"missing frozen baseline score cache for {case['id']}")
        score_cache_provenance[case["id"]] = {
            "identity": identity,
            "file_sha256": _sha256_bytes(cache_path.read_bytes()),
        }

    model_cache_dir = model_cache_dir or rerank._model_cache_path()
    if model_cache_dir is None:
        model_cache_dir = Path.home() / ".cache" / "fastembed"
    model_preflight = [
        _preflight_model_artifact(model, model_cache_dir) for model in _MODELS
    ]
    output = {
        "format": "product-retrieval-rerank-preflight-v1",
        "plan_path": str(plan_path),
        "plan_sha256": _sha256_bytes(plan_path.read_bytes()),
        "baseline": {
            "baseline_dir": str(baseline_dir),
            "frozen_manifest_sha256": _sha256_bytes(frozen_bytes),
            "corpus_checksum": frozen["corpus_checksum"],
            "implementation_sha256": frozen["implementation"],
            "queries": frozen["queries"],
            "field_order": frozen["field_order"],
            "reference_groups": frozen["reference_groups"],
            "representation": _REPRESENTATION,
            "scoring_cache_repeats": 1,
            "scoring_cache_identity_by_case": score_cache_provenance,
        },
        "pooling": {
            "builders": list(_POOL_BUILDERS),
            "channels": {
                name: [method for method, _ in channels]
                for name, channels in _POOL_BUILDERS.items()
            },
            "semantic_pool_encoder": semantic_metadata["identity"],
            "semantic_pool_artifact_sha256": semantic_digest,
            "rrf_constant": 60,
            "positive_channel_score_required": True,
            "budgets": plan["plan"]["pool_budgets"],
            "max_candidates_per_reranker_pool": 50,
            "root_candidate_projection": "projection == 'text'",
            "target_labels_used_for_pooling": False,
        },
        "reranker_run": {
            "models": model_preflight,
            "batch_size": _BATCH_SIZE,
            "onnx_intra_op_threads": 1,
            "onnx_inter_op_threads": 1,
            "parallel_workers": 1,
            "score_semantics": "raw cross-encoder logit; no calibration or sigmoid",
            "max_new_unique_pairs_per_model": _DEFAULT_MAX_NEW_PAIRS,
            "planned_unique_pairs_per_model": plan["plan"][
                "unique_exact_pairs_per_model"
            ],
            "expected_inference_calls_per_model": math.ceil(
                plan["plan"]["unique_exact_pairs_per_model"] / _BATCH_SIZE
            ),
            "model_pair_prefix": None,
            "target_labels_passed_to_model": False,
        },
        "claim_boundary": (
            "controlled development corpus and source-derived "
            "mutations; not a fresh-site claim"
        ),
    }
    _atomic_json(Path(output_path), output)
    return output


def scoring_cache_dir_from_plan(plan: dict[str, Any], baseline_dir: Path) -> Path:
    """Resolve the sibling global score-cache directory used by run_matrix."""
    configured = plan.get("dataset", {}).get("scoring_cache_dir")
    return (
        Path(configured) if configured else Path(baseline_dir).parent / "scoring-cache"
    )


def _preflight_model_artifact(model: str, cache_dir: Path) -> dict[str, Any]:
    """Read cached model revision and hashes without loading an inference session."""
    runtime = rerank._runtime_identity(model)
    registry = runtime["model_registry"]
    source = registry.get("sources", {}).get("hf")
    if not source:
        raise ValueError(f"reranker {model} has no registered Hugging Face source")
    repo_dir = cache_dir / f"models--{source.replace('/', '--')}"
    snapshots_dir = repo_dir / "snapshots"
    if not snapshots_dir.is_dir():
        raise ValueError(f"warm model snapshot is missing for {model}")
    ref_path = repo_dir / "refs" / "main"
    revision = (
        ref_path.read_text(encoding="utf-8").strip() if ref_path.is_file() else None
    )
    snapshot = snapshots_dir / revision if revision else None
    if snapshot is None or not snapshot.is_dir():
        snapshots = sorted(path for path in snapshots_dir.iterdir() if path.is_dir())
        if len(snapshots) != 1:
            raise ValueError(
                f"could not uniquely resolve cached model revision for {model}"
            )
        snapshot = snapshots[0]
        revision = snapshot.name
    artifact = rerank._resolved_model_artifact(
        type(
            "CachedEncoder",
            (),
            {"model": type("CachedModel", (), {"_model_dir": snapshot})()},
        )(),
        runtime,
    )
    if artifact is None or not artifact.get("files", {}).get(registry["model_file"]):
        raise ValueError(
            f"cached model weights or tokenizer files are incomplete for {model}"
        )
    return {
        "model": model,
        "runtime": runtime,
        "resolved_model_artifact": artifact,
        "registry_size_in_gb": registry.get("size_in_GB"),
        "tokenizer_max_length": _tokenizer_max_length(snapshot),
    }


def _tokenizer_max_length(snapshot: Path) -> int | None:
    """Read model context limit from its cached tokenizer config, if present."""
    path = snapshot / "tokenizer_config.json"
    if not path.is_file():
        return None
    config = json.loads(path.read_text(encoding="utf-8"))
    value = config.get("model_max_length", config.get("max_length"))
    return value if isinstance(value, int) and value < 1_000_000 else None


def candidate_universe(
    candidates: list[dict[str, Any]], field: str
) -> list[dict[str, Any]]:
    """Match the baseline root projection while preserving its local index order."""
    if field == "root":
        return [
            candidate for candidate in candidates if candidate["projection"] == "text"
        ]
    return candidates


def cached_scores(
    score_map: dict[str, Any],
    field: str,
    method: str,
    group_id: str,
    representation: str,
    semantic_digest: str,
) -> list[float]:
    """Return one baseline vector using run_matrix's exact serialized cache key."""
    metadata = methods.METHOD_METADATA[method]
    effective_group = (
        "query_only" if metadata["reference_aggregation"] == "none" else group_id
    )
    key = json.dumps(
        [
            field,
            method,
            effective_group,
            representation,
            semantic_digest if method.startswith("semantic") else None,
        ]
    )
    stored = score_map.get(key)
    if not isinstance(stored, dict) or not isinstance(stored.get("scores"), list):
        raise ValueError(f"baseline score cache lacks {field}/{method}/{group_id}")
    return [float(value) for value in stored["scores"]]


def build_rrf_pool(
    candidates: list[dict[str, Any]],
    channels: list[tuple[str, list[float]]],
    budget: int,
    *,
    rrf_constant: int = 60,
) -> tuple[list[int], dict[str, float]]:
    """Fuse positive channel ranks by RRF and return deduplicated candidate indices."""
    if budget < 1:
        raise ValueError("pool budget must be positive")
    if any(len(scores) != len(candidates) for _, scores in channels):
        raise ValueError("score vector length does not match candidate projection")
    identities = [candidate["id"] for candidate in candidates]
    if len(set(identities)) != len(identities):
        raise ValueError("candidate universe contains duplicate identities")

    fused: dict[str, float] = defaultdict(float)
    for _, scores in channels:
        if any(not math.isfinite(score) or score < 0 for score in scores):
            raise ValueError("baseline pool channel contains an invalid score")
        order = sorted(
            range(len(candidates)),
            key=lambda index: (-scores[index], candidates[index]["id"]),
        )
        for position, index in enumerate(order, start=1):
            if scores[index] > 0:
                fused[candidates[index]["id"]] += 1.0 / (rrf_constant + position)

    by_id = {candidate["id"]: index for index, candidate in enumerate(candidates)}
    ranked_ids = sorted(fused, key=lambda identity: (-fused[identity], identity))
    return [by_id[identity] for identity in ranked_ids[:budget]], dict(fused)


def build_plan(
    frozen: dict[str, Any],
    corpus: dict[str, Any],
    scores_by_case: dict[str, dict[str, Any]],
    semantic_digest: str,
    *,
    budgets: tuple[int, ...] = (5, 20, 50),
    models: tuple[str, ...] = _MODELS,
) -> dict[str, Any]:
    """Construct all blinded pools and deduplicate exact pairs before inference."""
    cases_by_id = {case["id"]: case for case in corpus["cases"]}
    jobs: list[dict[str, Any]] = []
    pair_inputs: dict[str, dict[str, Any]] = {}
    pair_usage: dict[str, int] = defaultdict(int)
    for case in corpus["cases"]:
        score_map = scores_by_case[case["id"]]
        for group in frozen["reference_groups"]:
            group_id = group["id"]
            for field in frozen["field_order"]:
                candidates = candidate_universe(case["candidates"], field)
                if not candidates:
                    raise ValueError(
                        f"empty candidate universe for {case['id']}/{field}"
                    )
                query = frozen["queries"][field]
                for builder_id, channel_specs in _POOL_BUILDERS.items():
                    channels = []
                    for method, channel_kind in channel_specs:
                        channel_group = (
                            "query_only" if channel_kind == "query" else group_id
                        )
                        channel_scores = cached_scores(
                            score_map,
                            field,
                            method,
                            channel_group,
                            _REPRESENTATION,
                            semantic_digest,
                        )
                        channels.append((method, channel_scores))
                    for budget in budgets:
                        indices, fused = build_rrf_pool(candidates, channels, budget)
                        items = []
                        for index in indices:
                            candidate = candidates[index]
                            document = methods.representation_text(
                                candidate, _REPRESENTATION
                            )
                            pair_sha = _pair_sha(query, document)
                            item = {
                                "candidate_index": index,
                                "candidate_id": candidate["id"],
                                "node_id": candidate.get("node_id"),
                                "pair_sha256": pair_sha,
                                "fusion_score": fused[candidate["id"]],
                            }
                            items.append(item)
                            pair_record = {
                                "pair_sha256": pair_sha,
                                "query": query,
                                "document": document,
                            }
                            old = pair_inputs.setdefault(pair_sha, pair_record)
                            if old != pair_record:
                                raise ValueError("exact pair digest collision")
                            pair_usage[pair_sha] += 1
                        job = {
                            "job_id": _sha256_json(
                                [case["id"], group_id, field, builder_id, budget]
                            ),
                            "case_id": case["id"],
                            "source_id": case["source_id"],
                            "variant": case["variant"],
                            "family": case["family"],
                            "split": case["split"],
                            "seed_group": group_id,
                            "field": field,
                            "query": query,
                            "representation": _REPRESENTATION,
                            "pool_builder": builder_id,
                            "pool_channels": [name for name, _ in channels],
                            "pool_budget": budget,
                            "candidate_universe": "text_projection"
                            if field == "root"
                            else "all_candidates",
                            "candidate_count": len(candidates),
                            "pool_count": len(items),
                            "pool_items": items,
                        }
                        jobs.append(job)

    if len(cases_by_id) != len(corpus["cases"]):
        raise ValueError("duplicate case identities in frozen corpus")
    unique_pairs = [
        pair_inputs[key] | {"use_count": pair_usage[key]} for key in sorted(pair_inputs)
    ]
    return {
        "format": _FORMAT,
        "dataset": {
            "baseline_dir": ".generated/product-retrieval-minilm-v3",
            "corpus_checksum": frozen["corpus_checksum"],
            "semantic_artifact_sha256": semantic_digest,
            "semantic_model": "sentence-transformers/all-MiniLM-L6-v2",
            "scoring_cache_identity": "run_matrix.py cache_identity, repeats=1",
            "evaluation_boundary": (
                "controlled development source pages and mutations; no fresh-site claim"
            ),
        },
        "plan": {
            "case_count": len(corpus["cases"]),
            "seed_groups": [group["id"] for group in frozen["reference_groups"]],
            "fields": list(frozen["field_order"]),
            "pool_builders": list(_POOL_BUILDERS),
            "pool_budgets": list(budgets),
            "models": list(models),
            "reranker_jobs_per_model": len(jobs),
            "reranker_jobs_total": len(jobs) * len(models),
            "pooled_candidate_occurrences_per_model": sum(
                job["pool_count"] for job in jobs
            ),
            "unique_exact_pairs_per_model": len(unique_pairs),
            "max_new_unique_pairs_per_model": _DEFAULT_MAX_NEW_PAIRS,
            "rrf_constant": 60,
            "pool_selection_is_gold_blind": True,
            "root_candidates_use_text_projection": True,
            "root_predictions_are_needed_for_scoped_field_metrics": True,
        },
        "jobs": jobs,
        "unique_pairs": unique_pairs,
    }


def load_campaign_plan(path: Path) -> dict[str, Any]:
    """Load a plan and verify its internal exact-pair/job references."""
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("format") != _FORMAT:
        raise ValueError("unsupported reranker campaign plan")
    pair_ids = {pair["pair_sha256"] for pair in plan["unique_pairs"]}
    if len(pair_ids) != len(plan["unique_pairs"]):
        raise ValueError("campaign plan repeats an exact pair in unique_pairs")
    for job in plan["jobs"]:
        if len(job["pool_items"]) > 50:
            raise ValueError("campaign plan contains a pool larger than 50")
        for item in job["pool_items"]:
            if item["pair_sha256"] not in pair_ids:
                raise ValueError("campaign job refers to an unknown exact pair")
    return plan


def execute_model(
    plan: dict[str, Any],
    model: str,
    pair_cache_dir: Path,
    *,
    max_new_unique_pairs: int = _DEFAULT_MAX_NEW_PAIRS,
    batch_size: int = _BATCH_SIZE,
    expected_model_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score every plan pair once with one loaded CPU model, using durable cache."""
    if model not in plan["plan"]["models"]:
        raise ValueError(f"model {model!r} is not declared in the campaign plan")
    if max_new_unique_pairs < 1 or batch_size < 1:
        raise ValueError("pair and batch bounds must be positive")
    started = time.perf_counter()
    runtime = rerank._runtime_identity(model)
    identity = {
        "backend": "fastembed.TextCrossEncoder",
        "model": model,
        "runtime": runtime,
    }
    cache_key = rerank._sha256_json(identity)
    entries_dir = Path(pair_cache_dir) / model_slug(model) / "pairs" / cache_key
    scores: dict[str, float] = {}
    telemetry: dict[str, dict[str, Any]] = {}
    missing: list[tuple[str, str, str]] = []
    resolved_artifact: dict[str, Any] | None = None
    cache_read_started = time.perf_counter()
    for pair in plan["unique_pairs"]:
        pair_key = pair["pair_sha256"]
        inputs = (pair["query"], pair["document"])
        entry = rerank._read_cache_entry(entries_dir, pair_key, inputs, identity)
        if entry is None:
            missing.append((pair_key, inputs[0], inputs[1]))
        else:
            score, record, artifact = entry
            scores[pair_key] = score
            telemetry[pair_key] = record
            if artifact is not None:
                if resolved_artifact is not None and artifact != resolved_artifact:
                    raise ValueError(
                        "cached pair scores refer to different model artifacts"
                    )
                resolved_artifact = artifact
    if (
        expected_model_artifact is not None
        and resolved_artifact is not None
        and resolved_artifact != expected_model_artifact
    ):
        raise ValueError("cached pair scores do not match the preflight model snapshot")
    cache_read_ms = (time.perf_counter() - cache_read_started) * 1000
    if len(missing) > max_new_unique_pairs:
        raise ValueError(
            f"campaign requires {len(missing)} new unique pairs for {model}; "
            f"authorized cap is {max_new_unique_pairs}"
        )

    setup_wall_ms = setup_cpu_ms = inference_wall_ms = inference_cpu_ms = 0.0
    token_counting_wall_ms = cache_write_ms = 0.0
    input_tokens = truncated_pairs = inference_calls = 0
    batches: list[dict[str, Any]] = []
    model_cache_bytes_added: int | None = 0
    if missing:
        model_cache = rerank._model_cache_path()
        before_bytes = (
            rerank._tree_bytes(model_cache) if model_cache is not None else None
        )
        setup_started, setup_cpu_started = time.perf_counter(), time.process_time()
        encoder = rerank._load_encoder(model)
        setup_wall_ms = (time.perf_counter() - setup_started) * 1000
        setup_cpu_ms = (time.process_time() - setup_cpu_started) * 1000
        after_bytes = (
            rerank._tree_bytes(model_cache) if model_cache is not None else None
        )
        if before_bytes is None or after_bytes is None:
            model_cache_bytes_added = None
        else:
            model_cache_bytes_added = max(0, after_bytes - before_bytes)
        resolved_artifact = rerank._resolved_model_artifact(encoder, runtime)
        if (
            expected_model_artifact is not None
            and resolved_artifact != expected_model_artifact
        ):
            raise ValueError("loaded model snapshot differs from preflight identity")
        pairs = [(query, document) for _, query, document in missing]
        pair_records, token_counting_wall_ms = rerank._pair_telemetry(encoder, pairs)
        for start in range(0, len(missing), batch_size):
            chunk = missing[start : start + batch_size]
            records = pair_records[start : start + batch_size]
            inputs = [(query, document) for _, query, document in chunk]
            batch_tokens = sum(record["model_input_tokens"] for record in records)
            input_tokens += batch_tokens
            inference_started, inference_cpu_started = (
                time.perf_counter(),
                time.process_time(),
            )
            raw_scores = list(
                encoder.rerank_pairs(inputs, batch_size=batch_size, parallel=None)
            )
            wall_ms = (time.perf_counter() - inference_started) * 1000
            cpu_ms = (time.process_time() - inference_cpu_started) * 1000
            inference_wall_ms += wall_ms
            inference_cpu_ms += cpu_ms
            inference_calls += 1
            if len(raw_scores) != len(chunk):
                raise RuntimeError("cross-encoder returned an unexpected score count")
            batches.append(
                {
                    "pair_count": len(chunk),
                    "input_tokens": batch_tokens,
                    "wall_ms": wall_ms,
                    "cpu_ms": cpu_ms,
                }
            )
            write_started = time.perf_counter()
            for (pair_key, query, document), record, raw_score in zip(
                chunk, records, raw_scores, strict=True
            ):
                score = float(raw_score)
                if not math.isfinite(score):
                    raise RuntimeError("cross-encoder returned a non-finite raw score")
                pair = (query, document)
                rerank._write_cache_entry(
                    entries_dir,
                    pair_key,
                    pair,
                    score,
                    record,
                    identity,
                    resolved_artifact,
                )
                scores[pair_key] = score
                telemetry[pair_key] = record
                truncated_pairs += int(record["truncated"])
            cache_write_ms += (time.perf_counter() - write_started) * 1000

    if missing:
        missing_ids = {record[0] for record in missing}
        cached_ids = set(scores) - missing_ids
    else:
        cached_ids = set(scores)
    for pair_key in cached_ids:
        record = telemetry[pair_key]
        input_tokens += int(record["model_input_tokens"])
        truncated_pairs += int(record["truncated"])
    result = {
        "model": model,
        "model_identity": identity,
        "resolved_model_artifact": resolved_artifact,
        "scores": scores,
        "pair_telemetry": telemetry,
        "ledger": {
            "unique_pairs_requested": len(plan["unique_pairs"]),
            "cache_hits": len(cached_ids),
            "cache_misses": len(missing),
            "max_new_unique_pairs_authorized": max_new_unique_pairs,
            "cache_read_wall_ms": cache_read_ms,
            "cache_write_wall_ms": cache_write_ms,
            "model_setup_wall_ms": setup_wall_ms,
            "model_setup_cpu_ms": setup_cpu_ms,
            "model_cache_bytes_added": model_cache_bytes_added,
            "inference_calls": inference_calls,
            "inference_wall_ms": inference_wall_ms,
            "inference_cpu_ms": inference_cpu_ms,
            "token_counting_wall_ms": token_counting_wall_ms,
            "input_tokens": input_tokens,
            "truncated_pairs": truncated_pairs,
            "batches": batches,
            "api_cost_usd": 0.0,
            "hardware_cost_usd": None,
            "cost_note": (
                "Local CPU inference has no API charge; hardware cost is unmeasured."
            ),
            "adapter_wall_ms": (time.perf_counter() - started) * 1000,
        },
    }
    return result


def evaluate_model(
    plan: dict[str, Any], corpus: dict[str, Any], model_result: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate reranked pools after inference; no labels enter pool generation."""
    model = model_result["model"]
    scores = model_result["scores"]
    cases = {case["id"]: case for case in corpus["cases"]}
    job_rows: list[dict[str, Any]] = []
    root_predictions: dict[tuple[str, str, str, int], str | None] = {}
    ranked_by_job: dict[str, list[dict[str, Any]]] = {}

    for job in plan["jobs"]:
        ranked = [
            {
                **item,
                "raw_score": scores[item["pair_sha256"]],
            }
            for item in job["pool_items"]
        ]
        # ``pool_items`` is emitted in RRF rank order.
        # Preserve that order for raw-score ties.
        pool_order = {
            item["candidate_id"]: position
            for position, item in enumerate(job["pool_items"])
        }
        ranked.sort(
            key=lambda item: (
                -item["raw_score"],
                pool_order[item["candidate_id"]],
            )
        )
        ranked_by_job[job["job_id"]] = ranked
        if job["field"] == "root":
            key = (
                job["case_id"],
                job["seed_group"],
                job["pool_builder"],
                job["pool_budget"],
            )
            root_predictions[key] = ranked[0]["node_id"] if ranked else None

    for job in plan["jobs"]:
        case = cases[job["case_id"]]
        universe = candidate_universe(case["candidates"], job["field"])
        candidate_by_id = {candidate["id"]: candidate for candidate in universe}
        expected = set(case["expected"].get(job["field"], []))
        canonical = set(case["canonical_expected"].get(job["field"], []))
        pool_ranked = ranked_by_job[job["job_id"]]
        pool_ids = {item["candidate_id"] for item in pool_ranked}
        pool_present = bool(expected & set(candidate_by_id))
        pool_alias_recall = bool(expected & pool_ids) if expected else None
        pool_canonical_recall = bool(canonical & pool_ids) if canonical else None
        modes = ["global"] if job["field"] == "root" else ["global", "predicted_root"]
        for mode in modes:
            predicted_root = None
            eligible = pool_ranked
            if mode == "predicted_root":
                root_key = (
                    job["case_id"],
                    job["seed_group"],
                    job["pool_builder"],
                    job["pool_budget"],
                )
                predicted_root = root_predictions.get(root_key)
                eligible = (
                    []
                    if predicted_root is None
                    else [
                        item
                        for item in pool_ranked
                        if candidate_by_id[item["candidate_id"]]["node_id"]
                        == predicted_root
                        or predicted_root
                        in candidate_by_id[item["candidate_id"]].get("ancestors", [])
                    ]
                )
            top = eligible[:5]
            top_ids = [item["candidate_id"] for item in top]
            alias_hits = {str(k): bool(set(top_ids[:k]) & expected) for k in (1, 3, 5)}
            canonical_hits = {
                str(k): bool(set(top_ids[:k]) & canonical) for k in (1, 3, 5)
            }
            first_alias = next(
                (
                    position
                    for position, item in enumerate(eligible, start=1)
                    if item["candidate_id"] in expected
                ),
                None,
            )
            first_canonical = next(
                (
                    position
                    for position, item in enumerate(eligible, start=1)
                    if item["candidate_id"] in canonical
                ),
                None,
            )
            top_candidate = candidate_by_id[top_ids[0]] if top_ids else None
            owner = case["owning_root_id"]
            owner_correct = bool(
                top_candidate
                and (
                    top_candidate["node_id"] == owner
                    or owner in top_candidate.get("ancestors", [])
                )
            )
            job_rows.append(
                {
                    "case": job["case_id"],
                    "source_id": job["source_id"],
                    "split": job["split"],
                    "variant": job["variant"],
                    "family": job["family"],
                    "group": job["seed_group"],
                    "field": job["field"],
                    "pool_builder": job["pool_builder"],
                    "pool_budget": job["pool_budget"],
                    "pool_count": job["pool_count"],
                    "pool_candidate_recall": pool_alias_recall,
                    "pool_canonical_recall": pool_canonical_recall,
                    "candidate_present": pool_present,
                    "model": model,
                    "mode": mode,
                    "predicted_root_node_id": predicted_root,
                    "post_scope_pool_count": len(eligible),
                    "post_scope_pool_recall": (
                        bool(expected & {item["candidate_id"] for item in eligible})
                        if expected
                        else None
                    ),
                    "expected_present": bool(expected),
                    "missing_field_false_positive": not expected and bool(top_ids),
                    "top1_correct": alias_hits["1"] if expected else not top_ids,
                    "owner_correct": owner_correct,
                    "abstained": not top_ids,
                    "alias_hit": alias_hits,
                    "canonical_hit": canonical_hits,
                    "alias_mrr": 1.0 / first_alias if first_alias else 0.0,
                    "canonical_mrr": 1.0 / first_canonical if first_canonical else 0.0,
                    "top": [
                        {
                            "id": item["candidate_id"],
                            "node_id": item["node_id"],
                            "raw_score": item["raw_score"],
                            "selection_rank": rank,
                            "pool_rank": pool_ranked.index(item) + 1,
                        }
                        for rank, item in enumerate(top, start=1)
                    ],
                    "top_raw_score": top[0]["raw_score"] if top else None,
                    "score_margin": (
                        top[0]["raw_score"] - top[1]["raw_score"]
                        if len(top) > 1
                        else None
                    ),
                    "scores_are_calibrated_confidence": False,
                }
            )

    complete_rows = []
    group_keys = set()
    for row in job_rows:
        group_keys.add(
            (
                row["case"],
                row["group"],
                row["pool_builder"],
                row["pool_budget"],
                row["model"],
                row["mode"],
            )
        )
    expected_fields = set(plan["plan"]["fields"])
    for case_id, group_id, builder, budget, model_name, mode in sorted(group_keys):
        members = [
            row
            for row in job_rows
            if row["case"] == case_id
            and row["group"] == group_id
            and row["pool_builder"] == builder
            and row["pool_budget"] == budget
            and row["model"] == model_name
            and (
                row["mode"] == mode
                or (row["field"] == "root" and row["mode"] == "global")
            )
        ]
        by_field = {row["field"]: row for row in members}
        if set(by_field) != expected_fields:
            continue
        complete_rows.append(
            {
                "case": case_id,
                "group": group_id,
                "pool_builder": builder,
                "pool_budget": budget,
                "model": model_name,
                "mode": mode,
                "complete_record_correct": all(
                    row["top1_correct"] for row in by_field.values()
                ),
            }
        )
    return {
        "model": model,
        "job_rows": job_rows,
        "complete_records": complete_rows,
        "summary": summarize_results(job_rows, complete_rows),
    }


def summarize_results(
    rows: list[dict[str, Any]], complete_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Aggregate per-field, per-variant and complete-record measurements."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row["model"],
            row["pool_builder"],
            row["pool_budget"],
            row["group"],
            row["variant"],
            row["family"],
            row["field"],
            row["mode"],
        )
        groups[key].append(row)
    summaries = []
    for key, members in sorted(groups.items()):
        present = [row for row in members if row["expected_present"]]
        absent = [row for row in members if not row["expected_present"]]
        summaries.append(
            {
                "model": key[0],
                "pool_builder": key[1],
                "pool_budget": key[2],
                "group": key[3],
                "variant": key[4],
                "family": key[5],
                "field": key[6],
                "mode": key[7],
                "trials": len(members),
                "present_trials": len(present),
                "absent_trials": len(absent),
                "pool_recall": _mean_bool(
                    row["pool_candidate_recall"] for row in present
                ),
                "pool_canonical_recall": _mean_bool(
                    row["pool_canonical_recall"] for row in present
                ),
                "alias_top1_accuracy": _mean_bool(
                    row["top1_correct"] for row in members
                ),
                "present_top1_accuracy": _mean_bool(
                    row["top1_correct"] for row in present
                ),
                "missing_field_false_positive_rate": _mean_bool(
                    row["missing_field_false_positive"] for row in absent
                ),
                "owner_accuracy": _mean_bool(row["owner_correct"] for row in members),
                "alias_mrr": _mean(row["alias_mrr"] for row in members),
                "canonical_mrr": _mean(row["canonical_mrr"] for row in members),
                "alias_recall_at_1": _mean_bool(
                    row["alias_hit"]["1"] for row in members
                ),
                "alias_recall_at_3": _mean_bool(
                    row["alias_hit"]["3"] for row in members
                ),
                "alias_recall_at_5": _mean_bool(
                    row["alias_hit"]["5"] for row in members
                ),
                "abstentions": sum(row["abstained"] for row in members),
            }
        )
    complete_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in complete_rows:
        complete_groups[
            (
                row["model"],
                row["pool_builder"],
                row["pool_budget"],
                row["group"],
                row["mode"],
            )
        ].append(row)
    return {
        "per_field": summaries,
        "complete_records": [
            {
                "model": key[0],
                "pool_builder": key[1],
                "pool_budget": key[2],
                "group": key[3],
                "mode": key[4],
                "trials": len(members),
                "complete_record_accuracy": _mean_bool(
                    row["complete_record_correct"] for row in members
                ),
            }
            for key, members in sorted(complete_groups.items())
        ],
    }


def _mean(values) -> float | None:
    items = [float(value) for value in values]
    return statistics.fmean(items) if items else None


def _mean_bool(values) -> float | None:
    items = [float(bool(value)) for value in values if value is not None]
    return statistics.fmean(items) if items else None


def model_slug(model: str) -> str:
    """Return a stable, filesystem-safe model label."""
    return "minilm-l6" if model.endswith("L-6-v2") else "minilm-l12"


def _pair_sha(query: str, document: str) -> str:
    return rerank._pair_key(query, document)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(run_matrix.canonical(value)).hexdigest()


def _parse_budgets(value: str) -> tuple[int, ...]:
    budgets = tuple(int(item) for item in value.split(",") if item)
    if not budgets or any(budget not in (5, 20, 50) for budget in budgets):
        raise argparse.ArgumentTypeError("budgets must be a subset of 5,20,50")
    return budgets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--baseline-dir", type=Path, required=True)
    plan_parser.add_argument("--scoring-cache-dir", type=Path, required=True)
    plan_parser.add_argument("--semantic-artifact", type=Path, required=True)
    plan_parser.add_argument("--output-dir", type=Path, required=True)
    plan_parser.add_argument("--budgets", type=_parse_budgets, default=(5, 20, 50))

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--plan", type=Path, required=True)
    preflight_parser.add_argument("--baseline-dir", type=Path, required=True)
    preflight_parser.add_argument("--semantic-artifact", type=Path, required=True)
    preflight_parser.add_argument("--model-cache-dir", type=Path)
    preflight_parser.add_argument("--output", type=Path, required=True)

    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("--plan", type=Path, required=True)
    execute_parser.add_argument("--preflight", type=Path, required=True)
    execute_parser.add_argument("--baseline-dir", type=Path, required=True)
    execute_parser.add_argument("--pair-cache-dir", type=Path, required=True)
    execute_parser.add_argument("--output-dir", type=Path, required=True)
    execute_parser.add_argument("--model", choices=sorted(_MODELS), required=True)
    execute_parser.add_argument(
        "--max-new-unique-pairs", type=int, default=_DEFAULT_MAX_NEW_PAIRS
    )

    args = parser.parse_args()
    if args.command == "plan":
        if args.output_dir.exists():
            parser.error(
                "output directory already exists; use a fresh campaign directory"
            )
        frozen, corpus, scores, semantic_digest = load_baseline(
            args.baseline_dir, args.scoring_cache_dir, args.semantic_artifact
        )
        plan = build_plan(frozen, corpus, scores, semantic_digest, budgets=args.budgets)
        if plan["plan"]["unique_exact_pairs_per_model"] > _DEFAULT_MAX_NEW_PAIRS:
            parser.error("planned pairs exceed the authorized per-model inference cap")
        args.output_dir.mkdir(parents=True, exist_ok=False)
        _atomic_json(args.output_dir / "plan.json", plan)
        print(json.dumps(plan["plan"], sort_keys=True))
        return

    if args.command == "preflight":
        preflight = write_preflight(
            args.plan,
            args.baseline_dir,
            args.semantic_artifact,
            args.output,
            model_cache_dir=args.model_cache_dir,
        )
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "plan_sha256": preflight["plan_sha256"],
                    "models": [
                        item["model"] for item in preflight["reranker_run"]["models"]
                    ],
                    "pairs_per_model": preflight["reranker_run"][
                        "planned_unique_pairs_per_model"
                    ],
                },
                sort_keys=True,
            )
        )
        return

    plan = load_campaign_plan(args.plan)
    preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
    plan_sha256 = _sha256_bytes(args.plan.read_bytes())
    if preflight.get("plan_sha256") != plan_sha256:
        parser.error("preflight artifact does not match the campaign plan")
    model_preflight = next(
        (
            item
            for item in preflight["reranker_run"]["models"]
            if item["model"] == args.model
        ),
        None,
    )
    if model_preflight is None:
        parser.error("preflight artifact does not include the requested model")
    result = execute_model(
        plan,
        args.model,
        args.pair_cache_dir,
        max_new_unique_pairs=args.max_new_unique_pairs,
        expected_model_artifact=model_preflight["resolved_model_artifact"],
    )
    with _read_baseline(args.baseline_dir) as corpus:
        evaluated = evaluate_model(plan, corpus, result)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    slug = model_slug(args.model)
    _atomic_json(args.output_dir / f"{slug}-scores.json", result)
    _atomic_json(args.output_dir / f"{slug}-summary.json", evaluated["summary"])
    _write_jsonl(args.output_dir / f"{slug}-jobs.jsonl", evaluated["job_rows"])
    _write_jsonl(
        args.output_dir / f"{slug}-complete-records.jsonl",
        evaluated["complete_records"],
    )
    print(json.dumps(result["ledger"], sort_keys=True))


class _read_baseline:
    """Small context-manager wrapper for the campaign's frozen corpus file."""

    def __init__(self, baseline_dir: Path):
        self.path = Path(baseline_dir) / "corpus.json"
        self.value: dict[str, Any] | None = None

    def __enter__(self) -> dict[str, Any]:
        self.value = json.loads(self.path.read_text(encoding="utf-8"))
        return self.value

    def __exit__(self, *_: Any) -> None:
        self.value = None


def _atomic_json(path: Path, value: Any) -> None:
    """Write a JSON artifact atomically under its parent directory."""
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


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    """Write one JSON object per line atomically."""
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
            for value in values:
                temporary.write(
                    json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n"
                )
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
