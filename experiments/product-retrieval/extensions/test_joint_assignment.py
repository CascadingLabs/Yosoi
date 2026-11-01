"""Focused proofs for bounded gold-blind joint root/field assignment."""

from __future__ import annotations

import math
import unittest

from joint_assignment import assign_jointly


def candidate(candidate_id, node_id, projection="text", ancestors=("document", "root")):
    return {
        "id": candidate_id,
        "node_id": node_id,
        "projection": projection,
        "ancestors": list(ancestors),
    }


class JointAssignmentTests(unittest.TestCase):
    def test_joint_assignment_resolves_independent_max_collision(self):
        candidates = [candidate("shared", "shared"), candidate("other", "other")]
        result = assign_jointly(
            {"id": [10.0, 8.0], "name": [9.0, 1.0]},
            candidates,
            {"root": 0.5},
            required_fields=("id", "name"),
        )

        self.assertEqual(result["field_mapping"]["id"]["candidate"]["id"], "other")
        self.assertEqual(result["field_mapping"]["name"]["candidate"]["id"], "shared")
        self.assertEqual(result["total_utility"], 17.5)
        self.assertFalse(result["ambiguous"])

    def test_distinct_projections_on_one_node_can_coexist(self):
        candidates = [
            candidate("root-text", "root", "text", ancestors=("document",)),
            candidate("root-id", "root", "@id", ancestors=("document",)),
        ]
        result = assign_jointly(
            {"name": [10.0, 8.0], "id": [10.0, 9.0]},
            candidates,
            {"root": 0.1},
            required_fields=("name", "id"),
        )

        selected = [
            result["field_mapping"][field]["evidence_key"] for field in ("name", "id")
        ]
        self.assertEqual(
            {(item["node_id"], item["projection"]) for item in selected},
            {("root", "text"), ("root", "@id")},
        )
        self.assertEqual(result["total_utility"], 19.1)

    def test_sibling_cross_owner_fields_inside_root_remain_a_flat_scope_limit(self):
        candidates = [
            candidate(
                "item-a-id", "id-a", "@id", ancestors=("document", "main", "item-a")
            ),
            candidate(
                "item-b-price",
                "price-b",
                "text",
                ancestors=("document", "main", "item-b"),
            ),
            candidate(
                "outside-decoy", "outside", "text", ancestors=("document", "other")
            ),
        ]
        result = assign_jointly(
            {"id": [0.9, 0.0, 50.0], "price": [0.0, 0.8, 40.0]},
            candidates,
            [{"node_id": "main", "score": 0.7}],
            required_fields=("id", "price"),
        )

        self.assertEqual(result["selected_root"]["node_id"], "main")
        self.assertEqual(result["field_mapping"]["id"]["candidate"]["id"], "item-a-id")
        self.assertEqual(
            result["field_mapping"]["price"]["candidate"]["id"], "item-b-price"
        )
        self.assertEqual(
            result["ownership_scope"],
            "selected candidates are under the proposed root only",
        )
        self.assertFalse(result["nested_composition_claimed"])

    def test_missing_required_field_is_explicitly_unmatched(self):
        candidates = [candidate("outside", "outside", ancestors=("document", "other"))]
        result = assign_jointly(
            {"name": [0.9]},
            candidates,
            {"root": 0.4},
            required_fields=("name",),
        )

        self.assertEqual(result["status"], "required_unmatched")
        self.assertEqual(result["required_unmatched"], ["name"])
        self.assertEqual(
            result["field_mapping"]["name"]["status"], "unmatched_required"
        )
        self.assertEqual(result["field_mapping"]["name"]["utility"], 0.0)
        self.assertEqual(result["total_utility"], 0.4)

    def test_optional_field_can_remain_unmatched_without_invalidating_record(self):
        candidates = [candidate("name", "name")]
        result = assign_jointly(
            {"name": [0.8], "stock": [0.1]},
            candidates,
            {"root": 0.2},
            required_fields=("name",),
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["optional_unmatched"], ["stock"])
        self.assertEqual(
            result["field_mapping"]["stock"]["status"], "unmatched_optional"
        )

    def test_candidate_threshold_is_applied_as_raw_score_not_probability(self):
        candidates = [candidate("low", "low"), candidate("high", "high")]
        result = assign_jointly(
            {"name": [0.49, 0.51]},
            candidates,
            {"root": 0.2},
            required_fields=("name",),
            candidate_threshold=0.5,
        )

        self.assertEqual(result["field_mapping"]["name"]["candidate"]["id"], "high")
        self.assertEqual(result["candidate_threshold"], 0.5)
        self.assertFalse(result["candidate_threshold_is_probability"])

    def test_invalid_score_vector_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected 1"):
            assign_jointly(
                {"name": [0.2, 0.3]},
                [candidate("one", "one")],
                {"root": 0.2},
                required_fields=("name",),
            )

    def test_invalid_topology_shape_is_rejected(self):
        malformed = {"id": "missing-ancestors", "node_id": "x", "projection": "text"}
        with self.assertRaisesRegex(ValueError, "ancestors"):
            assign_jointly(
                {"name": [1.0]},
                [malformed],
                {"root": 0.2},
                required_fields=("name",),
            )

    def test_nonfinite_field_and_root_scores_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "finite real"):
            assign_jointly(
                {"name": [math.nan]},
                [candidate("one", "one")],
                {"root": 0.2},
                required_fields=("name",),
            )
        with self.assertRaisesRegex(ValueError, "finite real"):
            assign_jointly(
                {"name": [1.0]},
                [candidate("one", "one")],
                {"root": math.inf},
                required_fields=("name",),
            )

    def test_declared_dp_budget_returns_incomplete_root_path(self):
        candidates = [candidate("a", "a"), candidate("b", "b")]
        result = assign_jointly(
            {"id": [1.0, 0.8], "name": [0.9, 0.7]},
            candidates,
            {"root": 0.5},
            required_fields=("id", "name"),
            bounds={"max_dp_transitions": 1},
        )

        self.assertEqual(result["status"], "budget_exhausted")
        self.assertFalse(result["optimal_over_supplied_input"])
        self.assertIn("root", result["unsolved_roots"])
        self.assertTrue(
            any(
                path["reason"] == "max_dp_transitions"
                for path in result["incomplete_paths"]
            )
        )

    def test_top_k_truncation_is_returned_as_bounded_not_complete(self):
        candidates = [candidate(f"c{index:02d}", f"n{index:02d}") for index in range(3)]
        result = assign_jointly(
            {"name": [3.0, 2.0, 1.0]},
            candidates,
            {"root": 0.5},
            required_fields=("name",),
            bounds={"per_field_top_k": 2},
        )

        self.assertEqual(result["status"], "bounded")
        self.assertFalse(result["optimal_over_supplied_input"])
        self.assertEqual(result["incomplete_paths"][0]["omitted_evidence_count"], 1)

    def test_equal_utility_assignments_are_deterministic_and_ambiguous(self):
        candidates = [candidate("b", "b-node"), candidate("a", "a-node")]
        result = assign_jointly(
            {"name": [1.0, 1.0]},
            candidates,
            {"root": 0.2},
            required_fields=("name",),
        )

        self.assertEqual(result["field_mapping"]["name"]["candidate"]["id"], "a")
        self.assertTrue(result["ambiguous"])
        self.assertIn("equal_utility_field_assignments", result["ambiguity_reasons"])

    def test_specificity_penalty_is_explicit_and_defaults_to_zero(self):
        candidates = [candidate("field", "field", ancestors=("document", "large"))]
        field_scores = {"name": [0.5]}
        roots = [
            {"node_id": "large", "score": 0.9, "size": 10},
            {"node_id": "small", "score": 0.8, "size": 1},
        ]
        unpenalized = assign_jointly(field_scores, candidates, roots, ("name",))
        penalized = assign_jointly(
            field_scores,
            candidates,
            roots,
            ("name",),
            root_specificity_lambda=0.1,
        )

        self.assertEqual(unpenalized["root_specificity_lambda"], 0.0)
        self.assertEqual(unpenalized["selected_root"]["node_id"], "large")
        self.assertEqual(penalized["selected_root"]["node_id"], "small")
        self.assertAlmostEqual(penalized["root_size_penalty"], 0.1)


if __name__ == "__main__":
    unittest.main()
