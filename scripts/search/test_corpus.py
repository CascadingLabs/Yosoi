"""Offline guardrails for serial corpus execution and result accounting."""

import argparse
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import run_corpus


class CorpusTests(unittest.TestCase):
    """Check the network opt-in, stop boundary, denominator, and relevance proxy."""

    def args(self, *, live=False):
        """Build a small authored corpus invocation without external state."""
        return argparse.Namespace(
            live=live,
            interface="cli",
            corpus=run_corpus.ROOT / "corpus.json",
            providers=["bing", "brave"],
            max_cells=3,
            output_dir=Path("unused"),
            source_revision=None,
            binary=None,
        )

    def test_default_skips_every_cell_without_identifying_or_running_binary(self):
        """No live flag means no executable access and no provider work."""
        with (
            patch.object(run_corpus, "identity") as identity,
            patch.object(run_corpus, "cli_search") as search,
        ):
            report = asyncio.run(run_corpus.run(self.args()))
        identity.assert_not_called()
        search.assert_not_called()
        self.assertEqual(report["denominator"], 12)
        self.assertEqual(report["skipped"], 12)
        self.assertEqual(report["executed"], 0)

    def test_rate_limit_stops_serial_work_and_keeps_remaining_cells(self):
        """A single provider rate limit preserves all skipped denominator cells."""
        result = {
            "status": "failed",
            "detail": "rate_limited",
            "attempts": [{"http_status": 429}],
            "hits": [],
        }
        with (
            patch.object(run_corpus, "identity", return_value={}),
            patch.object(run_corpus, "cli_search", return_value=result) as search,
            patch.object(Path, "mkdir"),
        ):
            report = asyncio.run(run_corpus.run(self.args(live=True)))
        self.assertEqual(search.call_count, 1)
        self.assertEqual(report["stop_reason"], "rate_limit")
        self.assertEqual(report["executed"], 1)
        self.assertEqual(report["skipped"], 11)
        self.assertEqual(report["denominator"], 12)

    def test_http_success_and_row_count_do_not_establish_relevance(self):
        """HTTP success can still produce rows that fail the corpus topic proxy."""
        row = run_corpus.cell(
            {
                "id": "control",
                "category": "ordinary",
                "relevance_terms": ["photosynthesis"],
            },
            "bing",
            {
                "status": "results",
                "hits": [{"url": "https://example.test/", "title": "Space telescopes"}],
                "attempts": [{"http_status": 200}],
            },
        )
        self.assertTrue(row["http_success"])
        self.assertEqual(row["hit_count"], 1)
        self.assertEqual(row["topic_matching_hits"], 0)
        self.assertFalse(row["useful_results_proxy"])
        self.assertFalse(row["query_intent_verified"])

    def test_sdk_translates_duckduckgo_cli_name_before_provider_selection(self):
        """The advertised CLI spelling reaches the SDK with its serialized name."""
        selection = Mock(side_effect=RuntimeError("stop before provider I/O"))
        modules = {
            "yosoi": SimpleNamespace(search=None),
            "yosoi.archive": SimpleNamespace(Archive=None),
            "yosoi.policy": SimpleNamespace(
                Policy=None, ProviderSelection=selection, Search=None
            ),
        }
        with (
            patch.dict(sys.modules, modules),
            self.assertRaisesRegex(RuntimeError, "stop before provider I/O"),
        ):
            asyncio.run(
                run_corpus.sdk_search(
                    self.args(), {"query": "synthetic control"}, "duckduckgo"
                )
            )
        selection.assert_called_once_with(provider="duck_duck_go")


if __name__ == "__main__":
    unittest.main()
