"""Independent metric and invariance checks for retrieval scoring methods."""

from __future__ import annotations

import math
import unittest

from methods import METHOD_METADATA, METHODS, representation_text, score_candidates


def item(
    *,
    text: str = "",
    context: str = "",
    tag: str = "",
    path: list[str] | None = None,
    motifs: list[str] | None = None,
    attributes: dict[str, str] | None = None,
    identifier: str = "node-a",
) -> dict[str, object]:
    return {
        "id": identifier,
        "node_id": identifier,
        "projection": "test",
        "text": text,
        "context": context,
        "tag": tag,
        "attributes": attributes or {},
        "path": path or [],
        "motifs": motifs or [],
        "ancestors": [f"ancestor-{identifier}"],
    }


class RepresentationTests(unittest.TestCase):
    def test_representations_choose_expected_evidence(self) -> None:
        candidate = item(
            text="  $12.50  ",
            context="  Listed price  ",
            tag="span",
            path=["html", "body", "span"],
            motifs=["price-row"],
            attributes={"class": "p-8472", "data-sku": "MUG-1"},
        )
        self.assertEqual(representation_text(candidate, "value"), "$12.50")
        self.assertEqual(
            representation_text(candidate, "context"), "$12.50\nListed price"
        )
        structure_context = representation_text(candidate, "structure_context")
        self.assertIn("tag span", structure_context)
        self.assertIn("path html/body/span", structure_context)
        self.assertIn("motif price-row", structure_context)
        self.assertIn("attributes class data-sku", structure_context)

    def test_representation_omits_ids_and_attribute_values(self) -> None:
        candidate = item(
            text="Price",
            context="Product 12345",
            attributes={"id": "secret-12345", "class": "generated-abc"},
            identifier="snapshot-987",
        )
        structure = representation_text(candidate, "structure_context")
        self.assertNotIn("snapshot-987", structure)
        self.assertNotIn("secret-12345", structure)
        self.assertNotIn("generated-abc", structure)

    def test_unknown_representation_fails_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown representation"):
            representation_text(item(text="x"), "whole-page")


class StructureMetricTests(unittest.TestCase):
    def test_structural_weighted_jaccard_matches_hand_calculation(self) -> None:
        candidate = item(
            tag="div",
            path=["html", "body", "main"],
            motifs=["label-value"],
        )
        reference = item(
            tag="span",
            path=["html", "body", "main"],
            motifs=["label-value"],
        )
        score = score_candidates("structural_jaccard", {}, [candidate], [reference])[0]
        # Exact path contributes 3, shared motif 1; differing tags contribute
        # .75 each to the union. (3 + 1) / (3 + 1 + .75 + .75) = 8/11.
        self.assertAlmostEqual(score, 8.0 / 11.0)

    def test_structural_reference_max_and_documented_mean(self) -> None:
        candidate = item(tag="span", path=["html", "body", "span"])
        matching = item(tag="span", path=["html", "body", "span"])
        unrelated = item(tag="button", path=["html", "body", "button"])
        maximum = score_candidates(
            "structural_weighted_jaccard", {}, [candidate], [matching, unrelated]
        )[0]
        average = score_candidates(
            "structural_weighted_jaccard_avg", {}, [candidate], [matching, unrelated]
        )[0]
        self.assertEqual(maximum, 1.0)
        self.assertAlmostEqual(average, 0.5)
        self.assertEqual(
            METHOD_METADATA["structural_weighted_jaccard_avg"]["reference_aggregation"],
            "mean",
        )

    def test_hierarchical_jaccard_aggregates_feature_categories(self) -> None:
        candidate = item(
            tag="span",
            path=["html", "body", "section"],
            motifs=["price-row"],
            attributes={"class": "a"},
        )
        reference = item(
            tag="span",
            path=["html", "body", "aside"],
            motifs=["other-row"],
            attributes={"role": "b"},
        )
        score = score_candidates("hierarchical_jaccard", {}, [candidate], [reference])[
            0
        ]
        # The tag category matches exactly. Path prefixes overlap at html and
        # html/body (2/4); motifs and attribute names do not overlap.
        self.assertAlmostEqual(score, 0.35)

    def test_local_jaccard_ignores_path_and_tag(self) -> None:
        candidate = item(
            tag="span", path=["html", "body", "span"], motifs=["price-row", "amount"]
        )
        reference = item(
            tag="button", path=["html", "body", "button"], motifs=["price-row"]
        )
        score = score_candidates("local_jaccard", {}, [candidate], [reference])[0]
        self.assertAlmostEqual(score, 1.0 / 2.0)

    def test_path_edit_similarity_uses_levenshtein_normalization(self) -> None:
        candidate = item(path=["html", "body", "div", "span"])
        reference = item(path=["html", "body", "div", "time"])
        score = score_candidates("path_edit", {}, [candidate], [reference])[0]
        self.assertAlmostEqual(score, 0.75)

    def test_reference_methods_rank_by_similarity_not_node_identity(self) -> None:
        reference = item(
            text="12 dollars",
            context="Listed price",
            tag="span",
            path=["html", "body", "span"],
            motifs=["price-row"],
            identifier="seed-id",
        )
        close = item(
            text="13 dollars",
            context="Listed price",
            tag="span",
            path=["html", "body", "span"],
            motifs=["price-row"],
            identifier="different-id",
        )
        far = item(
            text="blue ceramic",
            context="Material detail",
            tag="button",
            path=["html", "body", "button"],
            motifs=["navigation"],
            identifier="seed-id",
        )
        structural = score_candidates(
            "structural_jaccard", {}, [close, far], [reference]
        )
        lexical = score_candidates(
            "lexical_token_jaccard_reference", {}, [close, far], [reference]
        )
        self.assertGreater(structural[0], structural[1])
        self.assertGreater(lexical[0], lexical[1])


class LexicalMetricTests(unittest.TestCase):
    def test_token_jaccard_query_ranks_overlap(self) -> None:
        query = {"field": "price", "description": "listed price in dollars"}
        candidates = [
            item(text="price label"),
            item(text="dollars listed price"),
        ]
        scores = score_candidates("token_jaccard", query, candidates, [], "value")
        self.assertAlmostEqual(scores[0], 1.0 / 5.0)
        self.assertAlmostEqual(scores[1], 3.0 / 4.0)
        self.assertGreater(scores[1], scores[0])

    def test_bm25_query_prefers_more_relevant_document(self) -> None:
        query = {"field": "price", "description": "price listed"}
        candidates = [
            item(text="price product title"),
            item(text="price amount listed"),
        ]
        scores = score_candidates("bm25", query, candidates, [], "value")
        self.assertGreater(scores[1], scores[0])
        self.assertEqual(max(scores), 1.0)

    def test_tfidf_cosine_query_prefers_lexical_overlap(self) -> None:
        query = {"field": "material", "description": "composition"}
        candidates = [item(text="material composition"), item(text="shipping status")]
        scores = score_candidates("tfidf_cosine", query, candidates, [], "value")
        self.assertAlmostEqual(scores[0], 1.0)
        self.assertEqual(scores[1], 0.0)

    def test_character_ngrams_help_with_spelling_variation(self) -> None:
        query = {"field": "color", "description": "colour"}
        candidates = [item(text="color"), item(text="engine")]
        scores = score_candidates(
            "lexical_char_ngram_cosine_query", query, candidates, [], "value"
        )
        self.assertGreater(scores[0], scores[1])
        self.assertGreater(scores[0], 0.0)

    def test_reference_lexical_max_uses_best_seed(self) -> None:
        references = [item(text="blue glaze"), item(text="ceramic material")]
        candidates = [item(text="ceramic surface"), item(text="shipping date")]
        scores = score_candidates(
            "lexical_token_jaccard_reference", {}, candidates, references, "value"
        )
        self.assertAlmostEqual(scores[0], 1.0 / 3.0)
        self.assertEqual(scores[1], 0.0)


class SemanticAndSketchTests(unittest.TestCase):
    def test_semantic_query_uses_exact_description_key(self) -> None:
        query = {"field": "price", "description": "  Listed price  "}
        candidate = item(text="$12.50")
        vectors = {
            "  Listed price  ": [1.0, 0.0],
            "$12.50": [0.8, 0.6],
        }
        score = score_candidates(
            "semantic_query", query, [candidate], [], "value", vectors
        )[0]
        self.assertAlmostEqual(score, 0.8)

    def test_semantic_reference_uses_max_seed_cosine(self) -> None:
        references = [item(text="blue glaze"), item(text="ceramic material")]
        candidate = item(text="ceramic surface")
        vectors = {
            "ceramic surface": [1.0, 0.0],
            "blue glaze": [0.0, 1.0],
            "ceramic material": [0.6, 0.8],
        }
        score = score_candidates(
            "semantic_reference", {}, [candidate], references, "value", vectors
        )[0]
        self.assertAlmostEqual(score, 0.6)

    def test_semantic_missing_mismatched_and_invalid_vectors_abstain(self) -> None:
        candidates = [item(text="one"), item(text="two"), item(text="three")]
        query = {"field": "label", "description": "label description"}
        vectors = {
            "label description": [1.0, 0.0],
            "one": [1.0],  # dimension mismatch
            "two": [math.nan, 1.0],
            "three": [0.0, 0.0],
        }
        scores = score_candidates(
            "semantic_query", query, candidates, [], "value", vectors
        )
        self.assertEqual(scores, [0.0, 0.0, 0.0])

    def test_simhashes_are_deterministic_and_rank_close_text_higher(self) -> None:
        reference = item(text="glazed ceramic price details")
        close = item(text="glazed ceramic price information")
        far = item(text="shipping address tracking")
        for method in ("simhash64_lexical_reference", "simhash128_lexical_reference"):
            scores = score_candidates(method, {}, [close, far], [reference], "value")
            self.assertGreater(scores[0], scores[1])
            reordered = score_candidates(method, {}, [far, close], [reference], "value")
            self.assertEqual(reordered, [scores[1], scores[0]])
            self.assertEqual(
                score_candidates(method, {}, [close], [reference], "value"),
                [scores[0]],
            )

    def test_structural_simhash_ignores_text_and_snapshot_ids(self) -> None:
        reference = item(
            tag="section", path=["html", "body", "section"], motifs=["row"]
        )
        same_shape = item(
            text="different content",
            tag="section",
            path=["html", "body", "section"],
            motifs=["row"],
            identifier="another-snapshot-node",
        )
        different_shape = item(tag="button", path=["html", "body", "button"])
        scores = score_candidates(
            "simhash64_structure_reference",
            {},
            [same_shape, different_shape],
            [reference],
        )
        self.assertEqual(scores[0], 1.0)
        self.assertGreater(scores[0], scores[1])


class ContractTests(unittest.TestCase):
    def test_runner_core_method_ids_are_exposed(self) -> None:
        expected = {
            "hierarchical_jaccard",
            "structural_jaccard",
            "local_jaccard",
            "bm25",
            "tfidf_cosine",
            "token_jaccard",
            "path_edit",
            "semantic_query",
            "semantic_reference",
        }
        self.assertTrue(expected.issubset(set(METHODS)))

    def test_all_methods_return_finite_nonnegative_scores_in_candidate_order(
        self,
    ) -> None:
        query = {"field": "price", "description": "price in dollars"}
        candidates = [
            item(text="price $12", path=["html", "body", "span"], motifs=["price"]),
            item(
                text="material ceramic",
                path=["html", "body", "div"],
                motifs=["material"],
            ),
        ]
        references = [
            item(text="price label", path=["html", "body", "span"], motifs=["price"])
        ]
        for method in METHODS:
            with self.subTest(method=method):
                scores = score_candidates(method, query, candidates, references)
                self.assertEqual(len(scores), len(candidates))
                self.assertTrue(
                    all(
                        math.isfinite(score) and 0.0 <= score <= 1.0 for score in scores
                    )
                )

    def test_empty_evidence_and_empty_references_abstain(self) -> None:
        empty = item()
        for method in METHODS:
            with self.subTest(method=method):
                scores = score_candidates(method, {}, [empty], [])
                self.assertEqual(scores, [0.0])
        self.assertEqual(score_candidates("bm25", {}, [], []), [])

    def test_candidate_identity_fields_do_not_change_scores(self) -> None:
        reference = item(
            text="price amount", path=["html", "body", "span"], identifier="seed"
        )
        first = item(
            text="price amount", path=["html", "body", "span"], identifier="first"
        )
        second = item(
            text="price amount", path=["html", "body", "span"], identifier="second"
        )
        methods = [
            "structural_jaccard",
            "hierarchical_jaccard",
            "lexical_token_jaccard_reference",
            "path_edit",
            "simhash64_structure_reference",
        ]
        for method in methods:
            with self.subTest(method=method):
                first_score = score_candidates(method, {}, [first], [reference])[0]
                second_score = score_candidates(method, {}, [second], [reference])[0]
                self.assertEqual(first_score, second_score)

    def test_unknown_method_fails_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown method"):
            score_candidates("hidden_oracle", {}, [item(text="x")], [])


if __name__ == "__main__":
    unittest.main()
