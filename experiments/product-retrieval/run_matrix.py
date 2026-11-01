"""Frozen, source-grounded product candidate retrieval experiment (not SDK API)."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import itertools
import json
import math
import platform
import statistics
import sys
import time
from pathlib import Path

import corpus
import methods

HERE = Path(__file__).resolve().parent
FIELDS = {
    "root": (
        "One complete main product detail region with identity, "
        "name, purchase price, color, material and availability"
    ),
    "id": "Product identity attached to the selected product",
    "name": "Product name",
    "price": (
        "Displayed USD purchase price of this product, "
        "excluding installment payments, shipping and other "
        "products"
    ),
    "color": "Color of the selected product identified by its nearby label",
    "material": "Material of the selected product identified by its nearby label",
    "stock": (
        "Stock availability of the selected product including explicit unavailability"
    ),
}
REPRESENTATIONS = ["value", "context", "structure_context"]


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def checksum(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def implementation():
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(HERE.glob("*.py"))
    }


def available_methods():
    raw = methods.METHODS
    names = (
        list(raw)
        if isinstance(raw, dict)
        else [m if isinstance(m, str) else m["id"] for m in raw]
    )
    aliases = {
        "structural_weighted_jaccard",
        "hierarchical_structure",
        "lexical_token_jaccard_query",
        "lexical_bm25_query",
        "lexical_tfidf_cosine_query",
        "semantic_query_cosine",
        "semantic_reference_cosine",
        "tree_path_edit_reference",
    }
    return [name for name in names if name not in aliases]


def query_order(queries):
    """Resolve the root before any dependent field, regardless of JSON key order."""
    if "root" not in queries:
        raise ValueError("queries require a root before scoped field evaluation")
    return ["root", *sorted(set(queries) - {"root"})]


def freeze(source, output):
    if output.exists():
        raise ValueError("freeze requires a new output directory")
    started = time.perf_counter_ns()
    data = corpus.prepare_corpus(source)
    if len({c["id"] for c in data["cases"]}) != len(data["cases"]):
        raise ValueError("duplicate case identity")
    by_id = {c["id"]: c for c in data["cases"]}
    refs = data["references"]
    if any(r not in by_id for r in refs):
        raise ValueError("missing reference source")
    groups = [
        {"id": "+".join(g), "cases": list(g)}
        for size in range(1, len(refs) + 1)
        for g in itertools.combinations(refs, size)
    ]
    frozen = {
        "version": 1,
        "source": str(source.resolve()),
        "corpus_checksum": checksum(data),
        "implementation": implementation(),
        "queries": FIELDS,
        "field_order": query_order(FIELDS),
        "reference_groups": groups,
        "representations": REPRESENTATIONS,
        "methods": available_methods(),
        "fusion": ["rrf", "union_support", "structural_anchor"],
        "rrf_constant": 60,
        "top_k": [1, 3, 5],
        "selection_modes": ["global", "predicted_root"],
        "execution": "sequential; no target annotations passed to scorers",
        "python": sys.version,
        "platform": platform.platform(),
        "prepare_ns": time.perf_counter_ns() - started,
    }
    save(output / "corpus.json", data)
    save(output / "frozen.json", frozen)
    print(
        json.dumps(
            {
                "cases": len(by_id),
                "references": refs,
                "methods": frozen["methods"],
                "output": str(output),
            }
        ),
        flush=True,
    )


def rank(scores, candidates):
    if len(scores) != len(candidates) or any(
        not math.isfinite(s) or s < 0 for s in scores
    ):
        raise ValueError("invalid scorer output")
    return sorted(range(len(scores)), key=lambda i: (-scores[i], candidates[i]["id"]))


def score_one(method, query, candidates, references, representation, vectors):
    start = time.perf_counter_ns()
    values = methods.score_candidates(
        method, query, candidates, references, representation, vectors
    )
    elapsed = time.perf_counter_ns() - start
    return list(values), elapsed


def fuse(policy, members, candidates, structural):
    n = len(candidates)
    if not members:
        return [0.0] * n
    result = [0.0] * n
    for name, scores in members.items():
        order = rank(scores, candidates)
        for place, i in enumerate(order, start=1):
            if scores[i] <= 0:
                continue
            if policy == "rrf":
                result[i] += 1 / (60 + place)
            elif policy == "union_support":
                if place <= 5:
                    result[i] += 1 + 1 / (60 + place)
            elif policy == "structural_anchor":
                if name == structural:
                    result[i] += scores[i]
                elif place <= 5:
                    result[i] += 0.01 / (60 + place)
            else:
                raise ValueError("unknown fusion")
    return result


def evaluate(scores, candidates, gold, owner, mode, root_node=None):
    """Annotations enter here only, after scores and predicted root are fixed."""
    permitted = list(range(len(candidates)))
    if mode == "predicted_root":
        permitted = (
            []
            if root_node is None
            else [
                i
                for i in permitted
                if candidates[i]["node_id"] == root_node
                or root_node in candidates[i]["ancestors"]
            ]
        )
    permitted_set = set(permitted)
    order = [
        i for i in rank(scores, candidates) if i in permitted_set and scores[i] > 0
    ]
    selected = order[:5]
    ids = [candidates[i]["id"] for i in selected]
    target = set(gold)
    hits = {str(k): bool(set(ids[:k]) & target) for k in (1, 3, 5)}
    top = candidates[selected[0]] if selected else None
    owner_ok = bool(top and (top["node_id"] == owner or owner in top["ancestors"]))
    first_relevant = next(
        (j + 1 for j, i in enumerate(order) if candidates[i]["id"] in target), None
    )
    best = scores[selected[0]] if selected else 0.0
    second = scores[selected[1]] if len(selected) > 1 else 0.0
    return {
        "expected_present": bool(target),
        "gold_candidates": len(target),
        "candidate_present": bool(target & {c["id"] for c in candidates}),
        "hit": hits,
        "top1_correct": hits["1"] if target else not ids,
        "owner_correct": owner_ok,
        "reciprocal_rank": 1 / first_relevant if first_relevant else 0.0,
        "top": [
            {
                "id": candidates[i]["id"],
                "score": scores[i],
                "node_id": candidates[i]["node_id"],
            }
            for i in selected
        ],
        "top_score": best,
        "margin": best - second,
        "top_tie_count": sum(scores[i] == best for i in permitted) if selected else 0,
        "context_bytes_top5": sum(
            len(candidates[i]["context"].encode()) for i in selected
        ),
        "abstained": not ids,
    }


def run(output, semantic_path=None, repeats=1):
    frozen = json.loads((output / "frozen.json").read_text())
    data = json.loads((output / "corpus.json").read_text())
    if checksum(data) != frozen["corpus_checksum"]:
        raise ValueError("corpus integrity mismatch")
    if frozen["implementation"] != implementation():
        raise ValueError("implementation changed: freeze a fresh run")
    vectors = None
    semantic_meta = None
    semantic_digest = None
    if semantic_path:
        semantic = json.loads(semantic_path.read_text())
        vectors = semantic["vectors"]
        semantic_meta = {k: v for k, v in semantic.items() if k != "vectors"}
        semantic_digest = hashlib.sha256(semantic_path.read_bytes()).hexdigest()
        required = set(frozen["queries"].values())
        required.update(
            methods.representation_text(candidate, representation)
            for case in data["cases"]
            for candidate in case["candidates"]
            for representation in frozen["representations"]
        )
        missing = required - vectors.keys()
        if missing:
            raise ValueError(
                f"semantic artifact missing {len(missing)} exact input vectors"
            )
        dimensions = {len(vectors[text]) for text in required}
        if (
            len(dimensions) != 1
            or 0 in dimensions
            or any(
                not all(math.isfinite(x) for x in vectors[text])
                or not any(vectors[text])
                for text in required
            )
        ):
            raise ValueError(
                "semantic vectors invalid, empty, zero or inconsistent dimensions"
            )
    cases = {c["id"]: c for c in data["cases"]}
    results = []
    failures = []
    started = time.perf_counter_ns()
    methods_to_run = [
        m
        for m in frozen["methods"]
        if not m.startswith("semantic") or vectors is not None
    ]
    if repeats < 1:
        raise ValueError("repeats must be positive")
    for case_index, case in enumerate(data["cases"]):
        all_candidates = case["candidates"]
        candidate_ids = {c["id"] for c in all_candidates}
        if len(candidate_ids) != len(all_candidates):
            raise ValueError("duplicate candidate identity")
        cache_identity = checksum(
            {
                "corpus_checksum": frozen["corpus_checksum"],
                "runner_code": frozen["implementation"]["run_matrix.py"],
                "candidate_input": all_candidates,
                "reference_cases": [cases[r]["candidates"] for r in data["references"]],
                "queries": frozen["queries"],
                "methods_code": frozen["implementation"]["methods.py"],
                "repeats": repeats,
            }
        )
        cache_path = output.parent / "scoring-cache" / f"{cache_identity}.json.gz"
        cached_scores = {}
        if cache_path.exists():
            cached_scores = json.loads(gzip.decompress(cache_path.read_bytes()))
        new_cache_entries = False
        for group in frozen["reference_groups"]:
            # Exclude seed cases from transfer evaluation; retain explicit seed rows.
            is_seed = case["source_id"] in group["cases"] and case["variant"] in (
                "original",
                "baseline",
            )
            for representation in frozen["representations"]:
                root_predictions = {}
                for field in query_order(frozen["queries"]):
                    description = frozen["queries"][field]
                    candidates = (
                        [c for c in all_candidates if c["projection"] == "text"]
                        if field == "root"
                        else all_candidates
                    )
                    query = {"field": field, "description": description}
                    refs = [
                        c
                        for source_id in group["cases"]
                        for c in cases[source_id]["candidates"]
                        if c["id"] in cases[source_id]["expected"].get(field, [])
                    ]
                    scores_by_method = {}
                    timing = {}
                    for method in methods_to_run:
                        try:
                            metadata = methods.METHOD_METADATA[method]
                            effective_group = (
                                "query_only"
                                if metadata["reference_aggregation"] == "none"
                                else group["id"]
                            )
                            effective_rep = representation
                            cache_key = json.dumps(
                                [
                                    field,
                                    method,
                                    effective_group,
                                    effective_rep,
                                    semantic_digest
                                    if method.startswith("semantic")
                                    else None,
                                ]
                            )
                            if cache_key in cached_scores:
                                stored = cached_scores[cache_key]
                                scores_by_method[method] = stored["scores"]
                                timing[method] = {
                                    **stored["timing"],
                                    "reused_scoring_result": True,
                                }
                                continue
                            observations = []
                            scores = None
                            for _ in range(repeats):
                                scores, elapsed = score_one(
                                    method,
                                    query,
                                    candidates,
                                    refs,
                                    representation,
                                    vectors,
                                )
                                rank(scores, candidates)
                                observations.append(elapsed)
                            scores_by_method[method] = scores
                            timing[method] = {
                                "median_ns": statistics.median(observations),
                                "samples_ns": observations,
                                "reused_scoring_result": False,
                                "measurement": (
                                    "in-memory candidate scoring; "
                                    "excludes feature/corpus "
                                    "and embedding acquisition"
                                ),
                            }
                            cached_scores[cache_key] = {
                                "scores": scores,
                                "timing": timing[method],
                            }
                            new_cache_entries = True
                        except Exception as error:
                            failures.append(
                                {
                                    "case": case["id"],
                                    "group": group["id"],
                                    "representation": representation,
                                    "field": field,
                                    "method": method,
                                    "error": f"{type(error).__name__}: {error}",
                                }
                            )
                    # One representative per feature family prevents duplicate votes.
                    family_members = {}
                    for _family, choices in {
                        "structure": [
                            "hierarchical_jaccard",
                            "structural_jaccard",
                            "local_jaccard",
                        ],
                        "lexical": ["bm25", "tfidf_cosine", "token_jaccard"],
                        "semantic": ["semantic_query", "semantic_reference"],
                    }.items():
                        chosen = next(
                            (name for name in choices if name in scores_by_method), None
                        )
                        if chosen:
                            family_members[chosen] = scores_by_method[chosen]
                    structural = next(
                        (name for name in family_members if "jaccard" in name), None
                    )
                    for policy in frozen["fusion"]:
                        t = time.perf_counter_ns()
                        scores_by_method[f"hybrid_{policy}"] = fuse(
                            policy, family_members, candidates, structural
                        )
                        timing[f"hybrid_{policy}"] = {
                            "median_ns": time.perf_counter_ns()
                            - t
                            + sum(timing[m]["median_ns"] for m in family_members),
                            "samples_ns": [],
                            "includes": list(family_members),
                            "measurement": (
                                "estimated member medians plus measured fusion; not an "
                                "end-to-end median"
                            ),
                        }
                    for method, scores in scores_by_method.items():
                        order = rank(scores, candidates)
                        if field == "root":
                            root_predictions[method] = (
                                candidates[order[0]]["node_id"]
                                if order and scores[order[0]] > 0
                                else None
                            )
                        for mode in frozen["selection_modes"]:
                            actual_mode = "global" if field == "root" else mode
                            metrics = evaluate(
                                scores,
                                candidates,
                                case["expected"].get(field, []),
                                case["owning_root_id"],
                                actual_mode,
                                root_predictions.get(method),
                            )
                            canonical_metrics = evaluate(
                                scores,
                                candidates,
                                case["canonical_expected"].get(field, []),
                                case["owning_root_id"],
                                actual_mode,
                                root_predictions.get(method),
                            )
                            metrics["canonical_hit"] = canonical_metrics["hit"]
                            metrics["canonical_top1_correct"] = canonical_metrics[
                                "top1_correct"
                            ]
                            results.append(
                                {
                                    "case": case["id"],
                                    "source_id": case["source_id"],
                                    "variant": case["variant"],
                                    "family": case["family"],
                                    "split": case["split"],
                                    "seed_case": is_seed,
                                    "group": group["id"],
                                    "representation": representation,
                                    "field": field,
                                    "method": method,
                                    "mode": mode,
                                    "evaluation_mode": actual_mode,
                                    "candidate_count": len(candidates),
                                    "timing": timing[method],
                                    **metrics,
                                }
                            )
        if new_cache_entries:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(gzip.compress(canonical(cached_scores), mtime=0))
        print(
            json.dumps(
                {
                    "case": case["id"],
                    "completed": case_index + 1,
                    "total": len(cases),
                    "rows": len(results),
                    "failures": len(failures),
                }
            ),
            flush=True,
        )
    report = {
        "version": 1,
        "frozen_checksum": checksum(frozen),
        "semantic": semantic_meta,
        "semantic_artifact_checksum": hashlib.sha256(
            semantic_path.read_bytes()
        ).hexdigest()
        if semantic_path
        else None,
        "repeats": repeats,
        "elapsed_ns": time.perf_counter_ns() - started,
        "skipped_methods": sorted(set(frozen["methods"]) - set(methods_to_run)),
        "failures": failures,
        "rows": results,
    }
    save(output / "report.json", report)
    from reporting import render

    render(output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("freeze")
    f.add_argument(
        "--source",
        type=Path,
        default=HERE.parent / "contract-fingerprints/fixtures/evidence",
    )
    f.add_argument("--output", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--output", type=Path, required=True)
    r.add_argument("--semantic", type=Path)
    r.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.source, args.output)
    else:
        run(args.output, args.semantic, args.repeats)


if __name__ == "__main__":
    main()
