"""Focused arithmetic checks for exact tie-order sensitivity bounds."""

from __future__ import annotations

import unittest

from tie_audit import build_score_groups, tie_sensitivity


def candidate(candidate_id: str) -> dict[str, str]:
    return {"id": candidate_id}


class TieSensitivityTests(unittest.TestCase):
    def test_gold_outside_saved_top_five_uses_the_complete_tie_group(self) -> None:
        candidates = [candidate(value) for value in ("lead", "a", "b", "c", "d", "z")]
        scores = [1.0, 0.5, 0.5, 0.5, 0.5, 0.5]
        ranked, groups = build_score_groups(scores, candidates)

        result = tie_sensitivity(scores, candidates, {"z"}, ranked, groups)

        self.assertNotIn("z", [candidates[index]["id"] for index in ranked[:5]])
        self.assertEqual(result[5]["cutoff_tie"]["candidate_count"], 5)
        self.assertEqual(result[5]["cutoff_tie"]["gold_candidate_count"], 1)
        self.assertEqual(result[5]["expected_hit_probability"], 0.8)
        self.assertEqual(result[5]["worst_hit"], 0)
        self.assertEqual(result[5]["best_hit"], 1)

    def test_random_tie_order_uses_exact_hypergeometric_probability(self) -> None:
        candidates = [candidate(value) for value in ("a", "b", "c", "d")]
        scores = [0.5, 0.5, 0.5, 0.5]
        ranked, groups = build_score_groups(scores, candidates)

        result = tie_sensitivity(
            scores, candidates, {"c", "d"}, ranked, groups, cutoffs=(2,)
        )

        self.assertAlmostEqual(result[2]["expected_hit_probability"], 5 / 6)
        self.assertAlmostEqual(result[2]["expected_recall"], 0.5)
        self.assertEqual(result[2]["worst_recall"], 0.0)
        self.assertEqual(result[2]["best_recall"], 1.0)

    def test_cutoff_at_a_tie_boundary_is_deterministic(self) -> None:
        candidates = [candidate(value) for value in ("gold", "a", "b", "c")]
        scores = [0.9, 0.5, 0.5, 0.5]
        ranked, groups = build_score_groups(scores, candidates)

        result = tie_sensitivity(
            scores, candidates, {"gold"}, ranked, groups, cutoffs=(1, 3, 4)
        )

        self.assertEqual(result[1]["expected_hit_probability"], 1.0)
        self.assertEqual(result[4]["expected_hit_probability"], 1.0)
        self.assertIsNone(result[4]["cutoff_tie"])

    def test_score_groups_partition_the_complete_candidate_universe(self) -> None:
        candidates = [candidate(value) for value in ("d", "a", "c", "b")]
        scores = [0.5, 0.5, 0.25, 0.25]

        ranked, groups = build_score_groups(scores, candidates)

        self.assertEqual(len(ranked), 4)
        self.assertEqual([group["candidate_count"] for group in groups], [2, 2])
        self.assertEqual(groups[0]["candidate_ids"], ["a", "d"])
        self.assertEqual(groups[1]["candidate_ids"], ["b", "c"])

    def test_zero_score_candidates_abstain_and_are_not_tied_retrievals(self) -> None:
        candidates = [candidate(value) for value in ("zero-gold", "a", "b")]
        scores = [0.0, 0.6, 0.6]
        ranked, groups = build_score_groups(scores, candidates)

        result = tie_sensitivity(scores, candidates, {"zero-gold"}, ranked, groups)

        self.assertEqual([candidates[index]["id"] for index in ranked], ["a", "b"])
        self.assertEqual(groups[0]["candidate_count"], 2)
        self.assertEqual(result[1]["gold_candidates_in_score_universe"], 1)
        self.assertEqual(result[1]["gold_candidates_with_positive_scores"], 0)
        self.assertEqual(result[1]["zero_score_gold_candidate_ids"], ["zero-gold"])
        self.assertEqual(result[1]["expected_hit_probability"], 0.0)
        self.assertEqual(result[1]["actual_hit"], False)


if __name__ == "__main__":
    unittest.main()
