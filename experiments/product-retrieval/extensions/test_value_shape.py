"""Small tests for the Unicode value-form retrieval channel."""

from __future__ import annotations

import unicodedata
import unittest

from value_shape import (
    GATE_METADATA,
    METHOD_METADATA,
    build_reference_prototypes,
    form_features,
    multiplicative_shape_gate,
    profile_provenance,
    score_candidates,
)


def item(text: str, **extra):
    return {
        "id": f"item-{len(text)}",
        "node_id": "n1",
        "projection": "text",
        "text": text,
        **extra,
    }


class ValueShapeTests(unittest.TestCase):
    def test_currency_symbols_share_shape_without_currency_specific_rules(self) -> None:
        self.assertEqual(form_features("$12.50"), form_features("£12.50"))
        for method in ("value_shape_jaccard_max", "value_shape_cosine_max"):
            score = score_candidates(
                method,
                {"field": "price", "description": "purchase price"},
                [item("$12.50")],
                [item("£12.50")],
            )[0]
            self.assertEqual(score, 1.0)

    def test_changed_well_formed_price_still_matches_because_shape_is_not_correctness(
        self,
    ) -> None:
        score = score_candidates(
            "value_shape_jaccard_max",
            {"field": "price", "description": "purchase price"},
            [item("£99.99")],
            [item("£12.50")],
        )[0]
        self.assertEqual(score, 1.0)

    def test_name_form_differs_from_identifier_form_without_reading_lexemes(
        self,
    ) -> None:
        name = form_features("Grid notebook")
        similar_name = form_features("Daily notebook")
        identifier = form_features("9780316069359")
        self.assertLess(
            _weighted_jaccard_for_test(name, identifier),
            _weighted_jaccard_for_test(name, similar_name),
        )
        self.assertFalse(
            any("grid" in feature or "notebook" in feature for feature in name)
        )

    def test_changed_numeric_value_with_same_length_has_same_form(self) -> None:
        self.assertEqual(
            form_features("9780316069359"),
            form_features("9780316069360"),
        )

    def test_unicode_letters_are_generic_across_scripts(self) -> None:
        left = form_features("产品 A")
        right = form_features("商品 B")
        self.assertEqual(left, right)
        self.assertEqual(
            profile_provenance()["unicode_database_version"],
            unicodedata.unidata_version,
        )

    def test_empty_evidence_scores_zero_instead_of_matching_vacuously(self) -> None:
        self.assertEqual(form_features(""), {})
        for method in METHOD_METADATA:
            self.assertEqual(
                score_candidates(method, {}, [item("")], [item("")]),
                [0.0],
            )
            self.assertEqual(
                score_candidates(method, {}, [item("£12.50")], [item("")]),
                [0.0],
            )

    def test_seed_prototypes_use_text_only_and_max_mean_aggregation_is_explicit(
        self,
    ) -> None:
        reference_a = item("£12.50", context="wrong label", attributes={"id": "x"})
        reference_b = item("A hardcover edition")
        prototypes = build_reference_prototypes([reference_a, reference_b])
        text_only = build_reference_prototypes(
            [item("£12.50"), item("A hardcover edition", context="other")]
        )
        self.assertEqual(prototypes, text_only)
        candidate = [
            item("$12.50", context="unrelated text", attributes={"class": "foo"})
        ]
        maximum = score_candidates(
            "value_shape_jaccard_max", {}, candidate, [reference_a, reference_b]
        )[0]
        mean = score_candidates(
            "value_shape_jaccard_mean", {}, candidate, [reference_a, reference_b]
        )[0]
        self.assertGreaterEqual(maximum, mean)
        self.assertEqual(METHOD_METADATA["value_shape_jaccard_max"]["family"], "form")
        self.assertEqual(
            METHOD_METADATA["value_shape_jaccard_mean"]["reference_aggregation"], "mean"
        )

    def test_optional_gate_is_bounded_and_not_a_probability(self) -> None:
        result = multiplicative_shape_gate([10.0, 10.0], [1.0, 0.0], strength=0.5)
        self.assertEqual(result, [10.0, 5.0])
        self.assertFalse(GATE_METADATA["output_is_probability"])
        with self.assertRaises(ValueError):
            multiplicative_shape_gate([1.0], [1.0], strength=1.1)
        with self.assertRaises(ValueError):
            multiplicative_shape_gate([-1.0], [1.0])


def _weighted_jaccard_for_test(left, right):
    keys = set(left) | set(right)
    denominator = sum(max(left.get(key, 0.0), right.get(key, 0.0)) for key in keys)
    return (
        sum(min(left.get(key, 0.0), right.get(key, 0.0)) for key in keys) / denominator
        if denominator
        else 0.0
    )


if __name__ == "__main__":
    unittest.main()
