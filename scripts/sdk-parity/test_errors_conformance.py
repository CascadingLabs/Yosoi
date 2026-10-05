"""Focused checks for operation-error parity comparisons and attribution."""

import unittest

from run_errors_conformance import _compare_fixture, _evidence_cases

import parity


class OperationErrorConformanceTests(unittest.TestCase):
    def test_comparison_includes_category_metadata_message_and_sources(self):
        fixture = {
            "name": "opaque-request-error",
            "operationPath": "yosoi::request::BoundPageRequest::validate",
            "errorPath": "yosoi::request::RequestPreparationError",
            "input": {"target": "ftp://example.com", "policy": "default"},
            "error": {
                "rust_type": "yosoi::request::RequestPreparationError",
                "variant": None,
                "details": {"opaque": True},
                "message": "invalid request target",
                "source_chain": [],
            },
        }
        observed = {
            "input": dict(fixture["input"]),
            "error": dict(fixture["error"]),
            "exceptionType": "yosoi._native.RequestError",
            "expectedException": "yosoi.errors.RequestError",
            "exceptionMatches": True,
        }

        comparison = _compare_fixture(fixture, observed, parity)
        self.assertTrue(comparison["equal"])
        self.assertEqual(comparison["rustSha256"], comparison["pythonSha256"])

        observed["error"] = {**observed["error"], "source_chain": ["unexpected"]}
        mismatch = _compare_fixture(fixture, observed, parity)
        self.assertFalse(mismatch["equal"])

    def test_attribution_uses_only_mapped_symbols_that_the_fixture_exercises(self):
        operation_path = "yosoi::search::SearchRequest::new"
        empty_path = "yosoi::search::SearchQueryError::Empty"
        too_long_path = "yosoi::search::SearchQueryError::TooLong"
        ledger = {
            "entries": [
                {
                    "rustPath": operation_path,
                    "symbolKey": "operation:new",
                    "decision": "mapped",
                    "pythonTarget": "yosoi.search.SearchRequest",
                    "argumentMappings": [
                        {
                            "rustArgument": "query",
                            "pythonArgument": "query",
                        }
                    ],
                },
                {
                    "rustPath": empty_path,
                    "symbolKey": "variant:empty",
                    "decision": "mapped",
                    "pythonTarget": "yosoi.errors.SearchError",
                    "argumentMappings": [],
                },
                {
                    "rustPath": "yosoi::search::SearchQueryError",
                    "symbolKey": "type:query-error",
                    "decision": "mapped",
                    "pythonTarget": "yosoi.errors.SearchError",
                    "argumentMappings": [],
                },
                {
                    "rustPath": "yosoi::search::SearchQueryError::fmt",
                    "symbolKey": "trait:display",
                    "decision": "language-specific",
                    "trait": "Display",
                    "pythonTarget": "yosoi.errors.SearchError",
                    "argumentMappings": [],
                },
            ]
        }
        comparisons = [
            {
                "name": "empty-query",
                "operationPath": operation_path,
                "errorPath": empty_path,
                "equal": True,
                "rustSha256": "a" * 64,
                "pythonSha256": "a" * 64,
                "rust": {"input": {"query": " "}},
                "python": {"input": {"query": " "}},
            },
            {
                "name": "long-query",
                "operationPath": operation_path,
                "errorPath": too_long_path,
                "equal": True,
                "rustSha256": "b" * 64,
                "pythonSha256": "b" * 64,
                "rust": {"input": {"query": "é" * 256 + "x"}},
                "python": {"input": {"query": "é" * 256 + "x"}},
            },
        ]

        cases = _evidence_cases(comparisons, ledger)
        by_path = {case["rustPath"]: case for case in cases}
        self.assertEqual(set(by_path), {operation_path, empty_path})
        self.assertEqual(
            [item["name"] for item in by_path[operation_path]["comparisons"]],
            ["empty-query", "long-query"],
        )
        self.assertTrue(by_path[operation_path]["mappingChecks"][0]["equal"])

    def test_from_str_trait_attribution_requires_the_fixture_to_call_from_str(self):
        operation_path = "yosoi::request::ActivityId::from_str"
        error_path = "yosoi::request::ActivityId::Err"
        ledger = {
            "entries": [
                {
                    "rustPath": operation_path,
                    "symbolKey": "activity-id:from-str",
                    "decision": "mapped",
                    "trait": "FromStr",
                    "pythonTarget": "yosoi.request.ActivityId.from_str",
                    "argumentMappings": [],
                },
                {
                    "rustPath": error_path,
                    "symbolKey": "activity-id:err",
                    "decision": "mapped",
                    "pythonTarget": "yosoi.errors.RequestError",
                    "argumentMappings": [],
                },
            ]
        }
        comparison = {
            "name": "activity-id-invalid-uuid",
            "operationPath": operation_path,
            "operationTrait": None,
            "errorPath": error_path,
            "equal": True,
            "rustSha256": "c" * 64,
            "pythonSha256": "c" * 64,
        }

        cases = _evidence_cases([comparison], ledger)
        self.assertEqual([case["rustPath"] for case in cases], [error_path])

        comparison["operationTrait"] = "FromStr"
        cases = _evidence_cases([comparison], ledger)
        by_path = {case["rustPath"]: case for case in cases}
        self.assertEqual(set(by_path), {operation_path, error_path})
        self.assertEqual(by_path[operation_path]["trait"], "FromStr")


if __name__ == "__main__":
    unittest.main()
