"""Reject malformed schema-error payloads and unproven ledger mappings."""

import copy
import unittest

from pydantic import TypeAdapter, ValidationError
from run_schema_errors_conformance import payload_checks, select_comparisons

from yosoi.contracts import (
    ContractSchemaFailure,
    RuntimeExtractionFailure,
    RuntimeValidationFailure,
)


class SchemaErrorPayloadTests(unittest.TestCase):
    def test_all_contract_schema_error_variants_accept_their_wire_shape(self):
        adapter = TypeAdapter(ContractSchemaFailure)
        payloads = [
            {"variant": "ZeroVersion", "details": {}},
            {"variant": "UnsupportedVersion", "details": {"observed": 2}},
            {"variant": "EmptyContractId", "details": {}},
            {"variant": "EmptyFieldId", "details": {}},
            {"variant": "EmptyContractDescription", "details": {}},
            {
                "variant": "EmptyFieldDescription",
                "details": {"field": "title"},
            },
            {"variant": "EmptyValueType", "details": {"field": "title"}},
            {"variant": "NoFields", "details": {}},
            {"variant": "DuplicateField", "details": {"field": "title"}},
            {"variant": "LengthOverflow", "details": {}},
        ]
        for payload in payloads:
            with self.subTest(variant=payload["variant"]):
                observed = adapter.dump_python(
                    adapter.validate_python(payload), mode="json", exclude_none=True
                )
                self.assertEqual(observed, payload)

    def test_malformed_direct_schema_error_payloads_are_rejected(self):
        adapter = TypeAdapter(ContractSchemaFailure)
        malformed = [
            {"variant": "ZeroVersion"},
            {"variant": "UnknownVariant", "details": {}},
            {"variant": "UnsupportedVersion", "details": {"observed": True}},
            {
                "variant": "UnsupportedVersion",
                "details": {"observed": 1 << 32},
            },
            {"variant": "EmptyFieldDescription", "details": {}},
            {
                "variant": "EmptyValueType",
                "details": {"field": "title", "unexpected": "value"},
            },
        ]
        for payload in malformed:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                adapter.validate_python(payload)

    def test_malformed_nested_failure_payloads_are_rejected(self):
        extraction = TypeAdapter(RuntimeExtractionFailure)
        validation = TypeAdapter(RuntimeValidationFailure)
        malformed = [
            (
                extraction,
                {
                    "kind": "invalid_contract_schema",
                    "message": "contract schema version must be greater than zero",
                    "schema_error": {"variant": "UnknownVariant", "details": {}},
                },
            ),
            (
                extraction,
                {
                    "kind": "invalid_contract_schema",
                    "message": 9,
                    "schema_error": {"variant": "ZeroVersion", "details": {}},
                },
            ),
            (
                validation,
                {
                    "kind": "invalid_contract_schema",
                    "message": "contract schema version must be greater than zero",
                    "schema_error": {
                        "variant": "EmptyFieldDescription",
                        "details": {"field": "title", "extra": True},
                    },
                },
            ),
            (validation, {"kind": "not_a_validation_failure"}),
        ]
        for adapter, payload in malformed:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                adapter.validate_python(payload)


class SchemaErrorAttributionTests(unittest.TestCase):
    def test_dot_path_argument_mapping_requires_discriminator_and_equal_values(self):
        entry = {
            "decision": "mapped",
            "rustPath": "yosoi::contracts::ContractSchemaError::EmptyFieldDescription",
            "variantBinding": {
                "discriminator": "variant",
                "tag": "EmptyFieldDescription",
            },
            "argumentMappings": [
                {"rustArgument": "field", "pythonArgument": "details.field"}
            ],
        }
        selected = [
            {
                "rustType": "ContractSchemaError",
                "variant": "EmptyFieldDescription",
                "rust": {
                    "variant": "EmptyFieldDescription",
                    "details": {"field": "title"},
                },
                "python": {
                    "variant": "EmptyFieldDescription",
                    "details": {"field": "title"},
                },
                "arguments": {"field": "title"},
            }
        ]
        self.assertTrue(payload_checks(entry, selected)[0]["equal"])

        changed = copy.deepcopy(selected)
        changed[0]["python"]["details"]["field"] = "summary"
        self.assertFalse(payload_checks(entry, changed)[0]["equal"])
        changed = copy.deepcopy(selected)
        changed[0]["python"]["variant"] = "DuplicateField"
        self.assertFalse(payload_checks(entry, changed)[0]["equal"])
        changed = copy.deepcopy(selected)
        changed[0]["python"]["details"] = {}
        self.assertFalse(payload_checks(entry, changed)[0]["equal"])

    def test_nested_source_argument_maps_to_live_schema_error_field(self):
        entry = {
            "decision": "mapped",
            "rustPath": "yosoi::contracts::ExtractionFailure::InvalidContractSchema",
            "variantBinding": {
                "discriminator": "kind",
                "tag": "invalid_contract_schema",
            },
            "argumentMappings": [
                {"rustArgument": "0", "pythonArgument": "schema_error"}
            ],
        }
        schema_error = {"variant": "ZeroVersion", "details": {}}
        value = {
            "kind": "invalid_contract_schema",
            "message": "contract schema version must be greater than zero",
            "schema_error": schema_error,
        }
        selected = [
            {
                "rustType": "ExtractionFailure",
                "variant": "InvalidContractSchema",
                "rust": value,
                "python": value,
                "arguments": {"0": schema_error},
            }
        ]
        self.assertTrue(payload_checks(entry, selected)[0]["equal"])

        selected[0]["python"] = {**value, "schema_error": None}
        self.assertFalse(payload_checks(entry, selected)[0]["equal"])

    def test_selection_requires_mapped_exact_paths(self):
        comparisons = [
            {
                "rustType": "ContractSchemaError",
                "variant": "ZeroVersion",
                "rust": {"variant": "ZeroVersion", "details": {}},
            }
        ]
        entry = {
            "decision": "mapped",
            "rustPath": "yosoi::contracts::ContractSchemaError::ZeroVersion",
        }
        self.assertEqual(select_comparisons(entry, comparisons), comparisons)
        entry["decision"] = "proposed"
        self.assertEqual(select_comparisons(entry, comparisons), [])
        entry.update(
            decision="mapped",
            rustPath="yosoi::contracts::ContractSchemaError::fmt",
            trait="Display",
        )
        self.assertEqual(select_comparisons(entry, comparisons), [])


if __name__ == "__main__":
    unittest.main()
