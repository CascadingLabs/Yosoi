"""Evaluation regressions: missing evidence, wrong ownership and score identity."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_matrix
from run_matrix import evaluate, fuse, query_order, rank


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {"id": "a", "node_id": "1", "ancestors": ["root"], "context": "correct"},
            {"id": "b", "node_id": "2", "ancestors": ["decoy"], "context": "wrong"},
        ]

    def test_high_score_wrong_owner_is_not_success(self):
        result = evaluate([0.4, 0.9], self.candidates, ["a"], "root", "global")
        self.assertFalse(result["top1_correct"])
        self.assertFalse(result["owner_correct"])
        self.assertTrue(result["hit"]["3"])

    def test_scope_uses_predicted_root_not_gold(self):
        result = evaluate(
            [0.9, 0.8], self.candidates, ["a"], "root", "predicted_root", "decoy"
        )
        self.assertEqual(result["top"][0]["id"], "b")
        self.assertFalse(result["top1_correct"])

    def test_no_predicted_root_abstains(self):
        result = evaluate(
            [1, 1], self.candidates, ["a"], "root", "predicted_root", None
        )
        self.assertTrue(result["abstained"])

    def test_absent_field_positive_result_is_false_positive(self):
        result = evaluate([0.2, 0.1], self.candidates, [], "root", "global")
        self.assertFalse(result["top1_correct"])
        self.assertFalse(result["expected_present"])

    def test_zero_scores_abstain_including_fusion(self):
        scores = fuse("rrf", {"empty": [0, 0]}, self.candidates, None)
        result = evaluate(scores, self.candidates, [], "root", "global")
        self.assertTrue(result["top1_correct"])

    def test_nonfinite_negative_or_wrong_length_rejected(self):
        for scores in ([float("nan"), 1], [-1, 0], [1]):
            with self.assertRaises(ValueError):
                rank(scores, self.candidates)

    def test_aliases_count_as_one_retrieved_field(self):
        result = evaluate([1, 0.5], self.candidates, ["a", "b"], "root", "global")
        self.assertTrue(result["hit"]["1"])
        self.assertEqual(result["reciprocal_rank"], 1)

    def test_serialized_queries_still_resolve_root_before_fields(self):
        queries = json.loads(
            json.dumps({"root": "root", "price": "price"}, sort_keys=True)
        )
        self.assertEqual(list(queries), ["price", "root"])
        self.assertEqual(query_order(queries), ["root", "price"])

    def test_full_run_scopes_price_after_root_from_sorted_frozen_json(self):
        candidates = [
            {
                "id": "r",
                "node_id": "r",
                "projection": "text",
                "ancestors": [],
                "context": "product",
            },
            {
                "id": "p",
                "node_id": "p",
                "projection": "text",
                "ancestors": ["r"],
                "context": "price",
            },
        ]

        def case(identity):
            return {
                "id": identity,
                "source_id": identity,
                "variant": "original",
                "family": "test",
                "split": "controlled",
                "candidates": candidates,
                "expected": {"root": ["r"], "price": ["p"]},
                "canonical_expected": {"root": ["r"], "price": ["p"]},
                "owning_root_id": "r",
            }

        data = {"cases": [case("seed"), case("target")], "references": ["seed"]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            frozen = {
                "corpus_checksum": run_matrix.checksum(data),
                "implementation": run_matrix.implementation(),
                "queries": {"price": "price", "root": "root"},
                "methods": ["token_jaccard"],
                "reference_groups": [{"id": "seed", "cases": ["seed"]}],
                "representations": ["context"],
                "fusion": [],
                "selection_modes": ["global", "predicted_root"],
            }
            run_matrix.save(output / "corpus.json", data)
            run_matrix.save(output / "frozen.json", frozen)

            def scorer(_method, query, *_args):
                return ([1.0, 0.0] if query["field"] == "root" else [0.0, 1.0], 1)

            with patch.object(run_matrix, "score_one", side_effect=scorer):
                run_matrix.run(output)
            rows = json.loads((output / "report.json").read_text())["rows"]
            row = next(
                r
                for r in rows
                if r["case"] == "target"
                and r["field"] == "price"
                and r["mode"] == "predicted_root"
            )
            self.assertTrue(row["top1_correct"])
            self.assertFalse(row["abstained"])


if __name__ == "__main__":
    unittest.main()
