"""Small boundary checks for the bounded synthetic scaling harness."""

from __future__ import annotations

import unittest

import scaling


class ScalingHarnessTests(unittest.TestCase):
    def test_case_plan_is_three_finite_one_axis_sweeps(self):
        plan = scaling.case_plan()

        self.assertEqual(len(plan), 17)
        self.assertEqual(
            [item["depth"] for item in plan if item["axis"] == "depth"],
            list(scaling.DEPTH_VALUES),
        )
        self.assertEqual(
            [item["width"] for item in plan if item["axis"] == "width"],
            list(scaling.WIDTH_VALUES),
        )
        self.assertEqual(
            [item["attribute_count"] for item in plan if item["axis"] == "attributes"],
            list(scaling.ATTRIBUTE_VALUES),
        )
        self.assertEqual(sum(item["tree_edit_probe"] for item in plan), 1)

    def test_small_width_document_has_checked_candidate_parent_links(self):
        shape = scaling.build_synthetic_document(
            {
                "case_id": "width-8",
                "axis": "width",
                "depth": 2,
                "width": 8,
                "attribute_count": 1,
            }
        )
        document_index = scaling.validate_synthetic_document(shape["document"])
        candidates = scaling.corpus.build_candidates(shape["document"], "width-8")
        links = scaling.validate_candidate_source_links(candidates, document_index)
        prepared, diagnostics = scaling.advanced_methods.prepare_case(
            {"document": shape["document"], "candidates": candidates}
        )

        self.assertEqual(document_index["max_node_depth"], 2)
        self.assertGreater(document_index["node_count"], 8)
        self.assertEqual(links["candidate_source_links_checked"], len(candidates))
        self.assertEqual(diagnostics["status"], "complete")
        self.assertEqual(len(prepared), len(candidates))

    def test_depth_256_is_valid_and_257_hits_the_existing_candidate_guard(self):
        at_limit = scaling.build_synthetic_document(
            {
                "case_id": "depth-256",
                "axis": "depth",
                "depth": 256,
                "width": 1,
                "attribute_count": 1,
            }
        )
        at_limit_index = scaling.validate_synthetic_document(at_limit["document"])
        self.assertEqual(at_limit_index["max_node_depth"], 256)
        self.assertTrue(
            scaling.corpus.build_candidates(at_limit["document"], "depth-256")
        )

        over_limit = scaling.build_synthetic_document(
            {
                "case_id": "depth-257",
                "axis": "depth",
                "depth": 257,
                "width": 1,
                "attribute_count": 1,
            }
        )
        over_limit_index = scaling.validate_synthetic_document(over_limit["document"])
        self.assertEqual(over_limit_index["max_node_depth"], 257)
        with self.assertRaisesRegex(ValueError, "candidate depth budget"):
            scaling.corpus.build_candidates(over_limit["document"], "depth-257")

    def test_attribute_feature_overflow_is_reported_by_existing_cws_guard(self):
        shape = scaling.build_synthetic_document(
            {
                "case_id": "attributes-513",
                "axis": "attributes",
                "depth": 2,
                "width": 1,
                "attribute_count": 513,
            }
        )
        document_index = scaling.validate_synthetic_document(shape["document"])
        candidates = scaling.corpus.build_candidates(
            shape["document"], "attributes-513"
        )
        scaling.validate_candidate_source_links(candidates, document_index)
        probe = next(
            item
            for item in candidates
            if item["node_id"] == str(shape["probe_node_id"])
            and item["projection"] == "@data-feature-0000"
        )
        weights = scaling.advanced_methods.structural_feature_weights(probe)

        self.assertGreater(len(weights), 512)
        with self.assertRaisesRegex(ValueError, "feature budget exceeded"):
            scaling.advanced_methods._cws_signature(weights, 64)


if __name__ == "__main__":
    unittest.main()
