"""Focused checks for fixed layout-channel subset pools and viewport gate."""

from __future__ import annotations

import unittest

from layout_pool_ablation import (
    _evaluate_pool_coverage,
    build_pool_specs,
    fixed_round_robin_pool,
    viewport_gate_variant,
)


def test_one_qualified_witness_is_a_field_hit_not_half_a_hit():
    row = {
        "cohort": "a",
        "target": "one",
        "field": "price",
        "condition": "cross_template",
        "policy_id": "p",
        "policy_type": "layout_pool",
        "layout_variant": "layout_font",
        "budget": 1,
        "proposal_ids": ["element:000001"],
        "target_candidate_universe_fraction": 0.5,
    }
    cohorts = {
        "a": {
            "target_view": "wide",
            "target_pages": {
                "one": {
                    "candidates": [{"id": "element:000001"}, {"id": "element:000002"}]
                }
            },
        }
    }
    labels = {
        "wide": {
            "cases": {
                "one": {
                    "fields": {
                        "price": {
                            "status": "present_dom",
                            "canonical_ordinals": [1],
                            "qualified_alternative_ordinals": [2],
                        }
                    }
                }
            }
        }
    }
    result = _evaluate_pool_coverage([row], cohorts, labels)[0]
    assert result["qualified_witness_coverage"] == 0.5
    assert result["qualified_field_hit_rate"] == 1.0
    assert result["qualified_field_hits"] == 1


class LayoutPoolAblationTests(unittest.TestCase):
    def test_coverage_reads_saved_target_candidate_universe_fraction(self):
        proposal_rows = [
            {
                "cohort": "wide-to-wide",
                "condition": "self",
                "target": "page-a",
                "seed": "page-b",
                "field": "name",
                "policy_id": "layout_geometry::layout",
                "policy_type": "layout_pool",
                "layout_variant": "layout_geometry",
                "budget": 1,
                "proposal_ids": ["element:000001"],
                "target_candidate_universe_fraction": 0.5,
            }
        ]
        cohorts = {
            "wide-to-wide": {
                "target_view": "wide",
                "target_pages": {"page-a": {"candidates": [{"id": "element:000001"}]}},
            }
        }
        gold_by_view = {
            "wide": {
                "cases": {
                    "page-a": {
                        "fields": {
                            "name": {
                                "status": "present",
                                "canonical_ordinals": [1],
                                "qualified_alternative_ordinals": [],
                            }
                        }
                    }
                }
            }
        }

        groups = _evaluate_pool_coverage(proposal_rows, cohorts, gold_by_view)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["mean_candidate_universe_fraction"], 0.5)
        self.assertEqual(groups[0]["canonical_witness_coverage"], 1.0)

    def test_each_layout_variant_has_one_single_four_pairs_and_six_triples(self):
        variants = (
            "layout_geometry",
            "layout_font",
            "layout_geometry_typography",
            "layout_parent_typography",
            "layout_parent_geometry",
            "layout_color",
        )
        controls = ("structure", "lexical")

        specs = build_pool_specs(variants, controls)
        layout_specs = [spec for spec in specs if spec["policy_type"] == "layout_pool"]
        control_specs = [
            spec for spec in specs if spec["policy_type"] == "shared_control"
        ]

        self.assertEqual(len(layout_specs), 6 * 11)
        self.assertEqual(len(control_specs), 4)
        for variant in variants:
            selected = [
                spec for spec in layout_specs if spec["layout_variant"] == variant
            ]
            self.assertEqual(
                {
                    size: sum(len(spec["channel_order"]) == size for spec in selected)
                    for size in (1, 2, 3)
                },
                {1: 1, 2: 4, 3: 6},
            )

    def test_round_robin_deduplicates_in_channel_order_and_caps_budget(self):
        rankings = {
            "layout": ["a", "b", "c"],
            "structure": ["a", "d", "e"],
            "lexical": ["b", "f", "g"],
        }

        self.assertEqual(
            fixed_round_robin_pool(rankings, ("layout", "structure", "lexical"), 5),
            ["a", "b", "d", "f", "c"],
        )
        self.assertEqual(
            fixed_round_robin_pool(rankings, ("layout", "structure", "lexical"), 3),
            ["a", "b", "d"],
        )
        self.assertEqual(
            fixed_round_robin_pool(rankings, ("layout",), 15), ["a", "b", "c"]
        )

    def test_viewport_gate_is_exact_and_explicitly_post_hoc(self):
        equal = viewport_gate_variant(
            {"width": 1280, "height": 800, "dpr": 1},
            {"width": 1280, "height": 800, "dpr": 1},
        )
        unequal = viewport_gate_variant(
            {"width": 1280, "height": 800, "dpr": 1},
            {"width": 390, "height": 844, "dpr": 1},
        )

        self.assertEqual(equal["layout_variant"], "layout_geometry")
        self.assertEqual(unequal["layout_variant"], "layout_parent_typography")
        self.assertEqual(equal["status"], "post_hoc_hypothesis_not_heldout_validated")
        self.assertEqual(unequal["status"], "post_hoc_hypothesis_not_heldout_validated")


if __name__ == "__main__":
    unittest.main()
