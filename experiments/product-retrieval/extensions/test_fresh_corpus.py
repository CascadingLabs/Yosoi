"""Focused tests for fresh source-HTML corpus normalization and annotations."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from corpus import build_candidates
from fresh_corpus import build_fresh_corpus

ROOT = Path(__file__).resolve().parents[3]
FRESH_DIR = ROOT / ".generated" / "product-retrieval-fresh"
EXPECTED_KEYS = {
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


class FreshCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = build_fresh_corpus(FRESH_DIR)
        cls.cases = {case["id"]: case for case in cls.corpus["cases"]}

    def test_all_twelve_pages_cover_three_distinct_templates(self) -> None:
        self.assertEqual(len(self.cases), 12)
        self.assertEqual(
            {case["family"] for case in self.cases.values()},
            {"books_to_scrape", "webscraper_ecommerce_static", "scrapeme_woocommerce"},
        )
        self.assertTrue(
            all(case["split"] == "fresh_cross_site" for case in self.cases.values())
        )

    def test_source_hashes_and_saved_byte_lengths_match_manifest(self) -> None:
        manifest = json.loads((FRESH_DIR / "manifest.json").read_text(encoding="utf-8"))
        by_id = {page["id"]: page for page in manifest["pages"]}
        self.assertEqual(set(by_id), set(self.cases))
        for page_id, page in by_id.items():
            payload = (FRESH_DIR / page["file"]).read_bytes()
            self.assertEqual(len(payload), page["byte_len"], page_id)
            self.assertEqual(
                hashlib.sha256(payload).hexdigest(), page["sha256"], page_id
            )
            self.assertEqual(page["status"], 200, page_id)

    def test_documents_are_source_normalized_and_record_truthful_provenance(
        self,
    ) -> None:
        for case in self.cases.values():
            document = case["document"]
            self.assertEqual(document["schema"], "yosoi.rendered-dom.v1")
            self.assertEqual(document["tree_model"], "document_light_dom")
            self.assertEqual(document["document_epoch"], 1)
            provenance = case["provenance"]
            self.assertFalse(provenance["live_rendered_dom"])
            self.assertTrue(provenance["wire_epoch_is_synthetic"])
            self.assertIsNone(provenance["observed_browser_epoch"])
            self.assertEqual(
                provenance["source_representation"], "captured_http_response_html"
            )
            self.assertFalse(provenance["normalizer"]["javascript_executed"])
            self.assertEqual(len(provenance["source_html_sha256"]), 64)
            self.assertEqual(len(provenance["normalized_document_sha256"]), 64)
            for node in document["nodes"]:
                if node.get("kind") != "element":
                    continue
                attrs = node.get("attributes", [])
                keys = [
                    (attribute.get("namespace_uri", ""), attribute.get("name", ""))
                    for attribute in attrs
                ]
                self.assertEqual(keys, sorted(keys), case["id"])

    def test_generic_candidates_are_schema_only_and_replayable(self) -> None:
        for case in self.cases.values():
            candidates = case["candidates"]
            self.assertEqual(candidates, build_candidates(case["document"], case["id"]))
            self.assertTrue(candidates)
            self.assertEqual(len({item["id"] for item in candidates}), len(candidates))
            for candidate in candidates:
                self.assertEqual(set(candidate), EXPECTED_KEYS)
                self.assertNotIn("expected", candidate)
                self.assertNotIn("field_name", candidate)
                self.assertTrue(candidate["context"].startswith("parent="))
            by_id = {candidate["id"]: candidate for candidate in candidates}
            root_ids = case["expected"]["root"]
            self.assertEqual(len(root_ids), 1)
            self.assertEqual(by_id[root_ids[0]]["node_id"], case["owning_root_id"])

    def test_present_field_gold_points_into_the_annotated_owner(self) -> None:
        for case in self.cases.values():
            candidates = {
                candidate["id"]: candidate for candidate in case["candidates"]
            }
            root_id = case["owning_root_id"]
            for field in ("id", "name", "price", "color", "material", "stock"):
                if not case["expected"][field]:
                    continue
                self.assertTrue(case["expected_present"][field], (case["id"], field))
                self.assertIn(field, case["expected_values"])
                for candidate_id in case["expected"][field]:
                    candidate = candidates[candidate_id]
                    self.assertEqual(candidate["text"], case["expected_values"][field])
                    self.assertIn(root_id, candidate["ancestors"])
                    self.assertTrue(candidate["context"].startswith("parent="))

    def test_absent_contract_fields_are_explicit_and_have_no_gold_candidates(
        self,
    ) -> None:
        for case in self.cases.values():
            for field in ("color", "material"):
                self.assertFalse(case["expected_present"][field], (case["id"], field))
                self.assertEqual(case["expected_status"][field], "absent")
                self.assertEqual(case["expected"][field], [])
                self.assertNotIn(field, case["expected_values"])

        for case in self.cases.values():
            if case["family"] == "webscraper_ecommerce_static":
                self.assertFalse(case["expected_present"]["stock"])
                self.assertEqual(case["expected_status"]["stock"], "absent")
                self.assertEqual(case["expected"]["stock"], [])
                self.assertNotIn("stock", case["expected_values"])

    def test_url_only_ids_remain_present_but_unlocatable_in_dom(self) -> None:
        for page_id in (
            "webscraper-packard-255-g2",
            "webscraper-aspire-e1-510",
            "webscraper-thinkpad-t540p",
            "webscraper-probook",
        ):
            case = self.cases[page_id]
            self.assertTrue(case["expected_present"]["id"])
            self.assertEqual(case["expected_status"]["id"], "present_external_url")
            self.assertEqual(case["expected"]["id"], [])
            self.assertEqual(case["canonical_expected"]["id"], [])
            self.assertIn("id", case["expected_values"])
            self.assertEqual(
                case["canonical_values"]["identity"]["evidence_scope"], "external_url"
            )

    def test_currency_stays_attached_to_amount_without_exchange_rate_conversion(
        self,
    ) -> None:
        for case in self.cases.values():
            price = case["canonical_values"]["price"]
            self.assertEqual(
                price["currency"],
                "USD" if case["family"] == "webscraper_ecommerce_static" else "GBP",
            )
            self.assertTrue(price["amount"])
            self.assertEqual(case["expected_status"]["price"], "present_dom")

    def test_optional_values_are_retained_separately_from_contract_candidates(
        self,
    ) -> None:
        book = self.cases["books-obsession"]
        self.assertEqual(book["optional_fields"]["category"]["value"], "Romance")
        self.assertEqual(book["optional_fields"]["rating_class"]["value"], "One")
        shop = self.cases["scrapeme-bulbasaur"]
        self.assertEqual(shop["optional_fields"]["weight"], "15.2 kg")
        self.assertEqual(shop["optional_fields"]["dimensions"], "2 × 2 × 2 cm")
        self.assertEqual(shop["optional_fields"]["description"]["copied"], False)


if __name__ == "__main__":
    unittest.main()
