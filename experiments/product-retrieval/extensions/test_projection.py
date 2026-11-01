"""Small gold-blind projection-policy proofs for cached candidate scores."""

from __future__ import annotations

import unittest

from projection import (
    POLICY_NODE_THEN_PROJECT,
    POLICY_RESTRICTED_RANKING,
    POLICY_VALUE_RANKING,
    apply_projection_policy,
    evaluate_node_location,
    reference_projection_hints,
)


def candidate(candidate_id, node_id, projection, text, ancestors):
    return {
        "id": candidate_id,
        "node_id": node_id,
        "projection": projection,
        "text": text,
        "context": "parent=article",
        "tag": "h1" if projection == "text" else "input",
        "attributes": {},
        "path": ["#document", "html", "article", "h1"],
        "motifs": ["has-text"],
        "ancestors": ancestors,
    }


class ProjectionPolicyTests(unittest.TestCase):
    def test_no_policy_calls_uncalibrated_scores_probabilities(self):
        values = [candidate("a", "n", "text", "value", ["r"])]
        hints = reference_projection_hints(values, "name")
        for policy in (
            POLICY_VALUE_RANKING,
            POLICY_NODE_THEN_PROJECT,
            POLICY_RESTRICTED_RANKING,
        ):
            result = apply_projection_policy(
                policy, [0.8], values, hints, source_candidates=values
            )
            self.assertFalse(result["projection_scores_are_probabilities"])

    def test_seed_hints_are_projection_only_and_never_default_to_text(self) -> None:
        text_hint = reference_projection_hints(
            [candidate("seed-name", "10", "text", "Loop mug", ["root"])],
            "name",
        )
        id_hint = reference_projection_hints(
            [candidate("seed-id", "12", "@data-product-id", "obj-12", ["root"])],
            "id",
        )
        empty_hint = reference_projection_hints([], "name")
        wrong_root_hint = reference_projection_hints(
            [candidate("root-attr", "10", "@id", "product", ["doc"])], "root"
        )

        self.assertEqual(text_hint["projections"], ["text"])
        self.assertEqual(id_hint["projections"], ["@data-product-id"])
        self.assertEqual(empty_hint["status"], "no_reference_candidates")
        self.assertFalse(empty_hint["supported"])
        self.assertEqual(wrong_root_hint["status"], "root_requires_text_reference")
        self.assertFalse(wrong_root_hint["supported"])

    def test_correct_node_id_attribute_localizes_text_without_borrowing_its_score(
        self,
    ) -> None:
        scored = [
            candidate(
                "model-id",
                "title-node",
                "@id",
                "product-title",
                ["doc", "product-root"],
            ),
            candidate(
                "model-decoy",
                "related-title",
                "text",
                "Related vessel",
                ["doc", "related-root"],
            ),
        ]
        source = [
            *scored,
            candidate(
                "source-title-text",
                "title-node",
                "text",
                "Grid notebook",
                ["doc", "product-root"],
            ),
        ]
        hints = reference_projection_hints(
            [candidate("seed-name", "seed-title", "text", "Loop mug", ["seed-root"])],
            "name",
        )
        result = apply_projection_policy(
            POLICY_NODE_THEN_PROJECT,
            [0.95, 0.80],
            scored,
            hints,
            source_candidates=source,
            top_nodes=5,
        )

        projected = next(
            item for item in result["results"] if item["node_id"] == "title-node"
        )
        self.assertEqual(projected["candidate_id"], "source-title-text")
        self.assertEqual(projected["projection"], "text")
        self.assertEqual(projected["value"], "Grid notebook")
        self.assertEqual(projected["localization_score"], 0.95)
        self.assertIsNone(projected["projection_score"])
        self.assertEqual(
            projected["score_role"],
            "node_localization_only; projected value is unscored",
        )
        self.assertFalse(projected["candidate_was_scored"])
        self.assertFalse(result["projection_scores_are_probabilities"])
        self.assertFalse(
            result["original_model_pool_recall_applies_to_materialized_candidates"]
        )
        self.assertEqual(result["extra_source_projection_reads"], 1)
        self.assertEqual(result["source_projection_reads"], 2)

    def test_original_and_projection_restricted_rankings_remain_distinct(self) -> None:
        scored = [
            candidate(
                "title-attr", "title-node", "@id", "product-title", ["doc", "root"]
            ),
            candidate(
                "other-text",
                "other-node",
                "text",
                "Unrelated recommendation",
                ["doc", "root"],
            ),
        ]
        hints = reference_projection_hints(
            [candidate("seed-name", "seed-title", "text", "Loop mug", ["seed-root"])],
            "name",
        )
        baseline = apply_projection_policy(
            POLICY_VALUE_RANKING, [0.95, 0.80], scored, hints
        )
        restricted = apply_projection_policy(
            POLICY_RESTRICTED_RANKING, [0.95, 0.80], scored, hints
        )

        self.assertEqual(baseline["results"][0]["candidate_id"], "title-attr")
        self.assertEqual(restricted["results"][0]["candidate_id"], "other-text")
        self.assertEqual(restricted["results"][0]["candidate_score"], 0.80)
        self.assertEqual(restricted["status"], "complete")

    def test_wrong_owner_candidate_does_not_become_a_correct_location(self) -> None:
        scored = [
            candidate(
                "wrong-title",
                "related-title",
                "@id",
                "product-title",
                ["doc", "related-root"],
            )
        ]
        source = [
            *scored,
            candidate(
                "wrong-text",
                "related-title",
                "text",
                "Related product",
                ["doc", "related-root"],
            ),
        ]
        hints = reference_projection_hints(
            [candidate("seed-name", "seed-title", "text", "Loop mug", ["seed-root"])],
            "name",
        )
        result = apply_projection_policy(
            POLICY_NODE_THEN_PROJECT,
            [0.99],
            scored,
            hints,
            source_candidates=source,
            top_nodes=5,
        )
        evaluation = evaluate_node_location(
            result["node_ranking"],
            ["target-title"],
            [
                candidate(
                    "target-title",
                    "main-title",
                    "text",
                    "Target product",
                    ["doc", "main-root"],
                ),
                *source,
            ],
            "main-root",
            expected_present=True,
            expected_status="present_dom",
        )

        self.assertFalse(evaluation["node_top1_correct"])
        self.assertFalse(evaluation["owner_correct"])
        self.assertFalse(evaluation["owned_node_top1_correct"])
        self.assertIsNone(evaluation["value_correct"])

    def test_absent_projection_is_counted_without_falling_back_to_another_projection(
        self,
    ) -> None:
        scored = [
            candidate("title-id", "title-node", "@id", "product-title", ["doc", "root"])
        ]
        hints = reference_projection_hints(
            [candidate("seed-name", "seed-title", "text", "Loop mug", ["seed-root"])],
            "name",
        )
        node_projected = apply_projection_policy(
            POLICY_NODE_THEN_PROJECT,
            [0.9],
            scored,
            hints,
            source_candidates=scored,
        )
        restricted = apply_projection_policy(
            POLICY_RESTRICTED_RANKING,
            [0.9],
            scored,
            hints,
        )

        self.assertEqual(
            node_projected["status"], "no_supported_projection_at_selected_nodes"
        )
        self.assertEqual(node_projected["source_projection_reads"], 1)
        self.assertEqual(node_projected["absent_projection_count"], 1)
        self.assertEqual(node_projected["results"], [])
        self.assertEqual(restricted["status"], "no_supported_candidates")
        self.assertEqual(restricted["results"], [])

    def test_index_mapping_ties_and_duplicate_source_projections_are_deterministic(
        self,
    ) -> None:
        scored = [
            candidate("attr-z", "node-z", "@id", "title", ["doc", "root"]),
            candidate("attr-a", "node-a", "@id", "title", ["doc", "root"]),
        ]
        source = [
            *scored,
            candidate("text-z", "node-a", "text", "A title", ["doc", "root"]),
            candidate("text-a", "node-a", "text", "A title", ["doc", "root"]),
        ]
        hints = reference_projection_hints(
            [candidate("seed-name", "seed-title", "text", "Loop mug", ["seed-root"])],
            "name",
        )
        result = apply_projection_policy(
            POLICY_NODE_THEN_PROJECT,
            [0.8, 0.8],
            scored,
            hints,
            source_candidates=source,
            top_nodes=5,
        )

        self.assertEqual(
            [node["node_id"] for node in result["node_ranking"]], ["node-a", "node-z"]
        )
        self.assertEqual(
            [item["candidate_id"] for item in result["results"]], ["text-a", "text-z"]
        )
        self.assertEqual(result["duplicate_source_candidates"], 1)
        self.assertEqual(result["extra_source_projection_reads"], 2)

    def test_evaluator_separates_absence_external_identity_and_missing_gold_coordinates(
        self,
    ) -> None:
        source = [candidate("node-text", "node", "text", "Some value", ["doc", "root"])]
        absent = evaluate_node_location(
            [], [], source, "root", expected_present=False, expected_status="absent"
        )
        external = evaluate_node_location(
            [],
            [],
            source,
            "root",
            expected_present=True,
            expected_status="present_external_url",
        )
        missing = evaluate_node_location(
            [],
            ["missing-id"],
            source,
            "root",
            expected_present=True,
            expected_status="present_dom",
        )
        self.assertTrue(absent["quality_evaluable"])
        self.assertTrue(absent["node_top1_correct"])
        self.assertFalse(external["quality_evaluable"])
        self.assertIsNone(external["node_top1_correct"])
        self.assertEqual(missing["status"], "gold_candidate_missing_from_source")

    def test_target_annotation_keys_are_rejected_from_policy_candidates(self) -> None:
        labeled_candidate = {
            **candidate("id", "node", "text", "value", ["root"]),
            "expected_values": {"name": "value"},
        }
        hints = reference_projection_hints(
            [candidate("seed", "seed-node", "text", "seed", ["seed-root"])],
            "name",
        )
        with self.assertRaisesRegex(ValueError, "target annotations"):
            apply_projection_policy(
                POLICY_VALUE_RANKING, [1.0], [labeled_candidate], hints
            )


if __name__ == "__main__":
    unittest.main()
