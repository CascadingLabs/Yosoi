"""Focused checks for exact Serde wire comparison and result input direction."""

import unittest

from pydantic import BaseModel, Field, TypeAdapter
from run_serde_conformance import (
    operation_mapping_checks,
    python_field_observations,
    python_input_for_fixture,
    shape_observation,
    struct_field_evidence_cases,
)


def mapped_field_fixture(
    *,
    rust_output=None,
    python_present=True,
    python_alias="wire_value",
    python_value="same",
):
    rust_path = "fixture::Record::value"
    field_key = "member:struct_field:fixture::Record::value"
    return (
        {
            "entries": [
                {
                    "rustPath": "fixture::Record",
                    "symbolKey": "page:struct:fixture::Record",
                    "decision": "mapped",
                    "pythonTarget": "fixture.Record",
                },
                {
                    "rustPath": rust_path,
                    "symbolKey": field_key,
                    "decision": "mapped",
                    "pythonTarget": "fixture.Record.value",
                    "units": [],
                    "cardinality": [],
                    "argumentMappings": [],
                    "fixedArguments": [],
                    "defaults": [],
                },
            ]
        },
        [
            {
                "name": "record-fixture",
                "rustType": "fixture::Record",
                "pythonTarget": "fixture.Record",
                "inputSource": "rust",
                "construction": None,
                "rustOutput": {"wire_value": "same"}
                if rust_output is None
                else rust_output,
                "rustFixturePassed": True,
                "pythonError": None,
                "pythonFieldObservations": {
                    "value": {
                        "pythonField": "value",
                        "serializationAlias": python_alias,
                        "pythonAttributePresent": True,
                        "pythonAttributeValue": python_value,
                        "pythonWirePresent": python_present,
                        "pythonWireValue": python_value if python_present else None,
                        "attributeProjectionEqual": python_present,
                    }
                },
            }
        ],
        {
            "items": [
                {
                    "kind": "struct_field",
                    "id": "struct_field:fixture::Record::value",
                    "rustPath": rust_path,
                    "parentRustPath": "fixture::Record",
                    "symbolKey": field_key,
                }
            ]
        },
    )


class SerdeConformanceTests(unittest.TestCase):
    def test_shape_check_distinguishes_explicit_null_from_absent(self):
        expectations = {
            "nullPaths": ["source_bytes"],
            "absentPaths": ["expanded_name_path"],
        }
        matching = {"source_bytes": None}
        mismatched = {"expanded_name_path": None}

        self.assertTrue(shape_observation(matching, expectations)["passed"])
        observation = shape_observation(mismatched, expectations)
        self.assertFalse(observation["passed"])
        self.assertFalse(observation["nullPaths"][0]["present"])
        self.assertFalse(observation["absentPaths"][0]["absent"])

    def test_exact_comparison_data_retains_null_and_object_key_presence(self):
        rust = {"kind": "exhausted"}
        python_with_null = {"kind": "exhausted", "value": None}
        python_missing_null = {"kind": "zero_or_one", "value": None}
        rust_zero_or_one = {"kind": "zero_or_one"}

        self.assertNotEqual(rust, python_with_null)
        self.assertNotEqual(rust_zero_or_one, python_missing_null)

    def test_serialize_only_fixture_decodes_only_the_rust_output_in_python(self):
        fixture = {
            "decoder_supported": False,
            "wire_input_available": False,
            "wire_input": None,
            "rust_output": {"kind": "exhausted"},
        }

        value, source = python_input_for_fixture(fixture)
        self.assertEqual(source, "rust_serialized_output")
        self.assertEqual(value, fixture["rust_output"])

    def test_deserialize_fixture_uses_rust_wire_input(self):
        fixture = {
            "decoder_supported": True,
            "wire_input_available": True,
            "wire_input": {"kind": "json", "value": None},
            "rust_output": {"kind": "json", "value": None},
        }

        value, source = python_input_for_fixture(fixture)
        self.assertEqual(source, "rust_wire_input")
        self.assertEqual(value, fixture["wire_input"])

    def test_query_namespace_arguments_are_mapped_by_name_and_value(self):
        operation = {
            "name": "QuerySpec.with_namespace",
            "rustArguments": {"prefix": "t", "namespace_uri": "urn:test"},
            "pythonArguments": {"prefix": "unused", "uri": "unused"},
        }
        python_operation = {
            "pythonArguments": {"prefix": "t", "uri": "urn:test"},
        }
        checks = operation_mapping_checks(operation, python_operation)
        self.assertTrue(all(item["equal"] for item in checks))
        self.assertTrue(
            all(item["rustSha256"] == item["pythonSha256"] for item in checks)
        )

        python_operation["pythonArguments"]["uri"] = "urn:other"
        self.assertFalse(
            all(
                item["equal"]
                for item in operation_mapping_checks(operation, python_operation)
            )
        )

    def test_field_evidence_uses_compiler_field_and_live_serialization_alias(self):
        ledger, comparisons, inventory = mapped_field_fixture()
        cases = struct_field_evidence_cases(ledger, comparisons, inventory)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["outcome"], "passed")
        check = cases[0]["comparisons"][0]
        self.assertEqual(check["rustField"], "value")
        self.assertEqual(check["rustWireKey"], "wire_value")
        self.assertEqual(check["pythonSerializationAlias"], "wire_value")

    def test_mismatched_field_value_is_not_verified(self):
        ledger, comparisons, inventory = mapped_field_fixture(python_value="different")
        cases = struct_field_evidence_cases(ledger, comparisons, inventory)

        self.assertEqual(cases[0]["outcome"], "failed")
        self.assertFalse(cases[0]["comparisons"][0]["equal"])

    def test_missing_python_alias_is_not_verified(self):
        ledger, comparisons, inventory = mapped_field_fixture(
            python_present=False, python_alias="missing_alias"
        )
        cases = struct_field_evidence_cases(ledger, comparisons, inventory)

        self.assertEqual(cases[0]["outcome"], "failed")
        check = cases[0]["comparisons"][0]
        self.assertFalse(check["pythonPresent"])
        self.assertFalse(check["equal"])

    def test_null_and_absence_remain_distinct_for_field_evidence(self):
        ledger, comparisons, inventory = mapped_field_fixture(
            rust_output={}, python_value=None
        )
        cases = struct_field_evidence_cases(ledger, comparisons, inventory)

        self.assertEqual(cases[0]["outcome"], "failed")
        check = cases[0]["comparisons"][0]
        self.assertFalse(check["rustPresent"])
        self.assertTrue(check["pythonPresent"])
        self.assertFalse(check["equal"])

    def test_omission_on_both_sides_does_not_verify_the_typed_field(self):
        ledger, comparisons, inventory = mapped_field_fixture(
            rust_output={}, python_present=False, python_value=None
        )
        comparisons[0]["equal"] = True
        self.assertEqual(
            struct_field_evidence_cases(ledger, comparisons, inventory), []
        )

    def test_unsupported_field_mappings_cannot_create_passing_evidence(self):
        mapping_names = (
            "units",
            "cardinality",
            "argumentMappings",
            "fixedArguments",
        )
        for mapping_name in mapping_names:
            with self.subTest(mapping=mapping_name):
                ledger, comparisons, inventory = mapped_field_fixture()
                ledger["entries"][1][mapping_name] = [{"id": "unsupported"}]

                cases = struct_field_evidence_cases(ledger, comparisons, inventory)

                self.assertEqual(cases, [])

    def test_default_mapping_requires_independent_default_fixture(self):
        ledger, comparisons, inventory = mapped_field_fixture()
        ledger["entries"][1]["defaults"] = [{"id": "field-default"}]

        self.assertEqual(
            struct_field_evidence_cases(ledger, comparisons, inventory), []
        )

    def test_live_field_observation_keeps_null_and_alias_projection(self):
        class AliasModel(BaseModel):
            value: str | None = Field(alias="wire_value")

        value = AliasModel(wire_value=None)
        output = TypeAdapter(AliasModel).dump_python(
            value, mode="json", by_alias=True, exclude_none=False
        )
        observation = python_field_observations(AliasModel, value, output)["value"]

        self.assertTrue(observation["pythonAttributePresent"])
        self.assertTrue(observation["pythonWirePresent"])
        self.assertIsNone(observation["pythonAttributeValue"])
        self.assertIsNone(observation["pythonWireValue"])
        self.assertTrue(observation["attributeProjectionEqual"])


if __name__ == "__main__":
    unittest.main()
