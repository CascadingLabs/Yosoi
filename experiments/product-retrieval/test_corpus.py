"""Bounded contract tests for the product retrieval corpus builder."""

from __future__ import annotations

import unittest
from pathlib import Path

from corpus import FIELD_NAMES, build_candidates, prepare_corpus

EVIDENCE_DIR = (
    Path(__file__).resolve().parents[1]
    / "contract-fingerprints"
    / "fixtures"
    / "evidence"
)
EXPECTED_CANDIDATE_KEYS = {
    "id",
    "node_id",
    "projection",
    "text",
    "context",
    "tag",
    "attributes",
    "path",
    "motifs",
    "ancestors",
}


class ProductRetrievalCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = prepare_corpus(EVIDENCE_DIR)
        cls.cases = {case["id"]: case for case in cls.corpus["cases"]}

    def test_matrix_has_six_originals_and_nine_independent_variants_per_source(
        self,
    ) -> None:
        self.assertEqual(len(self.corpus["cases"]), 60)
        for source_number in range(1, 7):
            source_id = f"obj-{source_number:03}"
            self.assertIn(source_id, self.cases)
            derived = [
                case
                for case in self.corpus["cases"]
                if case["source_id"] == source_id and case["variant"] != "original"
            ]
            self.assertEqual(len(derived), 9)
            self.assertTrue(
                all(case["id"].startswith(f"{source_id}.") for case in derived)
            )

    def test_reference_case_ids_and_split_are_explicit(self) -> None:
        self.assertEqual(self.corpus["references"], ["obj-001", "obj-002"])
        self.assertEqual(self.cases["obj-001"]["variant"], "original")
        self.assertEqual(self.cases["obj-002"]["variant"], "original")
        self.assertEqual(self.cases["obj-001"]["split"], "development")
        self.assertEqual(self.cases["obj-003"]["split"], "controlled")

    def test_archive_payload_checksums_and_lengths_are_recorded(self) -> None:
        sources = self.corpus["provenance"]["source_checksums"]
        self.assertEqual(len(sources), 6)
        for source in sources:
            self.assertEqual(len(source["payload_sha256"]), 64)
            self.assertEqual(len(source["archive_record_sha256"]), 64)
            self.assertGreater(source["payload_byte_len"], 0)
        self.assertEqual(
            self.corpus["provenance"]["archive_schema"], "yosoi_rendered_dom_v1"
        )

    def test_cases_include_replayable_documents_and_unlabeled_candidate_records(
        self,
    ) -> None:
        for case in self.corpus["cases"]:
            self.assertEqual(case["document"]["schema"], "yosoi.rendered-dom.v1")
            self.assertEqual(
                case["candidates"], build_candidates(case["document"], case["id"])
            )
            candidate_ids = [candidate["id"] for candidate in case["candidates"]]
            self.assertEqual(len(candidate_ids), len(set(candidate_ids)))
            self.assertTrue(case["candidates"])
            for candidate in case["candidates"]:
                self.assertEqual(set(candidate), EXPECTED_CANDIDATE_KEYS)
                self.assertIn(
                    candidate["projection"],
                    {"text", *(f"@{name}" for name in candidate["attributes"])},
                )
                self.assertTrue(candidate["path"])
                self.assertIsInstance(candidate["ancestors"], list)
                self.assertNotIn("expected", candidate)
                self.assertNotIn("field", candidate)

    def test_derived_dom_attributes_use_canonical_namespace_name_order(self) -> None:
        for case in self.corpus["cases"]:
            if case["variant"] == "original":
                continue
            for node in case["document"]["nodes"]:
                if node.get("kind") != "element":
                    continue
                attributes = node.get("attributes", [])
                keys = [
                    (attribute.get("namespace_uri", ""), attribute.get("name", ""))
                    for attribute in attributes
                ]
                self.assertEqual(keys, sorted(keys), case["id"])

    def test_gold_fields_are_exact_target_candidates_and_scoped_to_root(self) -> None:
        for case in self.corpus["cases"]:
            candidates = {
                candidate["id"]: candidate for candidate in case["candidates"]
            }
            root_id = case["owning_root_id"]
            self.assertEqual(len(case["expected"]["root"]), 1)
            self.assertEqual(
                candidates[case["expected"]["root"][0]]["node_id"], root_id
            )
            for field_name in FIELD_NAMES:
                candidate_ids = case["expected"][field_name]
                if not candidate_ids:
                    self.assertNotIn(field_name, case["expected_values"])
                    continue
                self.assertIn(field_name, case["expected_values"])
                for candidate_id in candidate_ids:
                    candidate = candidates[candidate_id]
                    self.assertEqual(
                        candidate["text"], case["expected_values"][field_name]
                    )
                    if field_name != "id":
                        self.assertIn(root_id, candidate["ancestors"])

    def test_original_stock_text_is_preserved_and_not_normalized_to_a_state_label(
        self,
    ) -> None:
        available = self.cases["obj-001"]["expected_values"]["stock"]
        unavailable = self.cases["obj-005"]["expected_values"]["stock"]
        self.assertEqual(available, "12 in stock and ready to find a home.")
        self.assertEqual(unavailable, "Currently unavailable.")

    def test_each_required_field_has_a_missing_field_control(self) -> None:
        missing_cases = [
            case for case in self.corpus["cases"] if case["variant"] == "missing_field"
        ]
        self.assertEqual(len(missing_cases), 6)
        missing_fields = set()
        for case in missing_cases:
            absent = [field for field in FIELD_NAMES if not case["expected"][field]]
            self.assertEqual(len(absent), 1)
            self.assertNotIn(absent[0], case["expected_values"])
            missing_fields.add(absent[0])
        self.assertEqual(missing_fields, set(FIELD_NAMES))

    def test_decoy_and_multiple_price_controls_keep_gold_ownership_explicit(
        self,
    ) -> None:
        for variant in ("recommendation_decoys", "repeated_nested_products"):
            case = self.cases[f"obj-003.{variant}"]
            root_id = case["owning_root_id"]
            candidate_ids = set(case["expected"]["root"])
            decoy_roots = {
                candidate["node_id"]
                for candidate in case["candidates"]
                if candidate["projection"] == "@data-product-id"
                and candidate["node_id"] != root_id
            }
            self.assertTrue(decoy_roots)
            self.assertTrue(all(node_id != root_id for node_id in decoy_roots))
            self.assertEqual(len(candidate_ids), 1)

        price_case = self.cases["obj-003.multiple_price_roles"]
        expected_price = price_case["expected_values"]["price"]
        candidate_price_values = {
            candidate["text"]
            for candidate in price_case["candidates"]
            if candidate["projection"] == "text" and "$" in candidate["text"]
        }
        self.assertIn(expected_price, candidate_price_values)
        self.assertGreaterEqual(len(candidate_price_values), 3)

    def test_alternate_layout_and_label_paraphrase_have_explicit_parameters(
        self,
    ) -> None:
        alternate = self.cases["obj-002.alternate_layout"]
        self.assertEqual(alternate["family"], "description_list")
        self.assertEqual(
            alternate["provenance"]["mutation"]["layout"], "article/header/dl"
        )
        self.assertEqual(
            alternate["expected_values"], self.cases["obj-002"]["expected_values"]
        )
        paraphrased = self.cases["obj-002.label_paraphrase"]
        self.assertEqual(
            paraphrased["provenance"]["mutation"]["labels"],
            {"material": "Composition", "color": "Finish"},
        )


if __name__ == "__main__":
    unittest.main()
