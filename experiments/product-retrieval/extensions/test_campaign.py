"""Tiny, deterministic campaign tests; no models, browser or live sources."""

from __future__ import annotations

import gzip
import hashlib
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

campaign = importlib.import_module("campaign")
run_matrix = importlib.import_module("run_matrix")
_bootstrap_corpus = importlib.import_module("corpus")
build_candidates = _bootstrap_corpus.build_candidates


def _tiny_case(case_id: str, family: str, split: str, external_id: bool) -> dict:
    product_id = "URL-42" if external_id else case_id
    root_attributes = []
    if not external_id:
        root_attributes = [
            {"namespace_uri": "", "name": "data-product-id", "value": product_id}
        ]
    document = {
        "document_epoch": 1,
        "nodes": [
            {"kind": "document", "id": 1, "parent": None, "children": [2]},
            {
                "kind": "element",
                "id": 2,
                "parent": 1,
                "children": [3],
                "namespace_uri": "http://www.w3.org/1999/xhtml",
                "tag_name": "html",
                "attributes": [],
            },
            {
                "kind": "element",
                "id": 3,
                "parent": 2,
                "children": [4, 6, 8],
                "namespace_uri": "http://www.w3.org/1999/xhtml",
                "tag_name": "article",
                "attributes": root_attributes,
            },
            {
                "kind": "element",
                "id": 4,
                "parent": 3,
                "children": [5],
                "namespace_uri": "http://www.w3.org/1999/xhtml",
                "tag_name": "h1",
                "attributes": [],
            },
            {
                "kind": "text",
                "id": 5,
                "parent": 4,
                "children": [],
                "value": "Sample Vessel",
            },
            {
                "kind": "element",
                "id": 6,
                "parent": 3,
                "children": [7],
                "namespace_uri": "http://www.w3.org/1999/xhtml",
                "tag_name": "span",
                "attributes": [
                    {"namespace_uri": "", "name": "class", "value": "price"}
                ],
            },
            {"kind": "text", "id": 7, "parent": 6, "children": [], "value": "$12.50"},
            {
                "kind": "element",
                "id": 8,
                "parent": 3,
                "children": [9],
                "namespace_uri": "http://www.w3.org/1999/xhtml",
                "tag_name": "p",
                "attributes": [
                    {"namespace_uri": "", "name": "class", "value": "stock"}
                ],
            },
            {
                "kind": "text",
                "id": 9,
                "parent": 8,
                "children": [],
                "value": "4 in stock",
            },
        ],
        "root": 1,
        "schema": "yosoi.rendered-dom.v1",
        "tree_model": "document_light_dom",
    }
    candidates = build_candidates(document, case_id)

    def refs(node_id: str, projection: str, value: str) -> list[str]:
        return [
            candidate["id"]
            for candidate in candidates
            if candidate["node_id"] == node_id
            and candidate["projection"] == projection
            and candidate["text"] == value
        ]

    expected = {
        field: []
        for field in ("root", "id", "name", "price", "color", "material", "stock")
    }
    expected["root"] = refs("3", "text", "Sample Vessel $12.50 4 in stock")
    expected["name"] = refs("4", "text", "Sample Vessel")
    expected["price"] = refs("6", "text", "$12.50")
    expected["stock"] = refs("8", "text", "4 in stock")
    if not external_id:
        expected["id"] = refs("3", "@data-product-id", product_id)
    canonical_expected = {key: list(value) for key, value in expected.items()}
    expected_present = {
        "root": True,
        "id": True,
        "name": True,
        "price": True,
        "color": False,
        "material": False,
        "stock": True,
    }
    expected_status = {
        "root": "present_dom",
        "id": "present_external_url" if external_id else "present_dom",
        "name": "present_dom",
        "price": "present_dom",
        "color": "absent",
        "material": "absent",
        "stock": "present_dom",
    }
    expected_values = {
        "id": product_id,
        "name": "Sample Vessel",
        "price": "$12.50",
        "stock": "4 in stock",
    }
    return {
        "id": case_id,
        "source_id": case_id,
        "split": split,
        "variant": "original",
        "family": family,
        "document": document,
        "candidates": candidates,
        "expected": expected,
        "canonical_expected": canonical_expected,
        "expected_values": expected_values,
        "expected_present": expected_present,
        "expected_status": expected_status,
        "canonical_values": {
            "identity": {
                "scheme": "url path" if external_id else "product attribute",
                "value": product_id,
                "evidence_scope": "external_url" if external_id else "dom",
            },
            "price": {"amount": "12.50", "currency": "USD"},
        },
        "owning_root_id": "3",
        "optional_fields": {},
        "provenance": {"source_representation": "tiny test fixture"},
    }


def _tiny_semantic_artifact(path: Path, texts: list[str]) -> None:
    identity = {
        "backend": "fastembed",
        "model": "test/model",
        "model_revision": "test-revision",
        "runtime": {
            "fastembed_version": "test",
            "onnxruntime_version": "test",
            "model_registry": {"model": "test/model"},
            "dimension": 2,
        },
        "configuration": {"normalize": True},
    }
    input_map = {}
    vectors = {}
    for text in texts:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        input_map[text] = {
            "original_sha256": digest,
            "embedding_input": text,
            "embedding_input_sha256": digest,
        }
        vectors[text] = [0.6, 0.8]
    payload = {
        "vectors": vectors,
        "metadata": {
            "identity": identity,
            "identity_sha256": campaign.checksum(identity),
            "dimension": 2,
            "input_count": len(texts),
            "unique_input_count": len(texts),
            "input_map": input_map,
        },
        "ledger": {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class CampaignTests(unittest.TestCase):
    def test_hybrids_are_cross_family_subsets_and_standalones_are_separate(
        self,
    ) -> None:
        choices = {
            "structure": ["s1", "s2"],
            "lexical": ["l1", "l2", "l3"],
            "semantic": ["m1"],
        }
        variants = list(
            campaign.hybrid_variants(choices, set(sum(choices.values(), [])))
        )
        self.assertEqual(len(variants), 17)
        self.assertTrue(all(len(variant) >= 2 for variant in variants))
        self.assertTrue(all(len(variant) == len(set(variant)) for variant in variants))

    def test_prefixed_semantic_ablation_changes_only_query_text(self) -> None:
        candidate = {
            "id": "c1",
            "node_id": "4",
            "projection": "text",
            "text": "Sample Vessel",
            "context": "parent=article | next=$12.50",
            "tag": "h1",
            "attributes": {},
            "path": ["#document", "html", "article", "h1"],
            "motifs": ["has-text"],
            "ancestors": ["1", "2", "3"],
        }
        captured = {}
        original = campaign.methods.score_candidates

        def spy(method, query, candidates, references, representation, vectors):
            captured.update(
                {
                    "method": method,
                    "query": query,
                    "candidate": candidates[0],
                    "references": references,
                    "representation": representation,
                }
            )
            return [0.5]

        campaign.methods.score_candidates = spy
        try:
            scores, diagnostics = campaign.score(
                campaign.PREFIXED_SEMANTIC_METHOD,
                {"field": "name", "description": "Product name"},
                [candidate],
                [],
                "value",
                {
                    (
                        "Represent this sentence for searching relevant "
                        "passages: Product name"
                    ): [1.0]
                },
            )
        finally:
            campaign.methods.score_candidates = original
        self.assertEqual(scores, [0.5])
        self.assertEqual(captured["method"], "semantic_query")
        self.assertEqual(
            captured["query"]["description"],
            campaign.SEMANTIC_QUERY_PREFIX + "Product name",
        )
        self.assertEqual(captured["candidate"]["text"], "Sample Vessel")
        self.assertEqual(captured["candidate"]["context"], candidate["context"])
        self.assertFalse(diagnostics["candidate_text_prefixed"])

    def test_semantic_artifact_identity_vectors_and_inputs_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "semantic.json"
            texts = ["query one", "candidate two"]
            _tiny_semantic_artifact(artifact, texts)
            _, identity = campaign.validate_semantic_artifact(artifact, texts)
            self.assertEqual(identity["input_count"], 2)
            self.assertEqual(identity["dimension"], 2)
            self.assertEqual(len(identity["artifact_sha256"]), 64)
            with self.assertRaisesRegex(ValueError, "exactly"):
                campaign.validate_semantic_artifact(artifact, [*texts, "extra"])

            payload = json.loads(artifact.read_text(encoding="utf-8"))
            payload["vectors"][texts[0]] = [float("nan"), 1.0]
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite"):
                campaign.validate_semantic_artifact(artifact, texts)

    def test_freeze_collect_and_tiny_run_preserve_denominators_and_snapshot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            base_path = temp / "base.json"
            fresh_path = temp / "fresh.json"
            output = temp / "campaign"
            base = {
                "cases": [
                    _tiny_case("seed-product", "seed-template", "development", False)
                ],
                "references": [],
                "provenance": {"source": "tiny base fixture"},
            }
            fresh = {
                "cases": [
                    _tiny_case(
                        "fresh-external", "fresh-template", "fresh_cross_site", True
                    )
                ],
                "provenance": {
                    "label_truth": "manual source label, not blind",
                    "document_truth": "tiny wire fixture",
                },
            }
            base_path.write_text(json.dumps(base), encoding="utf-8")
            fresh_path.write_text(json.dumps(fresh), encoding="utf-8")

            campaign.freeze(base_path, fresh_path, output)
            config = json.loads((output / "frozen.json").read_text(encoding="utf-8"))
            frozen_cases = json.loads(
                (output / "corpus.json").read_text(encoding="utf-8")
            )["cases"]
            for case in frozen_cases:
                for candidate in case["candidates"]:
                    self.assertNotIn("expected", candidate)
                    self.assertNotIn("expected_values", candidate)
                    self.assertNotIn("field_name", candidate)
            external_case = next(
                case for case in frozen_cases if case["id"] == "fresh-external"
            )
            self.assertEqual(external_case["expected"]["id"], [])
            self.assertNotIn(
                "URL-42",
                [candidate["text"] for candidate in external_case["candidates"]],
            )
            self.assertEqual(config["field_order"][0], "root")
            self.assertNotIn("color", config["queries"]["root"].casefold())
            self.assertNotIn("material", config["queries"]["root"].casefold())
            self.assertIn(
                "lexical_char_ngram_cosine_reference",
                config["channel_members"]["lexical"],
            )
            self.assertIn(
                campaign.PREFIXED_SEMANTIC_METHOD, config["channel_members"]["semantic"]
            )
            self.assertEqual(
                campaign.code_identity(output / "implementation"),
                config["code_identity"],
            )

            text_path = temp / "texts.json"
            texts = campaign.collect(output, text_path)
            self.assertIn(
                campaign.SEMANTIC_QUERY_PREFIX + config["queries"]["name"],
                texts,
            )
            self.assertIn(config["queries"]["name"], texts)
            self.assertEqual(
                campaign.checksum(texts), config["semantic_input_checksum"]
            )
            snapshot_texts = temp / "snapshot-texts.json"
            snapshot_script = output / "implementation" / "extensions" / "campaign.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(snapshot_script),
                    "collect",
                    "--output",
                    str(output),
                    "--destination",
                    str(snapshot_texts),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(snapshot_texts.read_text()), texts)

            snapshot_run = temp / "snapshot-run"
            snapshot_run.mkdir()
            for filename in ("corpus.json", "preparation.json", "frozen.json"):
                shutil.copyfile(output / filename, snapshot_run / filename)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(snapshot_script),
                    "run",
                    "--output",
                    str(snapshot_run),
                    "--group-filter",
                    "seed-template/1",
                    "--case-filter",
                    "fresh-external",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            snapshot_summary = json.loads(
                (snapshot_run / "summary.json").read_text(encoding="utf-8")
            )
            self.assertGreater(snapshot_summary["rows"], 0)

            previous_rank = run_matrix.rank
            summary = campaign.run(
                output,
                group_filter="seed-template/1",
                case_filter="fresh-external",
            )
            self.assertIs(run_matrix.rank, previous_rank)
            self.assertGreater(summary["exact_cache_ledger"]["rank"]["hits"], 0)
            self.assertFalse(
                summary["evaluation_disclosures"]["fresh_labels_are_blind"]
            )

            rows = [
                json.loads(line)
                for line in gzip.open(output / "rows.jsonl.gz", "rt", encoding="utf-8")
            ]
            external_id = next(
                row for row in rows if row["field"] == "id" and row["method"] == "bm25"
            )
            self.assertEqual(external_id["expected_status"], "present_external_url")
            self.assertTrue(external_id["expected_present"])
            self.assertFalse(external_id["evaluable"])
            self.assertFalse(external_id["operational_present"])
            self.assertIsNone(external_id["canonical_top1_correct"])
            absent_color = next(
                row
                for row in rows
                if row["field"] == "color" and row["method"] == "bm25"
            )
            self.assertEqual(absent_color["expected_status"], "absent")
            self.assertTrue(absent_color["evaluable"])
            present_price = next(
                row
                for row in rows
                if row["field"] == "price" and row["method"] == "bm25"
            )
            self.assertEqual(present_price["expected_status"], "present_dom")
            self.assertTrue(present_price["evaluable"])

    def test_partial_scores_are_operational_misses_and_latency_samples_stay_bounded(
        self,
    ) -> None:
        totals = campaign.Totals()
        for index in range(2_000):
            partial = index == 1_999
            row = {
                "method": "tree",
                "representation": "value",
                "mode": "global",
                "condition": "fresh",
                "field": "price",
                "score_status": "partial" if partial else "complete",
                "case": f"case-{index}",
                "group": "seed",
                "scoring_ns": index + 1,
                "evaluable": not partial,
                "expected_present": True,
                "top1_correct": None if partial else True,
                "owner_correct": None if partial else True,
                "abstained": partial,
                "hit": None if partial else {"1": True, "3": True, "5": True},
                "canonical_top1_correct": None if partial else True,
                "operational_present": True,
                "operational_hit": {"1": False, "3": False, "5": False}
                if partial
                else {"1": True, "3": True, "5": True},
                "operational_owner_correct": not partial,
            }
            totals.add(row)
        report = next(row for row in totals.export() if row["field"] == "price")
        self.assertEqual(report["evaluable"], 1_999)
        self.assertEqual(report["operational_present"], 2_000)
        self.assertEqual(report["operational_present_recall_at_1"], 1_999 / 2_000)
        self.assertLessEqual(
            report["all_attempt_latency_sample_size"], campaign.LATENCY_SAMPLE_CAP
        )
        self.assertLessEqual(
            report["dom_complete_latency_sample_size"], campaign.LATENCY_SAMPLE_CAP
        )


if __name__ == "__main__":
    unittest.main()
