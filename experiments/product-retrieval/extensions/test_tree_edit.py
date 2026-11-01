"""Exact ordered-tree edit-distance regressions with bounded diagnostics."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import tree_edit
from tree_edit import (
    METHOD_METADATA,
    METHODS,
    TreeEditBudgetExceeded,
    TreeEditIncompleteInput,
    TreeEditUnavailable,
    score_candidates,
    score_candidates_with_diagnostics,
)


def subtree(
    labels: list[str],
    parents: list[int | None],
    positions: list[int],
    sibling_counts: list[int],
    *,
    complete: bool = True,
    status: str = "complete",
) -> dict[str, object]:
    return {
        "complete": complete,
        "status": status,
        "nodes": [
            {
                "label": label,
                "parent": parent,
                "position": position,
                "sibling_count": sibling_count,
            }
            for label, parent, position, sibling_count in zip(
                labels, parents, positions, sibling_counts, strict=True
            )
        ],
    }


def item(
    identifier: str,
    tree: dict[str, object],
    *,
    text: str = "ignored visible text",
    attribute_value: str = "ignored-attribute-value",
) -> dict[str, object]:
    return {
        "id": identifier,
        "node_id": f"node-{identifier}",
        "projection": "text",
        "text": text,
        "context": "ignored context",
        "tag": "main",
        "attributes": {"data-private": attribute_value},
        "path": ["html", "body", "main"],
        "motifs": ["shape"],
        "ancestors": [f"ancestor-{identifier}"],
        "subtree": tree,
    }


def chain(*labels: str) -> dict[str, object]:
    parents = [None, *range(len(labels) - 1)]
    return subtree(
        list(labels),
        parents,
        [0] * len(labels),
        [1] * len(labels),
    )


class ExactDistanceTests(unittest.TestCase):
    def test_identical_ordered_trees_have_similarity_one(self) -> None:
        tree = chain("element:main[]", "element:section[]", "element:span[]")
        scores, diagnostics = score_candidates_with_diagnostics(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("candidate", tree)],
            [item("reference", tree)],
        )
        self.assertEqual(scores, [1.0])
        self.assertEqual(diagnostics["status"], "complete")
        self.assertEqual(diagnostics["exact_distance_calls"], 1)

    def test_insert_delete_and_relabel_use_unit_operation_costs(self) -> None:
        source = chain("element:main[]", "element:section[]", "element:span[]")
        promoted_child = chain("element:main[]", "element:span[]")
        deleted = score_candidates(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("source", source)],
            [item("deleted-intermediate", promoted_child)],
        )[0]
        # Deleting section promotes span to its parent: distance 1; node sum 5.
        self.assertAlmostEqual(deleted, 1.0 - 1.0 / 5.0)

        relabeled = chain("element:main[]", "element:section[]", "element:time[]")
        updated = score_candidates(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("source", source)],
            [item("updated-leaf", relabeled)],
        )[0]
        # One leaf relabel across two three-node trees: distance 1; node sum 6.
        self.assertAlmostEqual(updated, 1.0 - 1.0 / 6.0)

    def test_child_insertion_and_promoted_child_are_tree_edits_not_root_only(
        self,
    ) -> None:
        root_only = chain("element:main[]")
        root_with_child = chain("element:main[]", "element:span[]")
        inserted = score_candidates(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("root-only", root_only)],
            [item("with-child", root_with_child)],
        )[0]
        self.assertAlmostEqual(inserted, 1.0 - 1.0 / 3.0)

        with_intermediate = chain(
            "element:main[]", "element:section[]", "element:span[]"
        )
        without_intermediate = chain("element:main[]", "element:span[]")
        promoted = score_candidates(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("with-intermediate", with_intermediate)],
            [item("without-intermediate", without_intermediate)],
        )[0]
        self.assertAlmostEqual(promoted, 0.8)
        self.assertLess(promoted, 1.0)

    def test_sibling_order_is_significant(self) -> None:
        left = subtree(
            ["element:main[]", "element:h1[]", "element:span[]"],
            [None, 0, 0],
            [0, 0, 1],
            [1, 2, 2],
        )
        reversed_children = subtree(
            ["element:main[]", "element:span[]", "element:h1[]"],
            [None, 0, 0],
            [0, 0, 1],
            [1, 2, 2],
        )
        score = score_candidates(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("left", left)],
            [item("reversed", reversed_children)],
        )[0]
        # Two relabels or delete+insert are required in an ordered tree.
        self.assertAlmostEqual(score, 1.0 - 2.0 / 6.0)

    def test_reference_aggregation_uses_max(self) -> None:
        tree = chain("element:main[]", "element:span[]")
        far = chain("element:button[]")
        score = score_candidates(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("candidate", tree)],
            [item("far", far), item("match", tree)],
        )[0]
        self.assertEqual(score, 1.0)


class InputAndBudgetTests(unittest.TestCase):
    def test_missing_incomplete_or_oversized_tree_is_diagnosed(self) -> None:
        valid = chain("element:main[]")
        incomplete = subtree(
            ["element:main[]"],
            [None],
            [0],
            [1],
            complete=False,
            status="truncated_node_limit",
        )
        scores, diagnostics = score_candidates_with_diagnostics(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("valid", valid), item("missing", valid) | {"subtree": None}],
            [item("incomplete", incomplete)],
        )
        self.assertEqual(scores, [0.0, 0.0])
        self.assertEqual(diagnostics["status"], "partial")
        self.assertEqual(diagnostics["unmatched_candidates"], 1)
        self.assertEqual(diagnostics["unmatched_references"], 1)
        self.assertEqual(
            diagnostics["candidate_shape_statuses"],
            {"complete": 1, "missing_subtree": 1},
        )
        self.assertEqual(
            diagnostics["reference_shape_statuses"],
            {"truncated_node_limit": 1},
        )
        with self.assertRaises(TreeEditIncompleteInput):
            score_candidates(
                tree_edit.TREE_EDIT_METHOD,
                {},
                [item("valid", valid)],
                [item("incomplete", incomplete)],
            )

        large = chain(*[f"element:n{index}[]" for index in range(4)])
        _, oversized_diagnostics = score_candidates_with_diagnostics(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("large", large)],
            [item("valid", valid)],
            max_tree_nodes=3,
        )
        self.assertEqual(
            oversized_diagnostics["candidate_shape_statuses"], {"tree_node_limit": 1}
        )

    def test_comparison_and_work_budgets_never_return_silent_full_scores(self) -> None:
        tree_a = chain("element:main[]", "element:section[]")
        tree_b = chain("element:main[]", "element:span[]")
        candidates = [item("a", tree_a), item("b", tree_b)]
        reference = [item("ref", tree_a)]
        partial, diagnostics = score_candidates_with_diagnostics(
            tree_edit.TREE_EDIT_METHOD,
            {},
            candidates,
            reference,
            max_pair_comparisons=1,
        )
        self.assertEqual(diagnostics["status"], "budget_exhausted")
        self.assertEqual(diagnostics["pairs_skipped_by_comparison_budget"], 1)
        self.assertEqual(len(partial), 2)
        with self.assertRaises(TreeEditBudgetExceeded):
            score_candidates(
                tree_edit.TREE_EDIT_METHOD,
                {},
                candidates,
                reference,
                max_pair_comparisons=1,
            )

        _, work_diagnostics = score_candidates_with_diagnostics(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("a", tree_a)],
            [item("ref", tree_b)],
            max_total_estimated_work=1,
        )
        self.assertEqual(work_diagnostics["status"], "budget_exhausted")
        self.assertEqual(work_diagnostics["exact_distance_calls"], 0)
        self.assertEqual(work_diagnostics["pairs_skipped_by_work_budget"], 1)

    def test_pair_distance_cache_uses_only_normalized_tree_shapes(self) -> None:
        tree = chain("element:main[data-private]", "element:span[]")
        candidates = [
            item("left-id", tree, text="private text A", attribute_value="value A"),
            item("right-id", tree, text="private text B", attribute_value="value B"),
        ]
        scores, diagnostics = score_candidates_with_diagnostics(
            tree_edit.TREE_EDIT_METHOD,
            {},
            candidates,
            [
                item(
                    "reference-id",
                    tree,
                    text="private text C",
                    attribute_value="value C",
                )
            ],
        )
        self.assertEqual(scores, [1.0, 1.0])
        self.assertEqual(diagnostics["exact_distance_calls"], 1)
        self.assertEqual(diagnostics["distance_cache_hits"], 1)

    def test_tree_label_schema_rejects_text_or_attribute_values(self) -> None:
        unsafe = chain("element:main[data-private=secret]")
        _, diagnostics = score_candidates_with_diagnostics(
            tree_edit.TREE_EDIT_METHOD,
            {},
            [item("candidate", unsafe)],
            [item("reference", unsafe)],
        )
        self.assertEqual(diagnostics["status"], "partial")
        self.assertEqual(
            diagnostics["candidate_shape_statuses"], {"unsafe_or_invalid_label": 1}
        )

    def test_lazy_dependency_absence_is_explicit(self) -> None:
        valid = chain("element:main[]")
        with patch.object(
            tree_edit,
            "_load_zss",
            side_effect=TreeEditUnavailable(
                "zss unavailable", {"status": "unavailable", "dependency": "zss"}
            ),
        ):
            scores, diagnostics = score_candidates_with_diagnostics(
                tree_edit.TREE_EDIT_METHOD,
                {},
                [item("candidate", valid)],
                [item("reference", valid)],
            )
            self.assertEqual(scores, [0.0])
            self.assertEqual(diagnostics["status"], "unavailable")
            with self.assertRaises(TreeEditUnavailable):
                score_candidates(
                    tree_edit.TREE_EDIT_METHOD,
                    {},
                    [item("candidate", valid)],
                    [item("reference", valid)],
                )

    def test_methods_and_normalization_metadata_are_public(self) -> None:
        self.assertEqual(METHODS, [tree_edit.TREE_EDIT_METHOD])
        metadata = METHOD_METADATA[tree_edit.TREE_EDIT_METHOD]
        self.assertEqual(
            metadata["similarity"],
            "1 - exact_distance / (candidate_node_count + reference_node_count)",
        )
        self.assertIn("exact Zhang-Shasha", metadata["algorithm"])


if __name__ == "__main__":
    unittest.main()
