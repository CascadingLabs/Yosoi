"""Focused checks for document-error fixture and exact-symbol attribution."""

import unittest

from run_document_errors_conformance import (
    EXPECTED_FIXTURE_NAMES,
    _evidence_cases,
    compare_fixture,
    validate_fixture_set,
)

import parity


def _fixture(name):
    return {
        "name": name,
        "operationPath": "yosoi::Document::parse",
        "errorPath": "yosoi::documents::ParseError::Document",
        "errorTypePath": "yosoi::documents::ParseError",
        "input": {"id": "bad-json", "content": "{"},
        "error": {
            "rust_type": "yosoi_engine::ParseError",
            "variant": "Document",
            "details": {
                "source": {
                    "rust_type": "yosoi_documents::DocumentParseError",
                    "message": "document ended before a complete value",
                }
            },
            "message": "document ended before a complete value",
            "source_chain": [],
        },
    }


class DocumentErrorsConformanceTests(unittest.TestCase):
    def test_fixture_contract_requires_each_named_rust_case_once(self):
        cases = [_fixture(name) for name in sorted(EXPECTED_FIXTURE_NAMES)]
        fixture_set = {
            "schemaVersion": 1,
            "kind": "yosoi-document-error-fixtures",
            "cases": cases,
        }

        self.assertEqual(len(validate_fixture_set(fixture_set)), 7)

        fixture_set["cases"].pop()
        with self.assertRaises(ValueError):
            validate_fixture_set(fixture_set)

    def test_comparison_requires_exact_error_metadata_and_source_chain(self):
        fixture = _fixture("document-parse-json-truncated")
        observed = {
            "input": dict(fixture["input"]),
            "error": dict(fixture["error"]),
            "exceptionType": "yosoi._native.ParseError",
            "expectedException": "yosoi.errors.ParseError",
            "exceptionMatches": True,
        }

        comparison = compare_fixture(fixture, observed, parity)
        self.assertTrue(comparison["equal"])
        self.assertEqual(comparison["rustSha256"], comparison["pythonSha256"])

        observed["error"] = {**observed["error"], "source_chain": ["guessed leaf"]}
        mismatch = compare_fixture(fixture, observed, parity)
        self.assertFalse(mismatch["equal"])

    def test_attribution_does_not_promote_unmapped_parse_variant(self):
        operation_path = "yosoi::Document::parse"
        error_type_path = "yosoi::documents::ParseError"
        variant_path = "yosoi::documents::ParseError::Document"
        ledger = {
            "entries": [
                {
                    "rustPath": operation_path,
                    "symbolKey": "document-parse-operation",
                    "decision": "mapped",
                    "pythonTarget": "yosoi.Document.parse",
                },
                {
                    "rustPath": error_type_path,
                    "symbolKey": "document-parse-type",
                    "decision": "mapped",
                    "pythonTarget": "yosoi.errors.ParseError",
                },
                {
                    "rustPath": variant_path,
                    "symbolKey": "document-parse-variant",
                    "decision": "missing",
                    "pythonTarget": None,
                },
            ]
        }
        comparison = {
            "name": "document-parse-json-truncated",
            "operationPath": operation_path,
            "errorPath": variant_path,
            "errorTypePath": error_type_path,
            "rust": {
                "input": {"id": "bad-json", "content": "{"},
                "error": _fixture("document-parse-json-truncated")["error"],
            },
            "equal": True,
            "rustSha256": "a" * 64,
            "pythonSha256": "a" * 64,
        }

        cases = _evidence_cases([comparison], ledger)

        self.assertEqual(len(cases), 1)
        attributed = {
            item["rustPath"] for item in cases[0]["matchedSymbols"]
        }
        self.assertEqual(attributed, {operation_path, error_type_path})
        self.assertNotIn(variant_path, attributed)


if __name__ == "__main__":
    unittest.main()
