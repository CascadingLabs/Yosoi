"""Small plan and count-join checks for the one-vs-two reference driver."""

from __future__ import annotations

import unittest

from reference_count_wave import match_aggregate_rows, select_matched_targets


class ReferenceCountPlanTests(unittest.TestCase):
    def test_selects_first_disjoint_target_per_template_in_plan_order(self) -> None:
        target_plan = {
            "targets": [
                {
                    "case": "books-sophies-world",
                    "family": "books_to_scrape",
                    "group": "books_to_scrape/2",
                },
                {
                    "case": "books-join",
                    "family": "books_to_scrape",
                    "group": "books_to_scrape/2",
                },
                {
                    "case": "webscraper-thinkpad-t540p",
                    "family": "webscraper_ecommerce_static",
                    "group": "webscraper_ecommerce_static/2",
                },
                {
                    "case": "webscraper-probook",
                    "family": "webscraper_ecommerce_static",
                    "group": "webscraper_ecommerce_static/2",
                },
                {
                    "case": "scrapeme-venusaur",
                    "family": "scrapeme_woocommerce",
                    "group": "scrapeme_woocommerce/2",
                },
                {
                    "case": "scrapeme-charmander",
                    "family": "scrapeme_woocommerce",
                    "group": "scrapeme_woocommerce/2",
                },
            ]
        }
        frozen = {
            "reference_groups": [
                {"id": "books_to_scrape/1", "cases": ["books-obsession"]},
                {
                    "id": "books_to_scrape/2",
                    "cases": ["books-obsession", "books-original-fake"],
                },
                {
                    "id": "webscraper_ecommerce_static/1",
                    "cases": ["webscraper-packard-255-g2"],
                },
                {
                    "id": "webscraper_ecommerce_static/2",
                    "cases": ["webscraper-packard-255-g2", "webscraper-aspire-e1-510"],
                },
                {"id": "scrapeme_woocommerce/1", "cases": ["scrapeme-bulbasaur"]},
                {
                    "id": "scrapeme_woocommerce/2",
                    "cases": ["scrapeme-bulbasaur", "scrapeme-ivysaur"],
                },
            ]
        }

        selected = select_matched_targets(target_plan, frozen)

        self.assertEqual(
            [item["case"] for item in selected],
            ["books-sophies-world", "webscraper-thinkpad-t540p", "scrapeme-venusaur"],
        )
        for item in selected:
            self.assertEqual(len(item["one_reference_cases"]), 1)
            self.assertEqual(len(item["two_reference_cases"]), 2)
            self.assertTrue(
                set(item["one_reference_cases"]) < set(item["two_reference_cases"])
            )
            self.assertNotIn(item["case"], item["two_reference_cases"])

    def test_rejects_target_in_reference_set(self) -> None:
        with self.assertRaisesRegex(ValueError, "target must be disjoint"):
            select_matched_targets(
                {
                    "targets": [
                        {
                            "case": "books-obsession",
                            "family": "books_to_scrape",
                            "group": "books_to_scrape/2",
                        }
                    ]
                },
                {
                    "reference_groups": [
                        {"id": "books_to_scrape/1", "cases": ["books-obsession"]},
                        {
                            "id": "books_to_scrape/2",
                            "cases": ["books-obsession", "books-original-fake"],
                        },
                    ]
                },
            )

    def test_matched_join_keeps_cohort_counts_statuses_and_timings_separate(
        self,
    ) -> None:
        key = {
            "encoder": "minilm",
            "method": "structural_jaccard",
            "representation": "context",
            "mode": "global",
            "condition": "annotator_seen_same_template",
            "field": "name",
        }
        one = {
            **key,
            "unique_cases": 3,
            "present": 3,
            "hit1": 1,
            "recall_at_1": 1 / 3,
            "score_status_counts": {"complete": 3},
            "page_median_scoring_ms_min": 4.0,
            "page_median_scoring_ms_max": 6.0,
        }
        two = {
            **key,
            "unique_cases": 3,
            "present": 3,
            "hit1": 2,
            "recall_at_1": 2 / 3,
            "score_status_counts": {"complete": 2, "partial": 1},
            "page_median_scoring_ms_min": 8.0,
            "page_median_scoring_ms_max": 10.0,
        }

        joined = match_aggregate_rows({"metrics": [one]}, {"metrics": [two]})[0]

        self.assertEqual(joined["one_reference"]["hit1"], 1)
        self.assertEqual(joined["two_references"]["hit1"], 2)
        self.assertEqual(
            joined["one_reference"]["score_status_counts"], {"complete": 3}
        )
        self.assertEqual(
            joined["two_references"]["score_status_counts"],
            {"complete": 2, "partial": 1},
        )
        self.assertEqual(joined["one_reference"]["page_median_scoring_ms_max"], 6.0)
        self.assertEqual(joined["two_references"]["page_median_scoring_ms_max"], 10.0)


if __name__ == "__main__":
    unittest.main()
