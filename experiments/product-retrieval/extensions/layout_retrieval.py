"""Compare generic live-element layout features with matched DOM/text controls."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import itertools
import json
import math
import re
import shutil
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
methods = importlib.import_module("methods")
corpus = importlib.import_module("corpus")
pool = importlib.import_module("complementarity").pool

FIELDS = {
    "name": "Product heading naming the item offered for purchase",
    "price": "Current displayed purchase price including currency",
    "stock": "Product availability prose or quantity in stock",
}
GROUPS = {
    "geometry": ("x", "y", "width", "height"),
    "parent_geometry": ("parent_x", "parent_y", "parent_width", "parent_height"),
    "font": ("font_relative_log", "weight", "italic", "line_height"),
    "color": ("red", "green", "blue"),
}
LAYOUT = {
    "layout_geometry": ("geometry",),
    "layout_parent_geometry": ("parent_geometry",),
    "layout_font": ("font",),
    "layout_color": ("color",),
    "layout_geometry_typography": ("geometry", "font"),
    "layout_parent_typography": ("parent_geometry", "font"),
}
CONTROLS = (
    ("structural_jaccard", "context"),
    ("hierarchical_jaccard", "context"),
    ("local_jaccard", "context"),
    ("lexical_char_ngram_cosine_reference", "value"),
    ("lexical_char_ngram_cosine_reference", "context"),
    ("lexical_char_ngram_cosine_query", "value"),
    ("lexical_char_ngram_cosine_query", "context"),
    ("lexical_tfidf_cosine_reference", "value"),
    ("lexical_tfidf_cosine_reference", "context"),
    ("bm25", "context"),
    ("lexical_bm25_reference", "context"),
)
CHANNELS = {
    "structure": "structural_jaccard/context",
    "lexical": "lexical_char_ngram_cosine_reference/context",
    "layout": "layout_parent_typography",
}
BUDGETS = (1, 3, 5, 10, 15)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def px(value):
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))px", str(value))
    return float(match[1]) if match else None


def build_candidates(layout):
    """Use source geometry/text eligibility only, without field annotations."""
    nodes = {row["ordinal"]: row for row in layout["nodes"]}
    if len(nodes) != len(layout["nodes"]) or len(nodes) > 2000:
        raise ValueError("invalid or over-budget element identity set")
    parents = {key: row["parentOrdinal"] for key, row in nodes.items()}
    children = defaultdict(list)
    ancestors = {}
    for key, parent in parents.items():
        if parent is not None and parent not in nodes:
            raise ValueError("missing captured parent")
        children[parent].append(key)
        chain = []
        current = parent
        while current is not None:
            if current == key or current in chain or len(chain) >= 256:
                raise ValueError("invalid or over-budget element ancestry")
            chain.append(current)
            current = parents[current]
        ancestors[key] = chain

    def eligible(row):
        box, style = row["box"], row["styles"]
        if not all(math.isfinite(box[k]) for k in ("x", "y", "width", "height")):
            raise ValueError("nonfinite captured geometry")
        if (
            not row["text"].strip()
            or box["width"] <= 0
            or box["height"] <= 0
            or style["display"] == "none"
            or style["visibility"] != "visible"
        ):
            return False
        return all(
            float(nodes[a]["styles"]["opacity"]) > 0
            for a in [row["ordinal"], *ancestors[row["ordinal"]]]
        )

    retained = [row for row in layout["nodes"] if eligible(row)]
    sizes = [
        value
        for row in retained
        if (value := px(row["styles"]["font-size"])) is not None and value > 0
    ]
    median = statistics.median(sizes) if sizes else None
    width, height = layout["viewport"]["width"], layout["viewport"]["height"]
    if width <= 0 or height <= 0:
        raise ValueError("invalid viewport")
    wire = {
        key: {"kind": "element", "tag_name": row["tag"], "children": children[key]}
        for key, row in nodes.items()
    }
    index = {
        "nodes": wire,
        "parents": parents,
        "text": {key: row["text"] for key, row in nodes.items()},
    }
    result = []
    for row in retained:
        key, box, style = row["ordinal"], row["box"], row["styles"]
        parent = nodes.get(parents[key])
        features = {
            "x": box["x"] / width,
            "y": box["y"] / height,
            "width": box["width"] / width,
            "height": box["height"] / height,
        }
        if parent and parent["box"]["width"] > 0 and parent["box"]["height"] > 0:
            p = parent["box"]
            features.update(
                parent_x=(box["x"] - p["x"]) / p["width"],
                parent_y=(box["y"] - p["y"]) / p["height"],
                parent_width=box["width"] / p["width"],
                parent_height=box["height"] / p["height"],
            )
        size = px(style["font-size"])
        if size and size > 0 and median:
            features["font_relative_log"] = math.log(size / median)
            line = px(style["line-height"])
            if line is not None:
                features["line_height"] = line / size
        weight = style["font-weight"]
        if re.fullmatch(r"\d+(?:\.\d+)?", weight):
            features["weight"] = float(weight) / 1000
        features["italic"] = float(style["font-style"] != "normal")
        color = re.fullmatch(r"rgba?\(([^)]+)\)", style["color"])
        if color:
            values = [float(value.strip()) for value in color[1].split(",")]
            if len(values) in (3, 4):
                features.update(
                    zip(
                        ("red", "green", "blue"),
                        [v / 255 for v in values[:3]],
                        strict=True,
                    )
                )
        if not all(math.isfinite(v) for v in features.values()):
            raise ValueError("nonfinite derived feature")
        attrs = {a["name"]: a["value"] for a in row["attributes"]}
        result.append(
            {
                "id": f"element:{key:06d}",
                "ordinal": key,
                "node_id": str(key),
                "projection": "text",
                "text": row["text"],
                "context": parent["text"] if parent else "",
                "tag": row["tag"],
                "attributes": attrs,
                "path": [
                    re.sub(r"\[\d+\]$", "", part) for part in row["path"].split("/")
                ],
                "motifs": corpus._motifs(key, {}, index, attrs),
                "ancestors": [str(value) for value in ancestors[key]],
                "layout_features": features,
                "text_truncated": row["textTruncated"],
            }
        )
    return result


def layout_scores(name, candidates, references):
    """Equal family weights; mean shared-dimension L1; max seed similarity."""
    groups = LAYOUT[name]

    def similarity(left, right):
        a, b = left["layout_features"], right["layout_features"]
        distances = []
        for group in groups:
            keys = [key for key in GROUPS[group] if key in a and key in b]
            if keys:
                distances.append(sum(abs(a[key] - b[key]) for key in keys) / len(keys))
        return 1 / (1 + statistics.mean(distances)) if distances else 0.0

    return [
        max((similarity(c, r) for r in references), default=0.0) for c in candidates
    ]


def implementation():
    paths = [
        HERE / "layout_retrieval.py",
        HERE / "complementarity.py",
        HERE / "evaluate_witnesses.py",
        HERE.parent / "methods.py",
        HERE.parent / "corpus.py",
    ]
    return {str(p.relative_to(HERE.parent)): sha(p) for p in paths}


def freeze(captures, output):
    if output.exists():
        raise ValueError("freeze requires a new directory")
    started_cpu, started_wall = time.process_time_ns(), time.perf_counter_ns()
    source = json.loads((captures / "summary.json").read_text())
    cases = []
    for page in source["pages"]:
        directory = captures / page["case_id"]
        files = {
            "element-layout.json": page["element_layout"]["sha256"],
            "rendered-dom.html": page["rendered_dom"]["sha256"],
            "viewport.png": page["screenshot"]["sha256"],
        }
        for filename, expected in files.items():
            if sha(directory / filename) != expected:
                raise ValueError("retained capture changed")
        layout = json.loads((directory / "element-layout.json").read_text())
        candidates = build_candidates(layout)
        cases.append(
            {
                "id": page["case_id"],
                "source_hashes": files,
                "candidates": candidates,
                "feature_availability": {
                    key: sum(key in c["layout_features"] for c in candidates)
                    for keys in GROUPS.values()
                    for key in keys
                },
                "truncated_text_candidates": sum(
                    c["text_truncated"] for c in candidates
                ),
                "captured_elements": len(layout["nodes"]),
                "viewport": layout["viewport"],
                "source_elements": [
                    {
                        key: row[key]
                        for key in ("ordinal", "path", "text", "textTruncated")
                    }
                    for row in layout["nodes"]
                ],
                "manifest_sha256": sha(directory / "manifest.json"),
            }
        )
    profile = {
        "kind": "live-layout-retrieval-profile-v1",
        "fields": FIELDS,
        "layout_groups": GROUPS,
        "layout_methods": LAYOUT,
        "controls": CONTROLS,
        "pool_channels": CHANNELS,
        "budgets": BUDGETS,
        "implementation": implementation(),
        "capture_summary_sha256": sha(captures / "summary.json"),
        "candidate_sha256": hashlib.sha256(canonical(cases)).hexdigest(),
        "preparation_cpu_ns": time.process_time_ns() - started_cpu,
        "preparation_wall_ns": time.perf_counter_ns() - started_wall,
        "scoring": (
            "Max canonical-seed similarity; fixed equal family "
            "weights; no learned weights."
        ),
        "eligibility": (
            "Nonempty captured text, positive CSS box, visible "
            "CSS visibility and positive ancestor opacity; "
            "off-viewport retained, occlusion not certified."
        ),
        "timing_of_choices": (
            "Feature/profile choices specified before reading "
            "annotation file; annotator delivered "
            "canonical-ordinal summary before formal source "
            "freeze. Operators are not blind. No ranked results "
            "used to choose this profile."
        ),
        "evaluation": (
            "Element-node localization only; no attribute "
            "projection, runtime Contract acceptance, semantic "
            "truth or discovery steps."
        ),
    }
    output.mkdir(parents=True)
    (output / "profile.json").write_bytes(canonical(profile))
    (output / "candidates.json").write_bytes(canonical(cases))
    for name in profile["implementation"]:
        target = output / "implementation" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE.parent / name, target)
    print(
        json.dumps(
            {
                "cases": len(cases),
                "eligible_candidates": sum(len(c["candidates"]) for c in cases),
            }
        )
    )


def quality(ids, gold, candidates):
    selected = set(ids)
    canonical_gold = {f"element:{int(v):06d}" for v in gold["canonical_ordinals"]}
    qualified = canonical_gold | {
        f"element:{int(v):06d}" for v in gold["qualified_alternative_ordinals"]
    }
    return {
        "status": gold["status"],
        "canonical_hit": bool(selected & canonical_gold),
        "qualified_hit": bool(selected & qualified),
        "nonempty": bool(ids),
        "candidate_count": len(ids),
        "context_bytes": sum(len(candidates[key]["context"].encode()) for key in ids),
        "gold_in_universe": bool(canonical_gold & candidates.keys()),
    }


def tie_hit_bounds(scores, candidates, gold_ids, budget):
    """Probability of at least one witness under uniform exact-score ties."""
    positive = sorted((s for s in scores if s > 0), reverse=True)
    k = min(budget, len(positive))
    if k == 0:
        return {"expected": 0.0, "worst": 0, "best": 0}
    boundary = positive[k - 1]
    higher = {c["id"] for c, s in zip(candidates, scores, strict=True) if s > boundary}
    if higher & gold_ids:
        return {"expected": 1.0, "worst": 1, "best": 1}
    tied = {c["id"] for c, s in zip(candidates, scores, strict=True) if s == boundary}
    n, g, slots = len(tied), len(tied & gold_ids), k - len(higher)
    miss = math.comb(n - g, slots) / math.comb(n, slots) if slots <= n - g else 0
    return {"expected": 1 - miss, "worst": int(slots > n - g), "best": int(g > 0)}


def verify_labels(cases, gold_cases):
    names = {
        "element-layout.json": "element_layout_sha256",
        "rendered-dom.html": "rendered_dom_sha256",
        "viewport.png": "viewport_png_sha256",
    }
    for case in cases:
        annotation = gold_cases[case["id"]]
        for filename, digest in case["source_hashes"].items():
            if annotation["hashes"][names[filename]] != digest:
                raise ValueError("annotation belongs to a different live capture")
        if annotation["hashes"]["manifest_sha256"] != case["manifest_sha256"]:
            raise ValueError("annotation manifest binding differs")
        source = {row["ordinal"]: row for row in case["source_elements"]}
        for field in FIELDS:
            gold = annotation["fields"][field]
            if gold["status"] not in {"present_dom", "absent", "unresolved"}:
                raise ValueError("unknown target annotation status")
            selected = (
                gold["canonical_ordinals"] + gold["qualified_alternative_ordinals"]
            )
            if len(selected) != len(set(selected)):
                raise ValueError("duplicate canonical/alternative ordinal")
            if bool(gold["canonical_ordinals"]) != (gold["status"] == "present_dom"):
                raise ValueError("target status and canonical coordinates disagree")
            evidence = {
                e["ordinal"]: e
                for e in gold["evidence"]
                if e["classification"]
                in {"canonical", "qualified_same_role_alternative"}
            }
            for ordinal in selected:
                row, witness = source[ordinal], evidence[ordinal]
                if (
                    row["path"] != witness["path"]
                    or row["textTruncated"]
                    or row["text"] != witness["exact_text"]
                    or row["text"] != gold["exact_value"]
                ):
                    raise ValueError(
                        "annotation role/value coordinate disagrees with source"
                    )


def load_frozen(frozen):
    profile = json.loads((frozen / "profile.json").read_text())
    if profile["implementation"] != implementation():
        raise ValueError("scoring implementation changed after freeze")
    cases = json.loads((frozen / "candidates.json").read_text())
    if hashlib.sha256(canonical(cases)).hexdigest() != profile["candidate_sha256"]:
        raise ValueError("frozen candidate evidence changed")
    return profile, cases


def comparison_condition(target, seed):
    different_viewport = target["viewport"] != seed["viewport"]
    if target["id"] == seed["id"]:
        if target["source_hashes"] == seed["source_hashes"]:
            return "self_diagnostic"
        return (
            "same_page_viewport_shift"
            if different_viewport
            else "same_page_new_capture"
        )
    return "cross_template_viewport_shift" if different_viewport else "cross_template"


def run(frozen, annotations, output, seeds=None, seed_annotations=None):
    if output.exists():
        raise ValueError("run requires a new output directory")
    started_cpu, started_wall = time.process_time_ns(), time.perf_counter_ns()
    profile, cases = load_frozen(frozen)
    labels = json.loads(annotations.read_text())
    gold_cases = labels["cases"]
    verify_labels(cases, gold_cases)
    if (seeds is None) != (seed_annotations is None):
        raise ValueError("seed corpus and annotations must be supplied together")
    seed_cases = cases if seeds is None else load_frozen(seeds)[1]
    seed_gold_cases = (
        gold_cases
        if seeds is None
        else json.loads(seed_annotations.read_text())["cases"]
    )
    verify_labels(seed_cases, seed_gold_cases)
    output.mkdir(parents=True)
    totals = defaultdict(lambda: defaultdict(int))
    methods_used = [*LAYOUT, *(f"{m}/{r}" for m, r in CONTROLS)]
    orders = [
        order
        for width in (1, 2, 3)
        for order in itertools.permutations(CHANNELS, width)
    ]
    rows_written = 0
    with gzip.open(output / "rows.jsonl.gz", "wt") as stream:
        for target in cases:
            candidates = target["candidates"]
            by_id = {c["id"]: c for c in candidates}
            for seed in seed_cases:
                seed_by_ord = {c["ordinal"]: c for c in seed["candidates"]}
                for field, description in FIELDS.items():
                    seed_gold = seed_gold_cases[seed["id"]]["fields"][field]
                    refs = [
                        seed_by_ord[o]
                        for o in seed_gold["canonical_ordinals"]
                        if o in seed_by_ord
                    ]
                    condition = comparison_condition(target, seed)
                    rankings = {}
                    score_vectors = {}
                    scorer_timing = {}
                    for name in methods_used:
                        tick = time.perf_counter_ns()
                        if name in LAYOUT:
                            scores = layout_scores(name, candidates, refs)
                        else:
                            method, representation = name.split("/")
                            scores = methods.score_candidates(
                                method,
                                {"field": field, "description": description},
                                candidates,
                                refs,
                                representation,
                            )
                        if len(scores) != len(candidates) or any(
                            not math.isfinite(s) or s < 0 for s in scores
                        ):
                            raise ValueError("invalid scorer output")
                        scorer_timing[name] = time.perf_counter_ns() - tick
                        score_vectors[name] = scores
                        order = sorted(
                            range(len(scores)),
                            key=lambda i: (-scores[i], candidates[i]["id"]),
                        )
                        rankings[name] = [
                            candidates[i]["id"] for i in order if scores[i] > 0
                        ][:15]
                    target_gold = gold_cases[target["id"]]["fields"][field]
                    configurations = [
                        (name, name, rankings[name]) for name in methods_used
                    ]
                    members = {
                        key: rankings[value][:5] for key, value in CHANNELS.items()
                    }
                    configurations += [
                        (
                            "pool/" + "+".join(order),
                            "fixed_pool",
                            pool(members, order, 15),
                        )
                        for order in orders
                    ]
                    for policy, kind, ranking in configurations:
                        for budget in BUDGETS:
                            result = quality(ranking[:budget], target_gold, by_id)
                            row = {
                                "target": target["id"],
                                "seed": seed["id"],
                                "field": field,
                                "condition": condition,
                                "method": policy,
                                "kind": kind,
                                "budget": budget,
                                "seed_has_eligible_reference": bool(refs),
                                "proposal_ids": ranking[:budget],
                                **result,
                            }
                            if kind != "fixed_pool":
                                row["scoring_ns"] = scorer_timing[policy]
                                ids = {
                                    f"element:{int(o):06d}"
                                    for o in target_gold["canonical_ordinals"]
                                }
                                for version, witnesses in (
                                    ("canonical", ids),
                                    (
                                        "qualified",
                                        ids
                                        | {
                                            f"element:{int(o):06d}"
                                            for o in target_gold[
                                                "qualified_alternative_ordinals"
                                            ]
                                        },
                                    ),
                                ):
                                    bounds = tie_hit_bounds(
                                        score_vectors[policy],
                                        candidates,
                                        witnesses,
                                        budget,
                                    )
                                    row.update(
                                        {
                                            f"tie_{version}_{k}": v
                                            for k, v in bounds.items()
                                        }
                                    )
                            stream.write(canonical(row).decode() + "\n")
                            rows_written += 1
                            for seed_filter in (
                                "all",
                                "seed_reference_available"
                                if refs
                                else "seed_reference_missing",
                            ):
                                key = condition, policy, budget, seed_filter
                                count = totals[key]
                                count["trials"] += 1
                                count["proposals"] += result["candidate_count"]
                                count["context_bytes"] += result["context_bytes"]
                                status = result["status"]
                                count[status] += 1
                                if status == "present_dom":
                                    count["canonical_hit"] += result["canonical_hit"]
                                    count["qualified_hit"] += result["qualified_hit"]
                                    count["gold_in_universe"] += result[
                                        "gold_in_universe"
                                    ]
                                    for key, value in row.items():
                                        if key.startswith("tie_"):
                                            count[key] += value
                                elif status == "absent":
                                    count["absent_nonempty"] += result["nonempty"]
    metrics = [
        {
            "condition": key[0],
            "method": key[1],
            "budget": key[2],
            "seed_filter": key[3],
            **dict(value),
        }
        for key, value in sorted(totals.items())
    ]
    report = {
        "kind": "live-layout-retrieval-results-v1",
        "rows": rows_written,
        "profile_sha256": sha(frozen / "profile.json"),
        "annotation_sha256": sha(annotations),
        "seed_profile_sha256": sha(
            (frozen if seeds is None else seeds) / "profile.json"
        ),
        "seed_annotation_sha256": sha(
            annotations if seeds is None else seed_annotations
        ),
        "metrics": metrics,
        "analysis_cpu_ns": time.process_time_ns() - started_cpu,
        "analysis_wall_ns": time.perf_counter_ns() - started_wall,
        "model_inference_calls": 0,
        "network_calls": 0,
        "notes": [
            "Field trials share four source pages and are not independent.",
            "Self matches are diagnostic only and excluded from transfer comparisons.",
            (
                "Pools are fixed top-five channel unions; scalar "
                "methods may return fifteen candidates."
            ),
            (
                "Per-row scoring time repeats for different budgets; "
                "do not sum it as execution cost."
            ),
            (
                "Geometry and text are from one viewport per page; no"
                " layout generalization claim beyond this cohort."
            ),
        ],
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "rows": rows_written,
                "metric_groups": len(metrics),
                "cpu_seconds": report["analysis_cpu_ns"] / 1e9,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run"))
    parser.add_argument("--captures", type=Path)
    parser.add_argument("--frozen", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--seeds", type=Path)
    parser.add_argument("--seed-labels", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.captures, args.output)
    else:
        run(args.frozen, args.labels, args.output, args.seeds, args.seed_labels)
