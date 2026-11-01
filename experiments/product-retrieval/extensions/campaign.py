"""Stream a broader cross-layout retrieval and hybrid-ablation campaign."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import heapq
import importlib
import itertools
import json
import math
import shutil
import statistics
import sys
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
run_matrix = importlib.import_module("run_matrix")
methods = importlib.import_module("methods")
_bootstrap_acceleration = importlib.import_module("acceleration")
ExactCaches = _bootstrap_acceleration.ExactCaches
_bootstrap_run_matrix = importlib.import_module("run_matrix")
FIELDS = _bootstrap_run_matrix.FIELDS
available_methods = _bootstrap_run_matrix.available_methods
canonical = _bootstrap_run_matrix.canonical
checksum = _bootstrap_run_matrix.checksum
evaluate = _bootstrap_run_matrix.evaluate
query_order = _bootstrap_run_matrix.query_order
save = _bootstrap_run_matrix.save

advanced_methods = importlib.import_module("advanced_methods")

QUERIES = {
    **FIELDS,
    "root": (
        "One complete main product detail region containing product identity, "
        "name, purchase price and whatever product information the source exposes"
    ),
    "price": (
        "Currently displayed purchase price of the selected "
        "product, with currency as shown, excluding "
        "installment payments, shipping and prices of other "
        "products"
    ),
}

FUSION_POLICIES = ("rrf", "top5_union")
REPRESENTATIONS = ("value", "context", "structure_context", "context_first")
SEMANTIC_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
PREFIXED_SEMANTIC_METHOD = "semantic_query_retrieval_prefix"
LATENCY_SAMPLE_CAP = 64
MAX_SCORE_CACHE_ENTRIES = 128
MAX_FAILURE_SAMPLES = 20


def _implementation_paths(root=ROOT):
    paths = [*root.glob("*.py"), *(root / "extensions").glob("*.py")]
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def code_identity(root=ROOT):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _implementation_paths(root)
    }


def _snapshot_implementation(destination, expected_identity):
    destination.mkdir(parents=True, exist_ok=False)
    for source in _implementation_paths(ROOT):
        relative = source.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    observed = code_identity(destination)
    if observed != expected_identity:
        raise ValueError("implementation snapshot differs from its frozen identity")


def _config_digest(config):
    return checksum(
        {key: value for key, value in config.items() if key != "configuration_checksum"}
    )


def _verify_config(config):
    if config.get("configuration_checksum") != _config_digest(config):
        raise ValueError("frozen campaign configuration checksum mismatch")


def _semantic_texts(cases, queries, representations, semantic_query_prefix):
    texts = set(queries.values())
    texts.update(semantic_query_prefix + query for query in queries.values())
    texts.update(
        text_key(candidate, representation)
        for case in cases
        for candidate in case["candidates"]
        for representation in representations
    )
    return sorted(texts)


def freeze(base, fresh, output):
    if output.exists():
        raise ValueError("freeze requires a fresh directory")
    initial = json.loads(base.read_text())
    new = json.loads(fresh.read_text())
    cases = initial["cases"] + new["cases"]
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("duplicate case identity")
    field_order = query_order(QUERIES)
    for case in cases:
        if not isinstance(case.get("expected"), dict):
            raise ValueError(f"case {case.get('id')} has no expected candidate map")
        if not isinstance(case.get("canonical_expected"), dict):
            raise ValueError(f"case {case.get('id')} has no canonical candidate map")
        if not isinstance(case.get("owning_root_id"), str):
            raise ValueError(f"case {case.get('id')} has no owning root ID")

    preparation = {}
    started = time.perf_counter_ns()
    for case in cases:
        candidates, diagnostics = advanced_methods.prepare_case(case)
        case["candidates"] = candidates
        preparation[case["id"]] = diagnostics
        if "expected_present" not in case:
            case["expected_present"] = {
                field: bool(case["expected"].get(field)) for field in QUERIES
            }
        if "expected_status" not in case:
            case["expected_status"] = {
                field: "present_dom" if case["expected_present"][field] else "absent"
                for field in QUERIES
            }
        if set(case["expected_present"]) != set(field_order):
            raise ValueError(
                f"case {case['id']} has incomplete expected_present fields"
            )
        if set(case["expected_status"]) != set(field_order):
            raise ValueError(f"case {case['id']} has incomplete expected_status fields")

    originals = [c for c in cases if c["variant"] == "original"]
    templates = defaultdict(list)
    for case in originals:
        templates[case["family"]].append(case["id"])
    groups = []
    for family, identities in sorted(templates.items()):
        for count in (1, 2):
            chosen = identities[:count]
            if len(chosen) == count:
                groups.append({"id": f"{family}/{count}", "cases": chosen})
    groups.append(
        {
            "id": "one_per_template",
            "cases": [ids[0] for _, ids in sorted(templates.items())],
        }
    )
    for heldout in templates:
        remaining = [
            ids[0] for family, ids in sorted(templates.items()) if family != heldout
        ]
        if remaining:
            groups.append({"id": f"leave_out/{heldout}", "cases": remaining})
    tree_ids = []
    try:
        import tree_edit

        tree_ids = [
            f"{name}_n{nodes}" for name in tree_edit.METHODS for nodes in (32, 64)
        ]
    except ImportError:
        pass
    core_methods = available_methods()
    channel_members = {
        "structure": ["hierarchical_jaccard", "local_jaccard"],
        "lexical": [
            "bm25",
            "lexical_char_ngram_cosine_query",
            "lexical_char_ngram_cosine_reference",
        ],
        "semantic": [
            "semantic_query",
            PREFIXED_SEMANTIC_METHOD,
            "semantic_reference",
        ],
    }
    semantic_inputs = _semantic_texts(
        cases, QUERIES, REPRESENTATIONS, SEMANTIC_QUERY_PREFIX
    )
    code = code_identity()
    fresh_provenance = new.get("provenance", {})

    output.mkdir(parents=True, exist_ok=False)
    _snapshot_implementation(output / "implementation", code)
    config = {
        "version": 2,
        "queries": QUERIES,
        "field_order": field_order,
        "representations": list(REPRESENTATIONS),
        "reference_groups": groups,
        "core_methods": core_methods,
        "campaign_methods": [PREFIXED_SEMANTIC_METHOD],
        "advanced_methods": list(advanced_methods.ADVANCED_METHODS),
        "tree_methods": tree_ids,
        "channel_members": channel_members,
        "semantic_query_prefix": SEMANTIC_QUERY_PREFIX,
        "hybrid_subset_policy": (
            "Cross-family subsets contain at least two families; standalone "
            "methods are evaluated separately."
        ),
        "fusion_policies": list(FUSION_POLICIES),
        "modes": ["global", "predicted_root"],
        "top_k": [1, 3, 5],
        "corpus_checksum": checksum(cases),
        "code_identity": code,
        "implementation_snapshot": "implementation",
        "semantic_input_count": len(semantic_inputs),
        "semantic_input_checksum": checksum(semantic_inputs),
        "prepare_ns": time.perf_counter_ns() - started,
        "source_provenance": {
            "base": initial["provenance"],
            "fresh": new["provenance"],
        },
        "evaluation_disclosures": {
            "fresh_annotation_status": fresh_provenance.get("label_truth"),
            "fresh_document_truth": fresh_provenance.get("document_truth"),
            "fresh_labels_are_blind": False,
        },
        "notes": [
            "Synthetic sources and source-normalized HTML remain separate conditions.",
            (
                "Present external-only evidence is not DOM absence "
                "and is excluded from DOM ranking quality "
                "denominators."
            ),
            (
                "All cross-family hybrid subsets and member "
                "alternatives are compared; standalone methods cover "
                "one-family baselines."
            ),
            (
                "Context-first reverses the two actual text blocks "
                "without adding labels or answers."
            ),
            (
                "The retrieval-query prefix is an input "
                "representation ablation, not calibrated confidence "
                "or a claimed gain."
            ),
        ],
    }
    config["configuration_checksum"] = _config_digest(config)
    save(output / "corpus.json", {"cases": cases})
    save(output / "preparation.json", preparation)
    save(output / "frozen.json", config)
    print(
        json.dumps(
            {
                "cases": len(cases),
                "groups": len(groups),
                "methods": len(config["core_methods"])
                + len(config["advanced_methods"])
                + len(tree_ids),
                "snapshot_files": len(code),
                "semantic_inputs": len(semantic_inputs),
                "output": str(output),
            }
        )
    )


def projected(candidate, representation):
    if representation != "context_first":
        return candidate
    return {**candidate, "text": candidate["context"], "context": candidate["text"]}


def text_key(candidate, representation):
    return methods.representation_text(
        projected(candidate, representation),
        "context" if representation == "context_first" else representation,
    )


def rank(scores, candidates):
    """Resolve the active run-matrix ranker, including its exact cache wrapper."""
    return run_matrix.rank(scores, candidates)


def _read_frozen_bundle(output):
    config = json.loads((output / "frozen.json").read_text())
    cases = json.loads((output / "corpus.json").read_text())["cases"]
    _verify_config(config)
    if config["code_identity"] != code_identity():
        raise ValueError(
            "active implementation differs from frozen code; run the copied "
            "implementation/campaign.py snapshot"
        )
    if checksum(cases) != config["corpus_checksum"]:
        raise ValueError("frozen corpus changed")
    expected_order = query_order(config["queries"])
    if config.get("field_order") != expected_order:
        raise ValueError("frozen field order must evaluate the root before fields")
    if config.get("semantic_query_prefix") != SEMANTIC_QUERY_PREFIX:
        raise ValueError(
            "semantic query prefix differs from the frozen method implementation"
        )
    semantic_inputs = _semantic_texts(
        cases,
        config["queries"],
        config["representations"],
        config["semantic_query_prefix"],
    )
    if len(semantic_inputs) != config.get("semantic_input_count") or checksum(
        semantic_inputs
    ) != config.get("semantic_input_checksum"):
        raise ValueError("frozen semantic input set changed")
    return config, cases


def collect(output, destination):
    config, cases = _read_frozen_bundle(output)
    if destination.exists():
        raise ValueError("semantic input export must use a new file")
    texts = _semantic_texts(
        cases,
        config["queries"],
        config["representations"],
        config["semantic_query_prefix"],
    )
    if checksum(texts) != config["semantic_input_checksum"]:
        raise ValueError("semantic text export differs from its frozen identity")
    save(destination, texts)
    print(
        json.dumps(
            {
                "strings": len(texts),
                "sha256": checksum(texts),
                "utf8_bytes": sum(len(text.encode("utf-8")) for text in texts),
            }
        )
    )
    return texts


def condition(case, references):
    if case["id"] in {r["id"] for r in references}:
        return "reference_self"
    if case["source_id"] in {r["source_id"] for r in references}:
        return "source_derived"
    if case["family"] in {r["family"] for r in references}:
        return (
            "annotator_seen_same_template"
            if case["split"] == "fresh_cross_site"
            else "same_template_new_source"
        )
    if case["split"] == "fresh_cross_site":
        return "annotator_seen_unseen_template"
    return "controlled_unseen_shape"


def hybrid_variants(member_choices, available):
    families = sorted(member_choices)
    for selected in itertools.product(*[[None, *member_choices[f]] for f in families]):
        members = tuple(m for m in selected if m is not None)
        if len(members) >= 2 and all(m in available for m in members):
            yield members


def blend(policy, members, scores, candidates):
    total = [0.0] * len(candidates)
    for method in members:
        for place, index in enumerate(rank(scores[method], candidates), 1):
            if scores[method][index] <= 0:
                continue
            if policy == "rrf":
                total[index] += 1 / (60 + place)
            elif place <= 5:
                total[index] += 1 + 1 / (60 + place)
    return total


def score(method, query, candidates, refs, representation, vectors):
    if method in advanced_methods.ADVANCED_METHODS:
        values = advanced_methods.score_candidates(method, query, candidates, refs)
        diagnostics = {"status": "complete"}
        if method == "ordered_tree_fragment_jaccard":
            diagnostics.update(_fragment_completeness(candidates, refs))
        return values, diagnostics
    if method == PREFIXED_SEMANTIC_METHOD:
        prefixed_query = {
            **query,
            "description": SEMANTIC_QUERY_PREFIX + query["description"],
        }
        values = methods.score_candidates(
            "semantic_query",
            prefixed_query,
            [projected(candidate, representation) for candidate in candidates],
            [],
            "context" if representation == "context_first" else representation,
            vectors,
        )
        return values, {
            "status": "complete",
            "query_prefix": SEMANTIC_QUERY_PREFIX,
            "candidate_text_prefixed": False,
        }
    try:
        import tree_edit

        for name in tree_edit.METHODS:
            if method in (f"{name}_n32", f"{name}_n64"):
                return tree_edit.score_candidates_with_diagnostics(
                    name,
                    query,
                    candidates,
                    refs,
                    max_tree_nodes=int(method.rsplit("n", 1)[-1]),
                )
    except ImportError:
        pass
    items = [projected(c, representation) for c in candidates]
    references = [projected(c, representation) for c in refs]
    return methods.score_candidates(
        method,
        query,
        items,
        references,
        "context" if representation == "context_first" else representation,
        vectors,
    ), {"status": "complete"}


def _fragment_completeness(candidates, refs):
    def statuses(items):
        result = Counter()
        for candidate in items:
            subtree = candidate.get("subtree")
            if not isinstance(subtree, dict):
                result["missing_subtree"] += 1
            elif subtree.get("complete") is True:
                result["complete"] += 1
            else:
                result[str(subtree.get("status", "incomplete_subtree"))] += 1
        return dict(result)

    candidate_statuses = statuses(candidates)
    reference_statuses = statuses(refs)
    complete = set(candidate_statuses) <= {"complete"} and set(reference_statuses) <= {
        "complete"
    }
    return {
        "status": "complete" if complete else "partial",
        "candidate_subtree_statuses": candidate_statuses,
        "reference_subtree_statuses": reference_statuses,
    }


def _method_metadata(method):
    if method == PREFIXED_SEMANTIC_METHOD:
        return {
            "family": "semantic",
            "comparison": "prefixed exact field query to candidate representation",
            "reference_aggregation": "none",
        }
    if method in advanced_methods.ADVANCED_METHODS:
        return advanced_methods.ADVANCED_METHODS[method]
    if method in methods.METHOD_METADATA:
        return methods.METHOD_METADATA[method]
    try:
        import tree_edit

        for tree_method, metadata in tree_edit.METHOD_METADATA.items():
            if method in (f"{tree_method}_n32", f"{tree_method}_n64"):
                return metadata
    except ImportError:
        pass
    raise ValueError(f"unknown campaign method {method}")


def _score_cache_key(case_id, method, candidates, refs, query, representation):
    metadata = _method_metadata(method)
    family = metadata.get("family")
    representation_key = representation if family in {"lexical", "semantic"} else None
    query_key = (
        (query.get("field"), query.get("description"))
        if metadata.get("reference_aggregation") == "none"
        else None
    )
    reference_key = (
        tuple(candidate["id"] for candidate in refs)
        if metadata.get("reference_aggregation") != "none"
        else ()
    )
    return (
        case_id,
        method,
        tuple(candidate["id"] for candidate in candidates),
        reference_key,
        query_key,
        representation_key,
    )


def validate_semantic_artifact(semantic_path, needed_texts):
    """Validate exact semantic inputs, vectors and the declared model/runtime."""
    payload = Path(semantic_path).read_bytes()
    semantic = json.loads(payload)
    if not isinstance(semantic, dict):
        raise ValueError("semantic artifact must be a JSON object")
    metadata = semantic.get("metadata")
    vectors = semantic.get("vectors")
    if not isinstance(metadata, dict) or not isinstance(vectors, dict):
        raise ValueError("semantic artifact requires metadata and vectors objects")

    identity = metadata.get("identity")
    if not isinstance(identity, dict) or checksum(identity) != metadata.get(
        "identity_sha256"
    ):
        raise ValueError("semantic model/runtime identity checksum mismatch")
    if identity.get("backend") != "fastembed" or not identity.get("model"):
        raise ValueError(
            "semantic artifact does not declare its FastEmbed model identity"
        )
    runtime = identity.get("runtime")
    if (
        not isinstance(runtime, dict)
        or not runtime.get("fastembed_version")
        or not runtime.get("onnxruntime_version")
    ):
        raise ValueError("semantic artifact omits FastEmbed or ONNX Runtime version")
    dimension = metadata.get("dimension")
    if (
        not isinstance(dimension, int)
        or dimension < 1
        or runtime.get("dimension") != dimension
    ):
        raise ValueError("semantic vector dimension disagrees with model identity")

    needed = set(needed_texts)
    if set(vectors) != needed:
        missing = len(needed - set(vectors))
        extra = len(set(vectors) - needed)
        raise ValueError(
            "semantic vectors must match the frozen text set exactly "
            f"(missing={missing}, extra={extra})"
        )
    input_map = metadata.get("input_map")
    if not isinstance(input_map, dict) or set(input_map) != needed:
        raise ValueError("semantic input map does not match the frozen text set")
    if metadata.get("input_count") != len(needed) or metadata.get(
        "unique_input_count"
    ) != len(needed):
        raise ValueError(
            "semantic artifact input counts disagree with the frozen text set"
        )

    configuration = identity.get("configuration", {})
    normalized = bool(configuration.get("normalize"))
    for text in needed:
        text_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        record = input_map[text]
        if not isinstance(record, dict) or record.get("original_sha256") != text_digest:
            raise ValueError("semantic input provenance hash mismatch")
        model_input = record.get("embedding_input")
        if not isinstance(model_input, str):
            raise ValueError("semantic artifact omits the exact model input text")
        if hashlib.sha256(model_input.encode("utf-8")).hexdigest() != record.get(
            "embedding_input_sha256"
        ):
            raise ValueError("semantic model-input hash mismatch")
        vector = vectors[text]
        if not isinstance(vector, list) or len(vector) != dimension:
            raise ValueError("semantic vector has the wrong shape")
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in vector
        ):
            raise ValueError(
                "semantic vector contains a non-finite or non-numeric value"
            )
        norm = math.sqrt(sum(float(value) * float(value) for value in vector))
        if norm == 0.0:
            raise ValueError("semantic vector is zero")
        if normalized and abs(norm - 1.0) > 1e-4:
            raise ValueError("normalized semantic vector is not unit length")

    return semantic, {
        "artifact_sha256": hashlib.sha256(payload).hexdigest(),
        "identity_sha256": metadata["identity_sha256"],
        "identity": identity,
        "input_count": len(needed),
        "input_set_sha256": checksum(sorted(needed)),
        "dimension": dimension,
    }


class _BoundedScoreCache:
    """Small exact LRU for repeated method/candidate/reference combinations."""

    def __init__(self, capacity=MAX_SCORE_CACHE_ENTRIES):
        self.capacity = capacity
        self.entries = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        value = self.entries.get(key)
        if value is None:
            self.misses += 1
            return None
        self.entries.move_to_end(key)
        self.hits += 1
        return value

    def put(self, key, value):
        if key in self.entries:
            self.entries.move_to_end(key)
        self.entries[key] = value
        if len(self.entries) > self.capacity:
            self.entries.popitem(last=False)

    def clear(self):
        self.entries.clear()


def _add_bottom_k(heap, value, token):
    priority = int.from_bytes(hashlib.sha256(token).digest()[:8], "big")
    item = (-priority, int(value))
    if len(heap) < LATENCY_SAMPLE_CAP:
        heapq.heappush(heap, item)
    elif priority < -heap[0][0]:
        heapq.heapreplace(heap, item)


def _latency_quantiles(heap):
    values = sorted(item[1] for item in heap)
    if not values:
        return None, None
    p95_index = min(len(values) - 1, math.ceil(len(values) * 0.95) - 1)
    return statistics.median(values) / 1e6, values[p95_index] / 1e6


class Totals:
    def __init__(self):
        self.groups = defaultdict(
            lambda: {
                "trials": 0,
                "evaluable": 0,
                "present": 0,
                "absent": 0,
                "correct": 0,
                "owner_correct": 0,
                "false_positive": 0,
                "abstained": 0,
                "hit1": 0,
                "hit3": 0,
                "hit5": 0,
                "canonical1": 0,
                "canonical_evaluable": 0,
                "operational_present": 0,
                "operational_owner_correct": 0,
                "operational_hit1": 0,
                "operational_hit3": 0,
                "operational_hit5": 0,
                "complete_score_trials": 0,
                "incomplete_score_trials": 0,
                "score_status_counts": Counter(),
                "latency_all_heap": [],
                "latency_quality_heap": [],
                "latency_all_count": 0,
                "latency_quality_count": 0,
            }
        )

    def add(self, row):
        keys = [
            (
                row["method"],
                row["representation"],
                row["mode"],
                row["condition"],
                "all",
            ),
            (
                row["method"],
                row["representation"],
                row["mode"],
                row["condition"],
                row["field"],
            ),
        ]
        for key in keys:
            total = self.groups[key]
            status = row["score_status"]
            total["trials"] += 1
            total["score_status_counts"][status] += 1
            total["complete_score_trials"] += status == "complete"
            total["incomplete_score_trials"] += status != "complete"
            total["latency_all_count"] += 1
            sample_token = canonical(
                [
                    *key,
                    row["case"],
                    row["group"],
                    row["field"],
                    row["representation"],
                    row["mode"],
                ]
            )
            _add_bottom_k(total["latency_all_heap"], row["scoring_ns"], sample_token)

            if row["operational_present"]:
                total["operational_present"] += 1
                total["operational_owner_correct"] += bool(
                    row["operational_owner_correct"]
                )
                for k in (1, 3, 5):
                    total[f"operational_hit{k}"] += bool(row["operational_hit"][str(k)])

            if not row["evaluable"]:
                continue
            total["evaluable"] += 1
            total["latency_quality_count"] += 1
            _add_bottom_k(
                total["latency_quality_heap"], row["scoring_ns"], sample_token
            )
            present = bool(row["expected_present"])
            total["present"] += present
            total["absent"] += not present
            total["correct"] += bool(row["top1_correct"])
            total["owner_correct"] += present and bool(row["owner_correct"])
            total["false_positive"] += not present and not row["abstained"]
            total["abstained"] += bool(row["abstained"])
            for k in (1, 3, 5):
                total[f"hit{k}"] += present and bool(row["hit"][str(k)])
            if row["canonical_top1_correct"] is not None:
                total["canonical_evaluable"] += 1
                total["canonical1"] += bool(row["canonical_top1_correct"])

    def export(self):
        rows = []
        columns = ["method", "representation", "mode", "condition", "field"]
        for key, total in sorted(self.groups.items()):
            row = dict(zip(columns, key, strict=True))
            for name, value in total.items():
                if name in {"latency_all_heap", "latency_quality_heap"}:
                    continue
                row[name] = dict(value) if isinstance(value, Counter) else value
            row["accuracy"] = (
                total["correct"] / total["evaluable"] if total["evaluable"] else None
            )
            row["canonical_top1_accuracy"] = (
                total["canonical1"] / total["canonical_evaluable"]
                if total["canonical_evaluable"]
                else None
            )
            row["owner_accuracy"] = (
                total["owner_correct"] / total["present"] if total["present"] else None
            )
            row["operational_owner_accuracy"] = (
                total["operational_owner_correct"] / total["operational_present"]
                if total["operational_present"]
                else None
            )
            row["latency_quantile_basis"] = (
                "deterministic bottom-k sample by row identity; raw "
                "scoring_ns retained in rows.jsonl.gz"
            )
            row["latency_sample_cap"] = LATENCY_SAMPLE_CAP
            row["all_attempt_latency_sample_size"] = len(total["latency_all_heap"])
            row["dom_complete_latency_sample_size"] = len(total["latency_quality_heap"])
            row["all_attempt_scoring_median_ms"], row["all_attempt_scoring_p95_ms"] = (
                _latency_quantiles(total["latency_all_heap"])
            )
            (
                row["dom_complete_scoring_median_ms"],
                row["dom_complete_scoring_p95_ms"],
            ) = _latency_quantiles(total["latency_quality_heap"])
            # Keep these established names aligned with the quality-evaluable cohort.
            row["scoring_median_ms"] = row["dom_complete_scoring_median_ms"]
            row["scoring_p95_ms"] = row["dom_complete_scoring_p95_ms"]
            for k in (1, 3, 5):
                row[f"recall_at_{k}"] = (
                    total[f"hit{k}"] / total["present"] if total["present"] else None
                )
                row[f"operational_present_recall_at_{k}"] = (
                    total[f"operational_hit{k}"] / total["operational_present"]
                    if total["operational_present"]
                    else None
                )
            rows.append(row)
        return rows


def _row_quality(values, candidates, case, field, mode, root_node, score_status):
    expected = case["expected"].get(field, [])
    canonical_ids = case["canonical_expected"].get(field, [])
    actual_mode = "global" if field == "root" else mode
    result = evaluate(
        values, candidates, expected, case["owning_root_id"], actual_mode, root_node
    )
    exact = evaluate(
        values,
        candidates,
        canonical_ids,
        case["owning_root_id"],
        actual_mode,
        root_node,
    )
    expected_status = case["expected_status"][field]
    expected_present = bool(case["expected_present"][field])
    quality_evaluable = (
        expected_status in {"present_dom", "absent"} and score_status == "complete"
    )
    operational_present = expected_present and expected_status in {
        "present_dom",
        "present_unlocatable",
        "ambiguous",
        "ambiguous_dom",
    }

    if quality_evaluable:
        top1_correct = result["top1_correct"]
        hit = result["hit"]
        owner_correct = result["owner_correct"]
        reciprocal_rank = result["reciprocal_rank"]
        canonical_top1_correct = exact["top1_correct"]
        operational_hit = hit if operational_present else None
        operational_owner_correct = owner_correct if operational_present else None
    else:
        top1_correct = None
        hit = None
        owner_correct = None
        reciprocal_rank = None
        canonical_top1_correct = None
        operational_hit = (
            {"1": False, "3": False, "5": False} if operational_present else None
        )
        operational_owner_correct = False if operational_present else None

    return {
        **result,
        "expected_present": expected_present,
        "expected_status": expected_status,
        "evaluable": quality_evaluable,
        "quality_evaluable": quality_evaluable,
        "operational_present": operational_present,
        "operational_hit": operational_hit,
        "operational_owner_correct": operational_owner_correct,
        "top1_correct": top1_correct,
        "hit": hit,
        "owner_correct": owner_correct,
        "reciprocal_rank": reciprocal_rank,
        "canonical_top1_correct": canonical_top1_correct,
    }


def _write_score_event(stream, counts, samples, event):
    status = str(event.get("status", "error"))
    method = str(event.get("method", "unknown"))
    counts[(method, status)] += 1
    stream.write(canonical(event).decode("utf-8") + "\n")
    if len(samples) < MAX_FAILURE_SAMPLES:
        samples.append(event)


def run(
    output, semantic_path=None, group_filter=None, case_filter=None, split_filter=None
):
    overall_started = time.perf_counter_ns()
    config, cases = _read_frozen_bundle(output)
    semantic = None
    semantic_identity = None
    vectors = None
    if semantic_path:
        needed = _semantic_texts(
            cases,
            config["queries"],
            config["representations"],
            config["semantic_query_prefix"],
        )
        if checksum(needed) != config["semantic_input_checksum"]:
            raise ValueError("semantic input strings do not match the frozen manifest")
        semantic, semantic_identity = validate_semantic_artifact(semantic_path, needed)
        vectors = semantic["vectors"]

    output_file = output / "rows.jsonl.gz"
    failure_file = output / "failures.jsonl.gz"
    summary_file = output / "summary.json"
    if output_file.exists() or failure_file.exists() or summary_file.exists():
        raise ValueError("refusing to overwrite a completed or partial run")

    with ExactCaches() as exact_caches:
        summary = _run_scoring(
            output,
            config,
            cases,
            vectors,
            semantic,
            semantic_identity,
            exact_caches,
            overall_started,
            group_filter,
            case_filter,
            split_filter,
        )
    print(
        json.dumps(
            {
                "rows": summary["rows"],
                "score_events": summary["score_event_count"],
                "failures": summary["score_failure_count"],
                "summary": str(summary_file),
            }
        )
    )
    return summary


def _run_scoring(
    output,
    config,
    cases,
    vectors,
    semantic,
    semantic_identity,
    exact_caches,
    overall_started,
    group_filter,
    case_filter,
    split_filter,
):
    by_id = {case["id"]: case for case in cases}
    names = [
        *config["core_methods"],
        *config.get("campaign_methods", []),
        *config["advanced_methods"],
        *config["tree_methods"],
    ]
    if vectors is None:
        names = [name for name in names if not name.startswith("semantic")]

    totals = Totals()
    score_event_counts = Counter()
    score_event_samples = []
    score_cache = _BoundedScoreCache()
    score_cache_hits = 0
    score_cache_misses = 0
    rows_written = 0
    failure_file = output / "failures.jsonl.gz"
    with (
        gzip.open(output / "rows.jsonl.gz", "wt", encoding="utf-8") as rows_stream,
        gzip.open(failure_file, "wt", encoding="utf-8") as failure_stream,
    ):
        for case in cases:
            if split_filter and case["split"] != split_filter:
                continue
            if case_filter and case_filter not in case["id"]:
                continue
            for group in config["reference_groups"]:
                if group_filter and group_filter not in group["id"]:
                    continue
                seed_cases = [by_id[identity] for identity in group["cases"]]
                category = condition(case, seed_cases)
                if category == "reference_self":
                    continue
                for representation in config["representations"]:
                    roots: dict[str, str | None] = {}
                    root_statuses: dict[str, str] = {}
                    root_diagnostic_ids: dict[str, str | None] = {}
                    for field in config["field_order"]:
                        query = {
                            "field": field,
                            "description": config["queries"][field],
                        }
                        candidates = (
                            [
                                candidate
                                for candidate in case["candidates"]
                                if candidate["projection"] == "text"
                            ]
                            if field == "root"
                            else case["candidates"]
                        )
                        refs = [
                            candidate
                            for seed in seed_cases
                            for candidate in seed["candidates"]
                            if candidate["id"] in seed["expected"].get(field, [])
                        ]
                        scores: dict[str, list[float]] = {}
                        timings: dict[str, int] = {}
                        diagnostics: dict[str, dict[str, Any]] = {}
                        score_cache_hit: dict[str, bool] = {}
                        diagnostic_ids: dict[str, str] = {}

                        for method in names:
                            key = _score_cache_key(
                                case["id"],
                                method,
                                candidates,
                                refs,
                                query,
                                representation,
                            )
                            cached = score_cache.get(key)
                            if cached is not None:
                                values, diagnosis, diagnostic_id = cached
                                scores[method] = list(values)
                                diagnostics[method] = diagnosis
                                diagnostic_ids[method] = diagnostic_id
                                timings[method] = 0
                                score_cache_hit[method] = True
                                score_cache_hits += 1
                                continue

                            score_started = time.perf_counter_ns()
                            score_cache_misses += 1
                            try:
                                raw_scores, diagnosis = score(
                                    method,
                                    query,
                                    candidates,
                                    refs,
                                    representation,
                                    vectors,
                                )
                                values = list(raw_scores)
                                rank(values, candidates)
                                if not isinstance(diagnosis, dict):
                                    raise ValueError(
                                        "scorer diagnostics must be a mapping"
                                    )
                            except Exception as error:
                                values = [0.0] * len(candidates)
                                diagnosis = {
                                    "status": "error",
                                    "error_type": type(error).__name__,
                                    "error": str(error),
                                }
                            status = str(diagnosis.get("status", "error"))
                            diagnostic_id = checksum(list(key))[:16]
                            duration_ns = time.perf_counter_ns() - score_started
                            diagnostic_ref = (
                                diagnostic_id if status != "complete" else None
                            )
                            score_cache.put(
                                key, (tuple(values), diagnosis, diagnostic_ref)
                            )
                            scores[method] = values
                            diagnostics[method] = diagnosis
                            diagnostic_ids[method] = diagnostic_ref
                            timings[method] = duration_ns
                            score_cache_hit[method] = False
                            if status != "complete":
                                _write_score_event(
                                    failure_stream,
                                    score_event_counts,
                                    score_event_samples,
                                    {
                                        "case": case["id"],
                                        "group": group["id"],
                                        "field": field,
                                        "representation": representation,
                                        "method": method,
                                        "diagnostic_id": diagnostic_id,
                                        **diagnosis,
                                    },
                                )

                        hybrid_available = {
                            method
                            for method in scores
                            if diagnostics[method].get("status") == "complete"
                        }
                        for members in hybrid_variants(
                            config["channel_members"], hybrid_available
                        ):
                            for policy in config["fusion_policies"]:
                                method = f"{policy}/" + "+".join(members)
                                blend_started = time.perf_counter_ns()
                                values = blend(policy, members, scores, candidates)
                                scores[method] = values
                                timings[method] = (
                                    time.perf_counter_ns()
                                    - blend_started
                                    + sum(timings[member] for member in members)
                                )
                                diagnostics[method] = {
                                    "status": "complete",
                                    "members": list(members),
                                }
                                score_cache_hit[method] = False
                                diagnostic_ids[method] = None

                        for method, values in scores.items():
                            if method.startswith(("rrf/", "top5_union/")):
                                order = rank(values, candidates)
                            else:
                                order = rank(values, candidates)
                            if field == "root":
                                root_statuses[method] = diagnostics[method].get(
                                    "status", "error"
                                )
                                roots[method] = (
                                    candidates[order[0]]["node_id"]
                                    if order
                                    and values[order[0]] > 0
                                    and root_statuses[method] == "complete"
                                    else None
                                )
                                root_diagnostic_ids[method] = diagnostic_ids.get(method)

                            for mode in config["modes"]:
                                actual_mode = "global" if field == "root" else mode
                                effective_status = diagnostics[method].get(
                                    "status", "error"
                                )
                                if (
                                    field != "root"
                                    and actual_mode == "predicted_root"
                                    and root_statuses.get(method) != "complete"
                                ):
                                    effective_status = (
                                        f"root_{root_statuses.get(method, 'missing')}"
                                    )
                                quality = _row_quality(
                                    values,
                                    candidates,
                                    case,
                                    field,
                                    actual_mode,
                                    roots.get(method),
                                    effective_status,
                                )
                                event_id = diagnostic_ids.get(method)
                                row = {
                                    "case": case["id"],
                                    "source_id": case["source_id"],
                                    "family": case["family"],
                                    "split": case["split"],
                                    "variant": case["variant"],
                                    "condition": category,
                                    "annotation_status": config[
                                        "evaluation_disclosures"
                                    ].get("fresh_annotation_status")
                                    if case["split"] == "fresh_cross_site"
                                    else None,
                                    "group": group["id"],
                                    "representation": representation,
                                    "field": field,
                                    "method": method,
                                    "mode": mode,
                                    "evaluation_mode": actual_mode,
                                    "score_status": effective_status,
                                    "score_diagnostics_id": event_id,
                                    "root_score_diagnostics_id": (
                                        root_diagnostic_ids.get(method)
                                        if field != "root"
                                        else event_id
                                    ),
                                    "score_cache_hit": score_cache_hit.get(method),
                                    "scoring_ns": timings[method],
                                    "hybrid_time_estimated": method.startswith(
                                        ("rrf/", "top5_union/")
                                    ),
                                    **quality,
                                }
                                rows_stream.write(canonical(row).decode("utf-8") + "\n")
                                totals.add(row)
                                rows_written += 1
            score_cache.clear()
            rows_stream.flush()
            failure_stream.flush()
            print(
                json.dumps(
                    {
                        "case": case["id"],
                        "rows": rows_written,
                        "score_events": sum(score_event_counts.values()),
                    }
                ),
                flush=True,
            )

    semantic_summary = None
    if semantic_identity is not None:
        semantic_summary = {
            **semantic_identity,
            "ledger": {
                key: value
                for key, value in semantic.get("ledger", {}).items()
                if key != "batches"
            },
        }
    summary = {
        "kind": "product-retrieval-expanded-campaign-v2",
        "frozen_checksum": checksum(config),
        "corpus_checksum": config["corpus_checksum"],
        "code_identity": config["code_identity"],
        "implementation_snapshot": config["implementation_snapshot"],
        "rows": rows_written,
        "score_event_count": sum(score_event_counts.values()),
        "score_failure_count": sum(
            count
            for (_, status), count in score_event_counts.items()
            if status in {"error", "unavailable", "budget_exhausted"}
        ),
        "overall_wall_ns": time.perf_counter_ns() - overall_started,
        "score_cache": {
            "hits": score_cache_hits,
            "misses": score_cache_misses,
            "capacity": MAX_SCORE_CACHE_ENTRIES,
        },
        "exact_cache_ledger": exact_caches.ledger(),
        "semantic": semantic_summary,
        "semantic_input_checksum": config["semantic_input_checksum"],
        "evaluation_disclosures": config["evaluation_disclosures"],
        "source_provenance": config["source_provenance"],
        "score_event_counts": {
            f"{method}/{status}": count
            for (method, status), count in sorted(score_event_counts.items())
        },
        "score_event_sample": score_event_samples,
        "score_event_file": "failures.jsonl.gz",
        "filters": {"group": group_filter, "case": case_filter, "split": split_filter},
        "metrics": totals.export(),
    }
    save(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--base", type=Path, required=True)
    f.add_argument("--fresh", type=Path, required=True)
    f.add_argument("--output", type=Path, required=True)
    c = sub.add_parser("collect")
    c.add_argument("--output", type=Path, required=True)
    c.add_argument("--destination", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--output", type=Path, required=True)
    r.add_argument("--semantic", type=Path)
    r.add_argument("--group-filter")
    r.add_argument("--case-filter")
    r.add_argument("--split-filter")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.base, args.fresh, args.output)
    elif args.command == "collect":
        collect(args.output, args.destination)
    else:
        run(
            args.output,
            args.semantic,
            args.group_filter,
            args.case_filter,
            args.split_filter,
        )


if __name__ == "__main__":
    main()
