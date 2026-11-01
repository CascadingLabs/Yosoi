"""Matched MiniLM one-versus-two-reference wave on three heldout templates.

The /2 cohort reuses certified same-site shards. Only its matching /1 shards
are run; embeddings are loaded from the frozen local artifact, with no new
embedding inference. Aggregates and timing populations remain separate.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import combinations, permutations
from pathlib import Path
from typing import Any

from complementarity import pool as fixed_pool

ROOT = Path(__file__).resolve().parents[3]
PRODUCT_ROOT = ROOT / "experiments" / "product-retrieval"
EXTENSIONS = PRODUCT_ROOT / "extensions"
SOURCE = ROOT / ".generated" / "product-retrieval-expanded-v1"
MODEL_ARTIFACT = (
    ROOT / ".generated" / "product-retrieval-expanded-input" / "minilm-v1.json"
)
SAME_SITE_ROOT = ROOT / ".generated" / "product-retrieval-same-site-v1"
SAME_SITE_TARGET_PLAN = SAME_SITE_ROOT / "target-plan.json"
SAME_SITE_WAVE = SAME_SITE_ROOT / "same-site-view" / "wave-complete.json"
OUTPUT_ROOT = ROOT / ".generated" / "product-retrieval-layout-pool-ablation-v1"
RECOVERY_OUTPUT_ROOT = ROOT / ".generated" / "product-retrieval-layout-pool-ablation-v2"
EXPECTED_V1_PLAN_SHA256 = (
    "53de52574ca01c70ff707adf5b9319630588298931037755e8fc154a7722df9d"
)
EXPECTED_V1_PROPOSALS_SHA256 = (
    "653dfb1261b01b6f5d8897d2d2b794e74c80042f1f62766b41ca117b4a616b63"
)
SPLIT = "fresh_cross_site"
CONTROL_CHANNELS = (
    ("structure", "structural_jaccard/context"),
    ("lexical", "lexical_char_ngram_cosine_reference/context"),
)
BUDGETS = (1, 3, 5, 10, 15)
GATE_STATUS = "post_hoc_hypothesis_not_heldout_validated"


def sha256_file(path: Path) -> str:
    """Hash one frozen source, result, or capture file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_checksum(value: Any) -> str:
    """Use the expanded-v1 campaign's canonical JSON checksum convention."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _layout_candidate_checksum(value: Any) -> str:
    """Match layout_retrieval.canonical, which uses json's ASCII escaping default."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def select_matched_targets(
    target_plan: Mapping[str, Any], frozen: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Choose the first already-declared heldout for each fresh template."""
    groups = {str(group["id"]): group for group in frozen.get("reference_groups", [])}
    selected: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for target in target_plan.get("targets", []):
        family = str(target["family"])
        if family in seen_families:
            continue
        case_id = str(target["case"])
        one_id, two_id = f"{family}/1", f"{family}/2"
        if str(target.get("group")) != two_id:
            raise ValueError(f"same-site heldout is not in its /2 group: {case_id}")
        one, two = groups.get(one_id), groups.get(two_id)
        if one is None or two is None:
            raise ValueError(f"reference groups are missing for {family}")
        one_cases, two_cases = list(one.get("cases", [])), list(two.get("cases", []))
        if len(one_cases) != 1 or len(two_cases) != 2:
            raise ValueError(f"expected one and two frozen references for {family}")
        if not set(one_cases) < set(two_cases):
            raise ValueError(f"/1 is not a strict subset of /2 for {family}")
        if case_id in one_cases or case_id in two_cases:
            raise ValueError(f"target is not disjoint from references: {case_id}")
        selected.append(
            {
                "case": case_id,
                "family": family,
                "one_reference_group": one_id,
                "one_reference_cases": one_cases,
                "two_reference_group": two_id,
                "two_reference_cases": two_cases,
                "selection_rule": (
                    "first target in the existing same-site target-plan order "
                    "for this family"
                ),
            }
        )
        seen_families.add(family)
    if len(selected) != 3:
        raise ValueError(f"expected three fresh templates, selected {len(selected)}")
    return selected


def build_pool_specs(
    layout_variants: Sequence[str], control_channels: Sequence[str]
) -> list[dict[str, Any]]:
    """Enumerate all requested ordered subsets containing each layout channel."""
    if len(set(layout_variants)) != len(layout_variants):
        raise ValueError("layout variants must be unique")
    if len(control_channels) != 2 or len(set(control_channels)) != 2:
        raise ValueError("this ablation requires exactly two shared controls")
    specs: list[dict[str, Any]] = []
    for variant in layout_variants:
        channels = ("layout", *control_channels)
        for size in (1, 2, 3):
            for subset in combinations(channels, size):
                if "layout" not in subset:
                    continue
                for order in permutations(subset):
                    specs.append(
                        {
                            "policy_type": "layout_pool",
                            "layout_variant": variant,
                            "channel_order": list(order),
                            "policy_id": f"{variant}::{'|'.join(order)}",
                        }
                    )
    for size in (1, 2):
        for subset in combinations(control_channels, size):
            for order in permutations(subset):
                specs.append(
                    {
                        "policy_type": "shared_control",
                        "layout_variant": None,
                        "channel_order": list(order),
                        "policy_id": f"control::{'|'.join(order)}",
                    }
                )
    if len(specs) != len(layout_variants) * 11 + 4:
        raise AssertionError(
            "pool policy enumeration does not match the declared design"
        )
    return specs


def fixed_round_robin_pool(
    rankings: Mapping[str, Sequence[str]], channel_order: Sequence[str], budget: int
) -> list[str]:
    """Use the existing fixed top-five round-robin union, with ID deduplication."""
    return fixed_pool(rankings, list(channel_order), budget)


def viewport_gate_variant(
    target_viewport: Mapping[str, Any], seed_viewport: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the explicitly post-hoc exact-viewport sensitivity hypothesis."""
    equal = dict(target_viewport) == dict(seed_viewport)
    return {
        "layout_variant": "layout_geometry" if equal else "layout_parent_typography",
        "viewport_equal": equal,
        "status": GATE_STATUS,
        "selection_source": (
            "exact viewport metadata only; no field labels or gold values"
        ),
    }


def _load_profile_bundle(
    view: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    if view not in {"wide", "narrow"}:
        raise ValueError(f"unknown layout view: {view}")
    profile_dir = ROOT / ".generated" / f"product-retrieval-layout-frozen-{view}-v3"
    profile_path, candidates_path = (
        profile_dir / "profile.json",
        profile_dir / "candidates.json",
    )
    profile, page_rows = (
        json.loads(profile_path.read_text()),
        json.loads(candidates_path.read_text()),
    )
    if _layout_candidate_checksum(page_rows) != profile.get("candidate_sha256"):
        raise ValueError(f"frozen {view} candidate checksum mismatch")
    implementation_mismatches = []
    for relative, expected in profile.get("implementation", {}).items():
        path = profile_dir / "implementation" / relative
        if not path.is_file() or sha256_file(path) != expected:
            implementation_mismatches.append(relative)
    if implementation_mismatches:
        raise ValueError(
            f"frozen {view} implementation changed: {implementation_mismatches[:3]}"
        )
    captures = (
        ROOT
        / ".generated"
        / (
            "product-retrieval-layout-v1"
            if view == "wide"
            else "product-retrieval-layout-narrow-v1"
        )
    )
    if sha256_file(captures / "summary.json") != profile.get("capture_summary_sha256"):
        raise ValueError(f"frozen {view} capture summary hash mismatch")
    pages = {str(page["id"]): page for page in page_rows}
    if len(pages) != len(page_rows) or len(pages) != 4:
        raise ValueError(f"frozen {view} should contain four unique capture pages")
    return (
        profile,
        pages,
        {
            "profile_path": profile_path,
            "candidates_path": candidates_path,
            "capture_summary_path": captures / "summary.json",
            "profile_sha256": sha256_file(profile_path),
            "candidates_raw_sha256": sha256_file(candidates_path),
            "candidate_canonical_sha256": _layout_candidate_checksum(page_rows),
            "capture_summary_sha256": sha256_file(captures / "summary.json"),
            "candidate_page_count": len(pages),
            "eligible_candidate_count": sum(
                len(page["candidates"]) for page in page_rows
            ),
            "captured_element_count": sum(
                len(page["source_elements"]) for page in page_rows
            ),
        },
    )


def _load_raw_channel_rows(
    cohort: str,
    target_pages: Mapping[str, Mapping[str, Any]],
    seed_pages: Mapping[str, Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[str, Any]]:
    directory = ROOT / ".generated" / f"product-retrieval-layout-{cohort}-v1"
    rows_path, summary_path = directory / "rows.jsonl.gz", directory / "summary.json"
    summary_hash = sha256_file(summary_path)
    channel_methods = {
        "layout_geometry",
        "layout_font",
        "layout_color",
        "layout_parent_geometry",
        "layout_geometry_typography",
        "layout_parent_typography",
        "structural_jaccard/context",
        "lexical_char_ngram_cosine_reference/context",
    }
    base: dict[tuple[str, str, str], dict[str, Any]] = {}
    row_count = 0
    selected_count = 0
    method_rows = 0
    with gzip.open(rows_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            row_count += 1
            if row.get("budget") != 5 or row.get("method") not in channel_methods:
                continue
            target, seed, field = (
                str(row["target"]),
                str(row["seed"]),
                str(row["field"]),
            )
            if target not in target_pages or seed not in seed_pages:
                raise ValueError(
                    "raw row case outside frozen candidate profile: "
                    f"{cohort}/{target}/{seed}"
                )
            trial_key = (target, seed, field)
            trial = base.setdefault(
                trial_key,
                {
                    "cohort": cohort,
                    "target": target,
                    "seed": seed,
                    "field": field,
                    "condition": str(row["condition"]),
                    "rankings": {},
                    "target_candidate_count": len(target_pages[target]["candidates"]),
                },
            )
            if trial["condition"] != row["condition"]:
                raise ValueError(f"condition disagrees among channel rows: {trial_key}")
            if trial["target_candidate_count"] != len(
                target_pages[target]["candidates"]
            ):
                raise ValueError(f"target candidate pool changed: {trial_key}")
            ids = [str(candidate_id) for candidate_id in row["proposal_ids"]]
            if len(ids) > 5 or len(ids) != len(set(ids)):
                raise ValueError(
                    f"saved top-five list is malformed: {trial_key}/{row['method']}"
                )
            candidate_ids = {
                str(candidate["id"]) for candidate in target_pages[target]["candidates"]
            }
            if set(ids) - candidate_ids:
                raise ValueError(
                    "saved proposal outside target profile pool: "
                    f"{trial_key}/{row['method']}"
                )
            if row["method"] in trial["rankings"]:
                raise ValueError(
                    f"duplicate channel top-five row: {trial_key}/{row['method']}"
                )
            trial["rankings"][str(row["method"])] = ids
            selected_count += 1
            method_rows += 1
    if row_count != int(summary.get("rows", -1)):
        raise ValueError(f"raw row count mismatch in {cohort}: {row_count}")
    expected_methods = channel_methods
    for trial_key, trial in base.items():
        if set(trial["rankings"]) != expected_methods:
            raise ValueError(
                f"channel top-five universe incomplete for {cohort}/{trial_key}"
            )
    if len(base) != 48 or selected_count != 48 * len(expected_methods):
        raise ValueError(
            f"expected 48 base trials and 8 channel rankings per trial in {cohort}"
        )
    return base, {
        "rows_path": str(rows_path.relative_to(ROOT)),
        "rows_sha256": sha256_file(rows_path),
        "summary_path": str(summary_path.relative_to(ROOT)),
        "summary_sha256": summary_hash,
        "raw_row_count": row_count,
        "base_trial_count": len(base),
        "channel_rank_rows_used": method_rows,
        "channel_methods": sorted(expected_methods),
    }


def _build_proposals(
    cohorts: Mapping[str, dict[str, Any]],
    layout_variants: Sequence[str],
    specs: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    proposal_rows: list[dict[str, Any]] = []
    per_cohort_counts = {}
    for cohort, cohort_data in cohorts.items():
        trials = cohort_data["trials"]
        target_pages = cohort_data["target_pages"]
        seed_pages = cohort_data["seed_pages"]
        cohort_start = len(proposal_rows)
        for trial in trials.values():
            target_page = target_pages[trial["target"]]
            seed_page = seed_pages[trial["seed"]]
            rankings_by_alias = {
                "structure": trial["rankings"]["structural_jaccard/context"],
                "lexical": trial["rankings"][
                    "lexical_char_ngram_cosine_reference/context"
                ],
            }
            specs_for_trial = []
            for spec in specs:
                layout_variant = spec["layout_variant"]
                rankings = dict(rankings_by_alias)
                if layout_variant is not None:
                    rankings["layout"] = trial["rankings"][layout_variant]
                specs_for_trial.append((spec, rankings))
            gate = viewport_gate_variant(target_page["viewport"], seed_page["viewport"])
            gate_rankings = {"layout": trial["rankings"][gate["layout_variant"]]}
            specs_for_trial.append(
                (
                    {
                        "policy_type": "posthoc_viewport_gate",
                        "layout_variant": gate["layout_variant"],
                        "channel_order": ["layout"],
                        "policy_id": "posthoc_viewport_gate",
                        "gate": gate,
                    },
                    gate_rankings,
                )
            )
            for spec, rankings in specs_for_trial:
                order = tuple(spec["channel_order"])
                source_methods = [
                    spec["layout_variant"]
                    if channel == "layout"
                    else (
                        "structural_jaccard/context"
                        if channel == "structure"
                        else "lexical_char_ngram_cosine_reference/context"
                    )
                    for channel in order
                ]
                full_pool = fixed_round_robin_pool(rankings, order, max(BUDGETS))
                if len(full_pool) != len(set(full_pool)):
                    raise AssertionError("fixed pool did not deduplicate candidate IDs")
                for budget in BUDGETS:
                    proposals = full_pool[:budget]
                    proposal_rows.append(
                        {
                            "cohort": cohort,
                            "condition": trial["condition"],
                            "target": trial["target"],
                            "seed": trial["seed"],
                            "field": trial["field"],
                            "policy_id": spec["policy_id"],
                            "policy_type": spec["policy_type"],
                            "layout_variant": spec["layout_variant"],
                            "channel_order": list(order),
                            "source_method_order": source_methods,
                            "budget": budget,
                            "proposal_ids": proposals,
                            "proposal_count": len(proposals),
                            "target_candidate_universe_size": trial[
                                "target_candidate_count"
                            ],
                            "target_candidate_universe_fraction": (
                                len(proposals) / trial["target_candidate_count"]
                                if trial["target_candidate_count"]
                                else 0.0
                            ),
                            "posthoc_gate_status": (
                                gate["status"]
                                if spec["policy_type"] == "posthoc_viewport_gate"
                                else None
                            ),
                            "target_gold_read": False,
                        }
                    )
        per_cohort_counts[cohort] = len(proposal_rows) - cohort_start
    return proposal_rows, per_cohort_counts


def _evaluate_pool_coverage(
    proposal_rows: Sequence[Mapping[str, Any]],
    cohorts: Mapping[str, Mapping[str, Any]],
    gold_by_view: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    totals: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in proposal_rows:
        cohort = str(row["cohort"])
        bundle = cohorts[cohort]
        label = gold_by_view[bundle["target_view"]]["cases"][str(row["target"])][
            "fields"
        ][str(row["field"])]
        page = bundle["target_pages"][str(row["target"])]
        candidate_ids = {str(candidate["id"]) for candidate in page["candidates"]}
        canonical_ids = {
            f"element:{int(ordinal):06d}"
            for ordinal in label.get("canonical_ordinals", [])
        }
        qualified_ids = canonical_ids | {
            f"element:{int(ordinal):06d}"
            for ordinal in label.get("qualified_alternative_ordinals", [])
        }
        proposals = {str(candidate_id) for candidate_id in row["proposal_ids"]}
        if proposals - candidate_ids:
            raise ValueError(
                "pool proposal outside target universe: "
                f"{cohort}/{row['target']}/{row['field']}"
            )
        absent_nonempty_pool = label["status"] == "absent" and bool(proposals)
        key = (
            cohort,
            str(row["condition"]),
            str(row["policy_id"]),
            str(row["policy_type"]),
            row.get("layout_variant"),
            int(row["budget"]),
            str(label["status"]),
        )
        total = totals.setdefault(
            key,
            {
                "trials": 0,
                "proposal_count_sum": 0,
                "proposal_count_min": None,
                "proposal_count_max": 0,
                "candidate_universe_fraction_sum": 0.0,
                "canonical_targets": 0,
                "canonical_targets_in_candidate_universe": 0,
                "canonical_witnesses_in_pool": 0,
                "qualified_targets": 0,
                "qualified_targets_in_candidate_universe": 0,
                "qualified_witnesses_in_pool": 0,
                "present_field_trials": 0,
                "canonical_field_hits": 0,
                "qualified_field_hits": 0,
                "nonempty_pools": 0,
                "absent_nonempty_pools": 0,
                "target_cases": set(),
            },
        )
        count = len(proposals)
        total["trials"] += 1
        total["proposal_count_sum"] += count
        total["proposal_count_min"] = (
            count
            if total["proposal_count_min"] is None
            else min(total["proposal_count_min"], count)
        )
        total["proposal_count_max"] = max(total["proposal_count_max"], count)
        total["candidate_universe_fraction_sum"] += float(
            row["target_candidate_universe_fraction"]
        )
        total["canonical_targets"] += len(canonical_ids)
        total["canonical_targets_in_candidate_universe"] += len(
            canonical_ids & candidate_ids
        )
        total["canonical_witnesses_in_pool"] += len(canonical_ids & proposals)
        total["qualified_targets"] += len(qualified_ids)
        total["qualified_targets_in_candidate_universe"] += len(
            qualified_ids & candidate_ids
        )
        total["qualified_witnesses_in_pool"] += len(qualified_ids & proposals)
        total["present_field_trials"] += label["status"] == "present_dom"
        total["canonical_field_hits"] += bool(canonical_ids & proposals)
        total["qualified_field_hits"] += bool(qualified_ids & proposals)
        total["nonempty_pools"] += bool(proposals)
        total["absent_nonempty_pools"] += absent_nonempty_pool
        total["target_cases"].add(str(row["target"]))
    aggregates = []
    for key, value in sorted(
        totals.items(), key=lambda item: tuple(str(x) for x in item[0])
    ):
        (
            cohort,
            condition,
            policy_id,
            policy_type,
            layout_variant,
            budget,
            field_status,
        ) = key
        trials = int(value["trials"])
        aggregates.append(
            {
                "cohort": cohort,
                "condition": condition,
                "policy_id": policy_id,
                "policy_type": policy_type,
                "layout_variant": layout_variant,
                "budget": budget,
                "field_status": field_status,
                **{name: val for name, val in value.items() if name != "target_cases"},
                "unique_target_cases": len(value["target_cases"]),
                "mean_proposal_count": value["proposal_count_sum"] / trials
                if trials
                else None,
                "mean_candidate_universe_fraction": value[
                    "candidate_universe_fraction_sum"
                ]
                / trials
                if trials
                else None,
                "canonical_witness_coverage": (
                    value["canonical_witnesses_in_pool"]
                    / value["canonical_targets_in_candidate_universe"]
                    if value["canonical_targets_in_candidate_universe"]
                    else None
                ),
                "qualified_witness_coverage": (
                    value["qualified_witnesses_in_pool"]
                    / value["qualified_targets_in_candidate_universe"]
                    if value["qualified_targets_in_candidate_universe"]
                    else None
                ),
                "accuracy_or_acceptance_claim": False,
                "canonical_field_hit_rate": value["canonical_field_hits"]
                / value["present_field_trials"]
                if value["present_field_trials"]
                else None,
                "qualified_field_hit_rate": value["qualified_field_hits"]
                / value["present_field_trials"]
                if value["present_field_trials"]
                else None,
            }
        )
    return aggregates


def _verify_annotation_sources(
    view: str,
    page_rows: Mapping[str, Mapping[str, Any]],
    labels_path: Path,
) -> dict[str, Any]:
    """Bind annotations to their captured source files and candidate manifest."""
    labels_bytes = labels_path.read_bytes()
    labels = json.loads(labels_bytes)
    capture_root = (
        ROOT
        / ".generated"
        / (
            "product-retrieval-layout-v1"
            if view == "wide"
            else "product-retrieval-layout-narrow-v1"
        )
    )
    file_hash_keys = {
        "element-layout.json": "element_layout_sha256",
        "rendered-dom.html": "rendered_dom_sha256",
        "viewport.png": "viewport_png_sha256",
    }
    for case_id, page in page_rows.items():
        annotation = labels["cases"].get(case_id)
        if annotation is None:
            raise ValueError(f"{view} label missing for captured page {case_id}")
        hashes = annotation["hashes"]
        manifest_path = capture_root / case_id / "manifest.json"
        if (
            sha256_file(manifest_path) != page["manifest_sha256"]
            or hashes["manifest_sha256"] != page["manifest_sha256"]
        ):
            raise ValueError(f"{view} manifest/source binding mismatch for {case_id}")
        for filename, label_hash_key in file_hash_keys.items():
            observed = sha256_file(capture_root / case_id / filename)
            if (
                observed != page["source_hashes"].get(filename)
                or observed != hashes[label_hash_key]
            ):
                raise ValueError(
                    f"{view} capture source hash mismatch for {case_id}/{filename}"
                )
    return {
        "labels": labels,
        "labels_sha256": hashlib.sha256(labels_bytes).hexdigest(),
        "capture_page_count": len(page_rows),
        "source_page_hashes_verified": True,
    }


def execute_pool_ablation(output_directory: Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Build pool proposals from saved top-five lists, then evaluate coverage."""
    output_directory = output_directory.resolve()
    if not output_directory.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ValueError("output must stay under the declared generated directory")
    if output_directory.exists():
        raise FileExistsError(
            "refusing to overwrite or resume partial pool-ablation output"
        )

    wide_profile, wide_pages, wide_meta = _load_profile_bundle("wide")
    narrow_profile, narrow_pages, narrow_meta = _load_profile_bundle("narrow")
    layout_variants = tuple(wide_profile["layout_methods"])
    if set(layout_variants) != set(narrow_profile["layout_methods"]):
        raise ValueError("wide and narrow profiles declare different layout variants")
    specs = build_pool_specs(layout_variants, tuple(key for key, _ in CONTROL_CHANNELS))

    cohort_views = {
        "wide-to-wide": ("wide", "wide"),
        "wide-to-narrow": ("narrow", "wide"),
        "narrow-to-wide": ("wide", "narrow"),
        "narrow-to-narrow": ("narrow", "narrow"),
    }
    views = {
        "wide": (wide_profile, wide_pages, wide_meta),
        "narrow": (narrow_profile, narrow_pages, narrow_meta),
    }
    cohorts: dict[str, dict[str, Any]] = {}
    input_hashes: dict[str, Any] = {}
    for cohort, (target_view, seed_view) in cohort_views.items():
        target_profile, target_pages, target_meta = views[target_view]
        seed_profile, seed_pages, seed_meta = views[seed_view]
        run_dir = ROOT / ".generated" / f"product-retrieval-layout-{cohort}-v1"
        summary_path = run_dir / "summary.json"
        rows_path = run_dir / "rows.jsonl.gz"
        summary_bytes = summary_path.read_bytes()
        summary = json.loads(summary_bytes)
        if summary["profile_sha256"] != target_meta["profile_sha256"]:
            raise ValueError(f"target profile binding mismatch in {cohort}")
        if summary["seed_profile_sha256"] != seed_meta["profile_sha256"]:
            raise ValueError(f"seed profile binding mismatch in {cohort}")
        if (
            summary["rows"] <= 0
            or summary["model_inference_calls"] != 0
            or summary["network_calls"] != 0
        ):
            raise ValueError(
                "source layout artifact is incomplete or used inference/network: "
                f"{cohort}"
            )
        trials, row_meta = _load_raw_channel_rows(
            cohort, target_pages, seed_pages, summary
        )
        cohorts[cohort] = {
            "target_view": target_view,
            "seed_view": seed_view,
            "target_profile": target_profile,
            "seed_profile": seed_profile,
            "target_pages": target_pages,
            "seed_pages": seed_pages,
            "summary": summary,
            "summary_path": summary_path,
            "rows_path": rows_path,
            "trials": trials,
            "row_meta": row_meta,
        }
        input_hashes[cohort] = {
            "target_view": target_view,
            "seed_view": seed_view,
            "target_profile_sha256": target_meta["profile_sha256"],
            "seed_profile_sha256": seed_meta["profile_sha256"],
            "target_candidate_sha256": target_profile["candidate_sha256"],
            "seed_candidate_sha256": seed_profile["candidate_sha256"],
            "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
            "rows_sha256": row_meta["rows_sha256"],
            "target_annotation_sha256": summary["annotation_sha256"],
            "seed_annotation_sha256": summary["seed_annotation_sha256"],
            "base_trial_count": row_meta["base_trial_count"],
            "source_top5_rows_used": row_meta["channel_rank_rows_used"],
        }

    proposal_rows, per_cohort_proposal_counts = _build_proposals(
        cohorts, layout_variants, specs
    )
    expected_fixed_policies = len(layout_variants) * 11 + 4
    expected_proposal_rows = 4 * 48 * (expected_fixed_policies + 1) * len(BUDGETS)
    if len(proposal_rows) != expected_proposal_rows:
        raise ValueError(
            f"unexpected pool row count: {len(proposal_rows)} "
            f"!= {expected_proposal_rows}"
        )
    output_directory.mkdir(parents=True, exist_ok=False)
    plan = {
        "format": "layout-pool-ablation-plan-v1",
        "cohorts": input_hashes,
        "layout_variants": list(layout_variants),
        "shared_control_channels": dict(CONTROL_CHANNELS),
        "fixed_layout_policy_count": len(layout_variants) * 11,
        "shared_control_policy_count": 4,
        "fixed_policy_count": expected_fixed_policies,
        "posthoc_gate_policy_count": 1,
        "policies_per_layout_variant": {
            variant: {"single": 1, "ordered_pairs": 4, "ordered_triples": 6}
            for variant in layout_variants
        },
        "budgets": list(BUDGETS),
        "pool_algorithm": (
            "fixed top-five round-robin in declared channel order, "
            "deduplicated by candidate ID"
        ),
        "source_rankings": (
            "persisted method proposal_ids at budget 5; no scores recomputed"
        ),
        "target_gold_used_for_pool_or_gate_construction": False,
        "posthoc_viewport_gate": {
            "rule": (
                "exact target/seed viewport equality selects layout_geometry; "
                "otherwise layout_parent_typography"
            ),
            "status": GATE_STATUS,
            "heldout_validation_claim": False,
        },
        "candidate_rows_total": len(proposal_rows),
        "per_cohort_proposal_rows": per_cohort_proposal_counts,
        "formatting_notes": [
            "Pool proposal construction finished before target labels are loaded.",
            "The viewport gate reads only exact viewport metadata.",
            (
                "Standalone structural and lexical controls are included once "
                "per base trial, not repeated per layout variant."
            ),
        ],
    }
    (output_directory / "run-plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
    )
    proposal_path = output_directory / "pool-proposals.jsonl.gz"
    with gzip.open(proposal_path, "wt", encoding="utf-8") as stream:
        for row in proposal_rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    # Annotation files are opened only after the complete gold-blind pool file exists.
    wide_labels_path = (
        ROOT / ".generated" / "product-retrieval-layout-gold-v1" / "labels.json"
    )
    narrow_labels_path = (
        ROOT / ".generated" / "product-retrieval-layout-gold-narrow-v1" / "labels.json"
    )
    wide_label_info = _verify_annotation_sources("wide", wide_pages, wide_labels_path)
    narrow_label_info = _verify_annotation_sources(
        "narrow", narrow_pages, narrow_labels_path
    )
    label_info_by_view = {"wide": wide_label_info, "narrow": narrow_label_info}
    labels_by_view = {
        "wide": wide_label_info["labels"],
        "narrow": narrow_label_info["labels"],
    }
    for cohort, bundle in cohorts.items():
        if (
            bundle["summary"]["annotation_sha256"]
            != label_info_by_view[bundle["target_view"]]["labels_sha256"]
        ):
            raise ValueError(f"target annotation hash mismatch in {cohort}")
        if (
            bundle["summary"]["seed_annotation_sha256"]
            != label_info_by_view[bundle["seed_view"]]["labels_sha256"]
        ):
            raise ValueError(f"seed annotation hash mismatch in {cohort}")
    target_pages_by_cohort = {
        cohort: bundle["target_pages"] for cohort, bundle in cohorts.items()
    }
    labels_by_cohort = {
        cohort: labels_by_view[bundle["target_view"]]["labels"]
        for cohort, bundle in cohorts.items()
    }
    coverage_groups = _evaluate_pool_coverage(
        proposal_rows, target_pages_by_cohort, labels_by_cohort
    )
    coverage_document = {
        "format": "layout-pool-ablation-coverage-v1",
        "coverage_semantics": (
            "candidate-pool and annotated source-witness coverage only; not "
            "accuracy, correctness, Contract acceptance, or runtime validation"
        ),
        "pool_proposals_written_before_gold_read": True,
        "annotation_hashes": {
            "wide": wide_label_info["labels_sha256"],
            "narrow": narrow_label_info["labels_sha256"],
        },
        "annotation_source_hash_checks": {
            "wide": wide_label_info["source_page_hashes_verified"],
            "narrow": narrow_label_info["source_page_hashes_verified"],
        },
        "fixed_policy_count": expected_fixed_policies,
        "posthoc_gate_policy_count": 1,
        "proposal_row_count": len(proposal_rows),
        "coverage_group_count": len(coverage_groups),
        "coverage_groups": coverage_groups,
        "notes": [
            (
                "Proposal IDs are unchanged target-profile rankings from saved "
                "budget-5 method rows, merged by fixed round-robin order."
            ),
            (
                "The top-five inputs are repeated across larger budgets only "
                "through round-robin unions; no method score is recomputed."
            ),
            (
                "Absent fields report whether a pool is nonempty; they are "
                "not labeled false-acceptances."
            ),
            "The viewport gate is explicitly post-hoc and not heldout validated.",
        ],
        "producer_hashes": {
            "driver_sha256": sha256_file(Path(__file__)),
            "test_sha256": sha256_file(
                Path(__file__).with_name("test_layout_pool_ablation.py")
            ),
        },
    }
    coverage_path = output_directory / "coverage.json"
    coverage_path.write_text(
        json.dumps(coverage_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "target_cohorts": list(cohorts),
        "fixed_policy_count": expected_fixed_policies,
        "posthoc_gate_policy_count": 1,
        "proposal_row_count": len(proposal_rows),
        "coverage_group_count": len(coverage_groups),
        "output_directory": str(output_directory),
    }


def recover_existing_pool_coverage(
    output_directory: Path = RECOVERY_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Evaluate the saved v1 pools without rebuilding or modifying them."""
    output_directory = output_directory.resolve()
    if not output_directory.is_relative_to(RECOVERY_OUTPUT_ROOT.resolve()):
        raise ValueError("recovery output must stay under the declared v2 directory")
    if output_directory.exists():
        raise FileExistsError("refusing to overwrite or resume partial recovery")

    source_directory = OUTPUT_ROOT
    plan_path = source_directory / "run-plan.json"
    proposals_path = source_directory / "pool-proposals.jsonl.gz"
    observed_plan_sha256 = sha256_file(plan_path)
    observed_proposals_sha256 = sha256_file(proposals_path)
    if observed_plan_sha256 != EXPECTED_V1_PLAN_SHA256:
        raise ValueError("v1 run-plan hash differs from the recorded partial run")
    if observed_proposals_sha256 != EXPECTED_V1_PROPOSALS_SHA256:
        raise ValueError("v1 proposal gzip hash differs from the recorded partial run")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if (
        plan.get("format") != "layout-pool-ablation-plan-v1"
        or plan.get("fixed_policy_count") != 70
        or plan.get("posthoc_gate_policy_count") != 1
        or plan.get("candidate_rows_total") != 68160
        or plan.get("target_gold_used_for_pool_or_gate_construction") is not False
    ):
        raise ValueError("v1 run plan does not match the declared 70-policy design")

    proposal_rows = []
    with gzip.open(proposals_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("target_gold_read") is not False:
                raise ValueError("saved proposal row is not marked gold-blind")
            proposal_rows.append(row)
    if len(proposal_rows) != plan["candidate_rows_total"]:
        raise ValueError("saved proposal row count does not match the v1 plan")
    cohort_counts = {
        cohort: sum(row["cohort"] == cohort for row in proposal_rows)
        for cohort in plan["cohorts"]
    }
    if cohort_counts != plan["per_cohort_proposal_rows"]:
        raise ValueError("saved per-cohort proposal counts differ from the v1 plan")

    output_directory.mkdir(parents=True, exist_ok=False)
    producer_path = Path(__file__).resolve()
    test_path = producer_path.with_name("test_layout_pool_ablation.py")
    shutil.copyfile(producer_path, output_directory / "producer.py")
    shutil.copyfile(test_path, output_directory / "producer-tests.py")
    recovery_manifest = {
        "format": "layout-pool-ablation-v2-recovery-v1",
        "status": "evaluation_in_progress",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_run_plan": str(plan_path.relative_to(ROOT)),
        "source_run_plan_sha256": observed_plan_sha256,
        "source_proposal_gzip": str(proposals_path.relative_to(ROOT)),
        "source_proposal_gzip_sha256": observed_proposals_sha256,
        "source_proposal_rows": len(proposal_rows),
        "per_cohort_proposal_rows": cohort_counts,
        "producer_snapshot_sha256": sha256_file(output_directory / "producer.py"),
        "test_snapshot_sha256": sha256_file(output_directory / "producer-tests.py"),
        "recovery_semantics": (
            "evaluate persisted v1 proposal IDs only; no ranking, scoring, "
            "or pool rebuild"
        ),
        "target_gold_used_for_pool_or_gate_construction": False,
    }
    manifest_path = output_directory / "recovery-manifest.json"
    manifest_path.write_text(
        json.dumps(recovery_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    wide_profile, wide_pages, wide_meta = _load_profile_bundle("wide")
    narrow_profile, narrow_pages, narrow_meta = _load_profile_bundle("narrow")
    profiles = {
        "wide": (wide_profile, wide_pages, wide_meta),
        "narrow": (narrow_profile, narrow_pages, narrow_meta),
    }
    for cohort, bindings in plan["cohorts"].items():
        target_profile, _, target_meta = profiles[bindings["target_view"]]
        seed_profile, _, seed_meta = profiles[bindings["seed_view"]]
        if (
            target_meta["profile_sha256"] != bindings["target_profile_sha256"]
            or seed_meta["profile_sha256"] != bindings["seed_profile_sha256"]
            or target_profile["candidate_sha256"] != bindings["target_candidate_sha256"]
            or seed_profile["candidate_sha256"] != bindings["seed_candidate_sha256"]
        ):
            raise ValueError(f"v1 plan/profile binding mismatch in {cohort}")

    wide_label_info = _verify_annotation_sources(
        "wide",
        wide_pages,
        ROOT / ".generated" / "product-retrieval-layout-gold-v1" / "labels.json",
    )
    narrow_label_info = _verify_annotation_sources(
        "narrow",
        narrow_pages,
        ROOT / ".generated" / "product-retrieval-layout-gold-narrow-v1" / "labels.json",
    )
    labels_by_view = {
        "wide": wide_label_info["labels"],
        "narrow": narrow_label_info["labels"],
    }
    evaluation_cohorts: dict[str, dict[str, Any]] = {}
    for cohort, bindings in plan["cohorts"].items():
        view = str(bindings["target_view"])
        label_info = wide_label_info if view == "wide" else narrow_label_info
        if bindings["target_annotation_sha256"] != label_info["labels_sha256"]:
            raise ValueError(f"v1 target annotation binding mismatch in {cohort}")
        seed_view = str(bindings["seed_view"])
        seed_label_info = wide_label_info if seed_view == "wide" else narrow_label_info
        if bindings["seed_annotation_sha256"] != seed_label_info["labels_sha256"]:
            raise ValueError(f"v1 seed annotation binding mismatch in {cohort}")
        evaluation_cohorts[cohort] = {
            "target_view": view,
            "target_pages": profiles[view][1],
        }

    coverage_groups = _evaluate_pool_coverage(
        proposal_rows, evaluation_cohorts, labels_by_view
    )
    coverage_document = {
        "format": "layout-pool-ablation-coverage-v2",
        "coverage_semantics": (
            "candidate-pool and annotated source-witness coverage only; not "
            "accuracy, correctness, Contract acceptance, or runtime validation"
        ),
        "recovered_from_existing_v1_pools": True,
        "pool_proposals_written_before_gold_read": True,
        "source_run_plan_sha256": observed_plan_sha256,
        "source_proposal_gzip_sha256": observed_proposals_sha256,
        "annotation_hashes": {
            "wide": wide_label_info["labels_sha256"],
            "narrow": narrow_label_info["labels_sha256"],
        },
        "annotation_source_hash_checks": {
            "wide": wide_label_info["source_page_hashes_verified"],
            "narrow": narrow_label_info["source_page_hashes_verified"],
        },
        "fixed_policy_count": 70,
        "posthoc_gate_policy_count": 1,
        "proposal_row_count": len(proposal_rows),
        "coverage_group_count": len(coverage_groups),
        "coverage_groups": coverage_groups,
        "notes": [
            "Evaluation consumed saved proposal IDs; no pool or score was regenerated.",
            "Absent fields indicate whether a pool is nonempty, not false acceptances.",
            "The viewport gate is post-hoc and not heldout validated.",
        ],
        "producer_hashes": {
            "driver_sha256": sha256_file(Path(__file__)),
            "test_sha256": sha256_file(test_path),
        },
    }
    coverage_path = output_directory / "coverage.json"
    coverage_path.write_text(
        json.dumps(coverage_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    recovery_manifest["status"] = "complete"
    recovery_manifest["annotation_hashes"] = coverage_document["annotation_hashes"]
    recovery_manifest["coverage_sha256"] = sha256_file(coverage_path)
    manifest_path.write_text(
        json.dumps(recovery_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "complete",
        "fixed_policy_count": 70,
        "posthoc_gate_policy_count": 1,
        "proposal_row_count": len(proposal_rows),
        "coverage_group_count": len(coverage_groups),
        "output_directory": str(output_directory),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recover-existing-v1",
        action="store_true",
        help="evaluate saved v1 pools into the separate v2 recovery directory",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.recover_existing_v1:
        result = recover_existing_pool_coverage(args.output or RECOVERY_OUTPUT_ROOT)
    else:
        result = execute_pool_ablation(args.output or OUTPUT_ROOT)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
