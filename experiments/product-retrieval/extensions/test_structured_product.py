"""Focused tests for the structured Product/Offer research extractor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from structured_product import evaluate_persisted, extract_page


def page(markup: str) -> dict:
    payload = markup.encode("utf-8")
    return extract_page(payload, "fixture", "https://example.test/item", None)


class StructuredProductTests(unittest.TestCase):
    def test_malformed_json_and_non_json_constants_are_partial(self) -> None:
        for body in (
            '{"@context":"https://schema.org","@type":"Product",',
            '{"@context":"https://schema.org","@type":"Product","offers":{"@type":"Offer","price":NaN}}',
            '{"@context":"https://schema.org","@type":"Product","@type":"Offer"}',
        ):
            result = page(f'<script type="application/ld+json">{body}</script>')
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["candidateProducts"], [])
            self.assertTrue(
                any("malformed_jsonld" in issue for issue in result["issues"])
            )

    def test_multiple_graph_offers_remain_distinct_and_keep_explicit_currency(
        self,
    ) -> None:
        result = page("""<script type="application/ld+json">
        {"@context":"https://schema.org/","@graph":[
          {"@id":"#p","@type":"Product","name":"Lamp","offers":[{"@id":"#o1"},{"@id":"#o2"}]},
          {"@id":"#o1","@type":"Offer","price":"20.00","priceCurrency":"USD","availability":"https://schema.org/InStock"},
          {"@id":"#o2","@type":"Offer","price":"18.50"}
        ]}</script>""")
        self.assertEqual(len(result["candidateProducts"]), 1)
        self.assertEqual(len(result["candidateOffers"]), 2)
        product = result["candidateProducts"][0]
        self.assertEqual(len(product["offer_refs"]), 2)
        by_id = {offer["schema_id"]: offer for offer in result["candidateOffers"]}
        self.assertEqual(by_id["#o1"]["fields"]["price"][0]["value"], "20.00")
        self.assertEqual(by_id["#o1"]["fields"]["priceCurrency"][0]["value"], "USD")
        self.assertEqual(by_id["#o2"]["fields"]["priceCurrency"], [])
        self.assertEqual(
            by_id["#o2"]["monetary_evidence"]["status"],
            "partial_amount_without_explicit_currency",
        )
        self.assertEqual(by_id["#o1"]["availability"][0]["enum"], "in_stock")
        self.assertIn("json_pointer", by_id["#o1"]["fields"]["price"][0]["source"])
        self.assertIsNotNone(by_id["#o1"]["source"]["script_start_byte"])

    def test_graph_reference_cycle_is_bounded_and_reported(self) -> None:
        result = page("""<script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[
          {"@id":"#p","@type":"Product","offers":{"@id":"#p"}}
        ]}</script>""")
        product = result["candidateProducts"][0]
        self.assertEqual(product["offer_refs"], [])
        self.assertEqual(
            product["unresolved_offer_references"][0]["resolution"], "cycle"
        )

    def test_availability_prose_is_not_promoted_to_a_stock_enum(self) -> None:
        result = page("""<script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Offer",
          "availability": "In stock (3 available)"
        }
        </script>""")
        availability = result["candidateOffers"][0]["availability"][0]
        self.assertEqual(availability["enum"], "unknown")
        self.assertEqual(availability["value_kind"], "text")
        self.assertEqual(availability["raw_value"], "In stock (3 available)")

    def test_jsonld_compact_names_without_schema_context_are_not_expanded(self) -> None:
        result = page("""<script type="application/ld+json">
        {"@type":"https://schema.org/Product","name":"Unexpanded"}
        </script>""")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["candidateProducts"][0]["fields"]["name"], [])
        self.assertIn(
            "compact_schema_properties_without_schema_context", result["issues"]
        )

    def test_microdata_nested_scope_does_not_borrow_sibling_product_properties(
        self,
    ) -> None:
        result = page("""<div itemscope itemtype="https://schema.org/Product">
          <span itemprop="name">First</span>
          <span itemprop="color">Light <b>Blue</b> shell</span>
          <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
            <meta itemprop="price" content="10.00">
            <meta itemprop="priceCurrency" content="USD">
          </div>
        </div>
        <div itemscope itemtype="https://schema.org/Product">
          <span itemprop="name">Second</span>
        </div>""")
        self.assertEqual(len(result["candidateProducts"]), 2)
        self.assertEqual(len(result["candidateOffers"]), 1)
        first, second = result["candidateProducts"]
        self.assertEqual(first["fields"]["name"][0]["value"], "First")
        self.assertEqual(second["fields"]["name"][0]["value"], "Second")
        self.assertEqual(first["fields"]["color"][0]["value"], "Light Blue shell")
        self.assertEqual(len(first["offer_refs"]), 1)
        self.assertEqual(second["offer_refs"], [])
        self.assertEqual(
            result["candidateOffers"][0]["fields"]["price"][0]["value"], "10.00"
        )
        self.assertIsNotNone(first["source"]["start_byte"])
        self.assertIsNotNone(
            second["fields"]["name"][0]["source"]["start_tag_end_byte"]
        )

    def test_inline_schema_context_subset_and_numeric_lexeme(self) -> None:
        result = page("""<script type="application/ld+json">
        {"@context":{"@vocab":"https://schema.org/"},"@type":"Product",
         "name":"Thing","offers":{"@type":"Offer","price":1.2300,"priceCurrency":"GBP"}}
        </script>""")
        offer = result["candidateOffers"][0]
        price = offer["fields"]["price"][0]
        self.assertEqual(price["value"], "1.2300")
        self.assertEqual(price["value_kind"], "json_number_token")
        self.assertEqual(len(result["candidateProducts"][0]["offer_refs"]), 1)

    def test_raw_price_display_and_typed_money_evaluations_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            offer = {
                "candidate_id": "fixture:offer:1",
                "fields": {
                    "price": [{"value": "$416.99", "value_kind": "text_content"}],
                    "priceCurrency": [{"value": "USD", "value_kind": "html_content"}],
                },
                "monetary_evidence": {
                    "status": "one_price_value_and_explicit_currency",
                    "amount_raw": "$416.99",
                    "currency_raw": "USD",
                },
                "availability": [],
            }
            extraction = {
                "format": "product-retrieval-structured-v1",
                "cpu_seconds": 0.001,
                "pages": [
                    {
                        "page_id": "fixture",
                        "status": "complete",
                        "candidateProducts": [],
                        "candidateOffers": [offer],
                    }
                ],
            }
            corpus = {
                "cases": [
                    {
                        "id": "fixture",
                        "expected_values": {},
                        "canonical_values": {
                            "price": {"amount": "416.99", "currency": "USD"}
                        },
                        "expected_status": {},
                    }
                ]
            }
            labels = {
                "annotation_status": "manual, not blind",
                "pages": [
                    {
                        "id": "fixture",
                        "contract_fields": {
                            "price": {"status": "present", "display": "$416.99"}
                        },
                    }
                ],
            }
            extraction_path = output / "extraction.json"
            extraction_path.write_text(json.dumps(extraction), encoding="utf-8")
            corpus_path = output / "corpus.json"
            corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
            labels_path = output / "labels.json"
            labels_path.write_text(json.dumps(labels), encoding="utf-8")

            evaluated = evaluate_persisted(output, corpus_path, labels_path)
            fields = evaluated["pages"][0]["fields"]
            self.assertEqual(
                fields["price_raw_display"]["status"], "exact_raw_display_match"
            )
            self.assertEqual(
                fields["price_amount_currency"]["status"],
                "uncomparable_price_format_or_currency_text",
            )


if __name__ == "__main__":
    unittest.main()
