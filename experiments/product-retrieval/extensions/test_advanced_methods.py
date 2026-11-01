"""Independent tests for CWS math and bounded ordered-tree features."""

from __future__ import annotations

import math
import unittest

from advanced_methods import (
    ADVANCED_METHODS,
    _cws_signature,
    prepare_case,
    score_candidates,
    structural_feature_weights,
    weighted_jaccard,
)


def candidate(
    *,
    identifier: str = "candidate-a",
    text: str = "price value",
    tag: str = "span",
    path: list[str] | None = None,
    motifs: list[str] | None = None,
    attributes: dict[str, str] | None = None,
    subtree: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": identifier,
        "node_id": identifier,
        "projection": "text",
        "text": text,
        "context": "price label",
        "tag": tag,
        "path": path or ["html", "body", tag],
        "motifs": motifs or ["field-row"],
        "attributes": attributes or {"class": "generated-value"},
        "ancestors": ["document-root"],
        **({"subtree": subtree} if subtree is not None else {}),
    }


def subtree(
    labels: list[str],
    parents: list[int | None],
    positions: list[int],
    counts: list[int],
):
    return {
        "complete": True,
        "status": "complete",
        "nodes": [
            {
                "label": label,
                "parent": parent,
                "position": position,
                "sibling_count": count,
            }
            for label, parent, position, count in zip(
                labels, parents, positions, counts, strict=True
            )
        ],
    }


def small_case() -> dict[str, object]:
    nodes = [
        {"id": 0, "kind": "document", "children": [1]},
        {
            "id": 1,
            "kind": "element",
            "tag_name": "main",
            "attributes": [{"name": "data-record", "value": "secret-id"}],
            "children": [2, 5],
        },
        {
            "id": 2,
            "kind": "element",
            "tag_name": "h1",
            "attributes": [{"name": "id", "value": "product-title"}],
            "children": [3],
        },
        {"id": 3, "kind": "text", "value": "Secret product name", "children": []},
        {
            "id": 5,
            "kind": "element",
            "tag_name": "span",
            "attributes": [{"name": "class", "value": "private-class"}],
            "children": [6],
        },
        {"id": 6, "kind": "text", "value": "$12.50", "children": []},
    ]
    return {
        "document": {"root": 0, "nodes": nodes},
        "candidates": [
            candidate(identifier="1", tag="main"),
            candidate(identifier="5", tag="span"),
        ],
        # Preparation must never inspect these evaluation-only fields.
        "expected": {"price": ["secret-gold"]},
        "expected_values": {"price": "$12.50"},
        "owning_root_id": "1",
    }


class WeightedJaccardTests(unittest.TestCase):
    def test_exact_weighted_jaccard_matches_hand_calculation(self) -> None:
        left = {"shared": 2.0, "left-only": 1.0}
        right = {"shared": 1.0, "right-only": 2.0}
        # Intersection mass 1; union mass 2 + 1 + 2.
        self.assertAlmostEqual(weighted_jaccard(left, right), 0.2)
        self.assertEqual(weighted_jaccard({}, {"x": 1.0}), 0.0)
        self.assertEqual(weighted_jaccard({}, {}), 0.0)

    def test_exact_control_uses_the_same_public_feature_map_as_the_sketch(self) -> None:
        left = candidate(path=["html", "body", "span"], motifs=["label-value"])
        right = candidate(
            path=["html", "body", "span"],
            motifs=["label-value"],
            identifier="reference",
        )
        self.assertEqual(
            score_candidates("weighted_jaccard_exact", {}, [left], [right]),
            [1.0],
        )
        self.assertEqual(
            structural_feature_weights(left), structural_feature_weights(right)
        )

    def test_weights_reject_negative_nonfinite_or_unnamed_features(self) -> None:
        for invalid in (
            {"bad": -1.0},
            {"bad": math.inf},
            {"": 1.0},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                weighted_jaccard(invalid, {})


class ConsistentWeightedSamplingTests(unittest.TestCase):
    def test_signatures_are_deterministic_and_order_independent(self) -> None:
        left = {"alpha": 1.0, "beta": 0.5, "gamma": 2.0}
        reordered = {"gamma": 2.0, "alpha": 1.0, "beta": 0.5}
        self.assertEqual(_cws_signature(left, 64), _cws_signature(left, 64))
        self.assertEqual(_cws_signature(left, 128), _cws_signature(reordered, 128))
        self.assertEqual(len(_cws_signature(left, 64)), 64)
        self.assertEqual(len(_cws_signature(left, 128)), 128)

    def test_identical_and_disjoint_vectors_have_expected_collision_limits(
        self,
    ) -> None:
        same = {"a": 1.0, "b": 2.0}
        disjoint = {"c": 1.0, "d": 2.0}
        self.assertEqual(_cws_signature(same, 128), _cws_signature(same, 128))
        self.assertFalse(
            any(
                left == right
                for left, right in zip(
                    _cws_signature(same, 128),
                    _cws_signature(disjoint, 128),
                    strict=True,
                )
            )
        )

    def test_sketch_collision_rate_tracks_a_known_weighted_jaccard(self) -> None:
        left = {"shared": 1.0, "left": 1.0}
        right = {"shared": 1.0, "right": 1.0}
        exact = weighted_jaccard(left, right)
        candidate_left = candidate(
            path=["html", "body", "shared"], motifs=["left"], attributes={}
        )
        candidate_right = candidate(
            path=["html", "body", "shared"], motifs=["right"], attributes={}
        )
        # Compare the direct CWS primitives as well as method output. For an
        # ideal independent sample the collision mean estimates exact Jaccard;
        # a fixed hash-derived sequence should be close, not identical.
        estimate = (
            sum(
                first == second
                for first, second in zip(
                    _cws_signature(left, 128), _cws_signature(right, 128), strict=True
                )
            )
            / 128
        )
        self.assertLessEqual(abs(estimate - exact), 0.15)

        scores = score_candidates(
            "weighted_minhash_128", {}, [candidate_left], [candidate_right]
        )
        self.assertEqual(len(scores), 1)
        self.assertTrue(0.0 <= scores[0] <= 1.0)

    def test_reference_aggregation_is_max_over_seed_sketches(self) -> None:
        target = candidate(path=["html", "body", "span"], motifs=["shared"])
        matching = candidate(
            identifier="matching", path=["html", "body", "span"], motifs=["shared"]
        )
        unrelated = candidate(
            identifier="unrelated", path=["html", "body", "button"], motifs=["menu"]
        )
        score = score_candidates(
            "weighted_minhash_64", {}, [target], [unrelated, matching]
        )[0]
        self.assertEqual(score, 1.0)

    def test_feature_budget_is_an_explicit_error_not_silent_truncation(self) -> None:
        oversized = {f"feature-{index}": 1.0 for index in range(513)}
        with self.assertRaisesRegex(ValueError, "feature budget exceeded"):
            _cws_signature(oversized, 64)


class SubtreePreparationTests(unittest.TestCase):
    def test_prepare_case_adds_generic_subtrees_without_reading_gold(self) -> None:
        case = small_case()
        augmented, diagnostics = prepare_case(case)
        self.assertEqual(diagnostics["status"], "complete")
        self.assertEqual(diagnostics["complete_subtrees"], 2)
        self.assertEqual([item["id"] for item in augmented], ["1", "5"])
        encoded = json_dump(augmented)
        self.assertNotIn("Secret product name", encoded)
        self.assertNotIn("$12.50", encoded)
        self.assertNotIn("secret-id", encoded)
        self.assertNotIn("private-class", encoded)
        self.assertIn("data-record", encoded)

    def test_preparation_is_independent_of_evaluation_labels(self) -> None:
        first = small_case()
        second = small_case()
        second["expected"] = {"stock": ["different-label"]}
        second["expected_values"] = {"stock": "different value"}
        second["owning_root_id"] = "another-owner"
        self.assertEqual(prepare_case(first)[0], prepare_case(second)[0])

    def test_subtree_budget_reports_truncation_and_methods_abstain(self) -> None:
        augmented, diagnostics = prepare_case(
            small_case(), max_subtree_nodes=2, max_total_subtree_nodes=20
        )
        self.assertGreater(diagnostics["subtree_truncations"], 0)
        self.assertTrue(
            any(item["subtree_status"] == "truncated_node_limit" for item in augmented)
        )
        result = score_candidates(
            "ordered_tree_fragment_jaccard",
            {},
            [augmented[0]],
            [augmented[1]],
        )
        self.assertEqual(result, [0.0])

    def test_cycle_or_shared_child_is_rejected(self) -> None:
        case = small_case()
        document = case["document"]
        document["nodes"][1]["children"] = [1]
        with self.assertRaisesRegex(ValueError, "cycle or shared child"):
            prepare_case(case)

    def test_empty_candidate_list_has_explicit_diagnostic(self) -> None:
        case = small_case()
        case["candidates"] = []
        augmented, diagnostics = prepare_case(case)
        self.assertEqual(augmented, [])
        self.assertEqual(diagnostics["status"], "no_candidates")


class OrderedTreeFragmentTests(unittest.TestCase):
    def test_identical_tree_fragments_match_exactly(self) -> None:
        shape = subtree(
            ["element:main", "element:h1", "text"],
            [None, 0, 1],
            [0, 0, 0],
            [1, 1, 1],
        )
        candidate_left = candidate(identifier="left", subtree=shape)
        candidate_right = candidate(identifier="right", subtree=shape)
        self.assertEqual(
            score_candidates(
                "ordered_tree_fragment_jaccard",
                {},
                [candidate_left],
                [candidate_right],
            ),
            [1.0],
        )

    def test_changed_label_and_child_order_allow_partial_but_not_exact_match(
        self,
    ) -> None:
        left = subtree(
            ["element:main", "element:h1", "element:span"],
            [None, 0, 0],
            [0, 0, 1],
            [1, 2, 2],
        )
        reordered = subtree(
            ["element:main", "element:span", "element:h1"],
            [None, 0, 0],
            [0, 0, 1],
            [1, 2, 2],
        )
        score = score_candidates(
            "ordered_tree_fragment_jaccard",
            {},
            [candidate(subtree=left)],
            [candidate(identifier="ref", subtree=reordered)],
        )[0]
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_missing_subtree_and_incomplete_reference_abstain(self) -> None:
        valid = candidate(subtree=subtree(["element:main"], [None], [0], [1]))
        incomplete = candidate(
            identifier="incomplete",
            subtree={"complete": False, "status": "truncated_node_limit", "nodes": []},
        )
        self.assertEqual(
            score_candidates(
                "ordered_tree_fragment_jaccard", {}, [valid], [incomplete]
            ),
            [0.0],
        )
        self.assertEqual(
            score_candidates(
                "ordered_tree_fragment_jaccard", {}, [candidate()], [valid]
            ),
            [0.0],
        )

    def test_metadata_names_the_partial_kernel_and_its_bounds(self) -> None:
        metadata = ADVANCED_METHODS["ordered_tree_fragment_jaccard"]
        self.assertIn("not full tree edit", metadata["interpretation"])
        self.assertEqual(metadata["max_subtree_nodes"], 128)
        self.assertEqual(metadata["max_fragment_edges"], 4)


def json_dump(value: object) -> str:
    import json

    return json.dumps(value, sort_keys=True)


if __name__ == "__main__":
    unittest.main()
