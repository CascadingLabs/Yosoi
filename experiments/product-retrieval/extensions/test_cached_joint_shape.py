"""Small unit tests for cached-score preparation and gold-blind scope masks."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cached_joint_shape import (
    MissingCachedScoreError,
    build_cache_key,
    cached_vector,
    choose_case_ids,
    masked_field_scores,
    projection_hints_for_seeds,
    root_size_fractions,
    root_text_indices,
    seed_candidates_for_field,
)


def candidate(candidate_id: str, projection: str, node_id: str) -> dict:
    return {
        "id": candidate_id,
        "node_id": node_id,
        "projection": projection,
        "ancestors": ["document"],
        "text": candidate_id,
    }


class CachedJointShapeTests(unittest.TestCase):
    def test_root_text_scores_and_field_scores_keep_separate_index_spaces(self) -> None:
        candidates = [
            candidate("text-0", "text", "n0"),
            candidate("id-0", "@id", "n0"),
            candidate("text-1", "text", "n1"),
            candidate("price-1", "@content", "n1"),
        ]

        self.assertEqual(root_text_indices(candidates), [0, 2])
        original_ids = [item["id"] for item in candidates]
        masked = masked_field_scores(
            [0.1, 0.9, 0.2, 0.8],
            candidates,
            {"supported": True, "projections": ["@content"]},
        )

        self.assertEqual(masked, [-1.0, -1.0, -1.0, 0.8])
        self.assertEqual([item["id"] for item in candidates], original_ids)
        self.assertEqual(len(masked), len(candidates))

    def test_projection_hints_use_only_seed_expected_candidate_ids(self) -> None:
        seed_cases = [
            {
                "candidates": [
                    candidate("seed-price", "@content", "price-node"),
                    candidate("seed-decoy", "@href", "link-node"),
                ],
                "expected": {"price": ["seed-price"]},
            },
            {
                "candidates": [candidate("second-price", "@content", "price-2")],
                "expected": {"price": ["second-price"]},
            },
        ]

        references = seed_candidates_for_field(seed_cases, "price")
        hints = projection_hints_for_seeds(seed_cases, ("price",))["price"]

        self.assertEqual(
            [item["id"] for item in references], ["seed-price", "second-price"]
        )
        self.assertEqual(hints["projections"], ["@content"])
        self.assertNotIn("@href", hints["projections"])

    def test_absent_cache_entry_fails_without_score_fallback(self) -> None:
        with self.assertRaises(MissingCachedScoreError):
            cached_vector({}, '["price","semantic_reference"]', 2)

    def test_cached_vector_shape_and_values_are_checked(self) -> None:
        entry = {"scores": [0.25, 0.75]}
        self.assertEqual(cached_vector({"key": entry}, "key", 2), [0.25, 0.75])
        with self.assertRaisesRegex(ValueError, "length"):
            cached_vector({"key": entry}, "key", 3)
        with self.assertRaisesRegex(ValueError, "finite nonnegative"):
            cached_vector({"key": {"scores": [float("nan")]}}, "key", 1)

    def test_semantic_cache_key_contains_the_original_embedding_artifact_hash(
        self,
    ) -> None:
        key = build_cache_key(
            "price",
            "semantic_reference",
            "obj-001+obj-002",
            "context",
            "minilm-sha256",
        )

        self.assertEqual(
            key,
            (
                '["price", "semantic_reference", "obj-001+obj-002", '
                '"context", "minilm-sha256"]'
            ),
        )

    def test_root_size_is_descendant_count_over_document_node_count(self) -> None:
        nodes = [
            {"id": 1, "parent": None},
            {"id": 2, "parent": 1},
            {"id": 3, "parent": 2},
            {"id": 4, "parent": 1},
        ]

        sizes = root_size_fractions(nodes)

        self.assertEqual(sizes["1"], 1.0)
        self.assertEqual(sizes["2"], 0.5)
        self.assertEqual(sizes["3"], 0.25)
        self.assertEqual(sizes["4"], 0.25)

    def test_case_selection_stays_within_the_four_original_micro_cases(self) -> None:
        self.assertEqual(
            choose_case_ids(("obj-004", "obj-003")), ("obj-004", "obj-003")
        )
        with self.assertRaisesRegex(ValueError, "at most four"):
            choose_case_ids(("obj-003", "obj-004", "obj-005", "obj-006", "obj-003"))
        with self.assertRaisesRegex(ValueError, "original micro cases"):
            choose_case_ids(("obj-003.class_rename",))


if __name__ == "__main__":
    unittest.main()
