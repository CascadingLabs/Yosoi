"""Ensure diagnostic evidence cannot verify unrelated SDK operations."""

import unittest

from run_diagnostics_conformance import payload_checks, select_comparisons


class DiagnosticAttributionTests(unittest.TestCase):
    def test_payload_evidence_requires_the_actual_tag_and_payload(self):
        entry = {
            "argumentMappings": [{"rustArgument": "0", "pythonArgument": "value"}],
            "variantBinding": {"discriminator": "kind", "tag": "browser_failure"},
        }
        selected = [
            {
                "rust": {"kind": "browser_failure", "value": "launch"},
                "python": {"kind": "browser_failure", "value": "launch"},
            }
        ]
        self.assertTrue(payload_checks(entry, selected)[0]["equal"])
        selected[0]["python"]["value"] = "timeout"
        self.assertFalse(payload_checks(entry, selected)[0]["equal"])
        selected[0]["python"] = {"kind": "wrong", "value": "launch"}
        self.assertFalse(payload_checks(entry, selected)[0]["equal"])
        selected[0]["python"] = {"kind": "browser_failure"}
        self.assertFalse(payload_checks(entry, selected)[0]["equal"])

    def test_payload_fixture_labels_can_cover_multiple_values_of_one_variant(self):
        entry = {
            "decision": "mapped",
            "rustPath": "yosoi::request::UnprojectableReason::UnknownSourceFormat",
            "argumentMappings": [
                {"rustArgument": "reason", "pythonArgument": "reason"}
            ],
            "variantBinding": {"discriminator": "kind", "tag": "unknown_source_format"},
        }
        comparisons = [
            {
                "rustType": "UnprojectableReason",
                "variant": "UnknownSourceFormatEmpty",
                "rust": {"kind": "unknown_source_format", "reason": "empty"},
            },
            {
                "rustType": "UnprojectableReason",
                "variant": "UnknownSourceFormatNoStrongSignature",
                "rust": {
                    "kind": "unknown_source_format",
                    "reason": "no_strong_signature",
                },
            },
            {
                "rustType": "UnprojectableReason",
                "variant": "DocumentRejected",
                "rust": {"kind": "document_rejected"},
            },
        ]
        self.assertEqual(select_comparisons(entry, comparisons), comparisons[:2])

    def test_selects_type_or_exact_variant_and_excludes_traits(self):
        comparisons = [
            {"rustType": "Rejection", "variant": "InvalidUrl"},
            {"rustType": "Rejection", "variant": "Credentials"},
            {"rustType": "PartialReason", "variant": "Limited"},
        ]
        entry = {"decision": "mapped", "rustPath": "yosoi::map::Rejection"}
        self.assertEqual(select_comparisons(entry, comparisons), comparisons[:2])
        entry["rustPath"] += "::Credentials"
        self.assertEqual(select_comparisons(entry, comparisons), comparisons[1:2])
        entry["rustPath"] = "yosoi::map::Rejection::fmt"
        entry["trait"] = "Display"
        self.assertEqual(select_comparisons(entry, comparisons), [])

    def test_unreviewed_or_argument_mappings_receive_no_evidence(self):
        comparison = [{"rustType": "Rejection", "variant": "InvalidUrl"}]
        entry = {"decision": "proposed", "rustPath": "yosoi::map::Rejection"}
        self.assertEqual(select_comparisons(entry, comparison), [])
        entry.update(decision="mapped", argumentMappings=[{"rustArgument": "input"}])
        self.assertEqual(select_comparisons(entry, comparison), [])


if __name__ == "__main__":
    unittest.main()
