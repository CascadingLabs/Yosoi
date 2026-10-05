"""Focused unit coverage for the parity inventory join and evidence gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("parity.py")
SPEC = importlib.util.spec_from_file_location("sdk_parity", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
parity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parity
sys.modules["parity"] = parity
SPEC.loader.exec_module(parity)
SEED_SCRIPT = SCRIPT.with_name("seed_ledger.py")
SEED_SPEC = importlib.util.spec_from_file_location("sdk_seed_ledger", SEED_SCRIPT)
assert SEED_SPEC is not None and SEED_SPEC.loader is not None
seed_ledger = importlib.util.module_from_spec(SEED_SPEC)
sys.modules[SEED_SPEC.name] = seed_ledger
SEED_SPEC.loader.exec_module(seed_ledger)


def write_json(path: Path, value: object) -> bytes:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def inventory() -> dict[str, object]:
    return {
        "sourceRevision": "a" * 40,
        "inventorySignature": "b" * 64,
        "featureProfileDigest": "c" * 64,
        "sdk": {"crate": "fixture_sdk", "package": "fixture-sdk", "version": "0.1.0"},
        "reference": {"version": "0.1.0", "generatorDigest": "d" * 64, "locale": "en"},
        "featureProfile": {"requestedFeatures": [], "defaultFeaturesEnabled": True},
        "items": [
            {
                "symbolKey": "page:struct:fixture_sdk::Thing",
                "id": "struct:fixture_sdk::Thing",
                "rustPath": "fixture_sdk::Thing",
                "aliases": ["fixture_sdk::model::Thing"],
                "kind": "struct",
                "signature": "pub struct Thing",
                "rustArguments": [],
                "surface": "item",
                "parentRustPath": None,
                "trait": None,
            },
            {
                "symbolKey": "member:struct_field:fixture_sdk::Thing::value",
                "id": "struct_field:fixture_sdk::Thing::value",
                "rustPath": "fixture_sdk::Thing::value",
                "aliases": [],
                "kind": "struct_field",
                "signature": "pub value: u64",
                "rustArguments": [],
                "surface": "member",
                "parentRustPath": "fixture_sdk::Thing",
                "trait": None,
            },
            {
                "symbolKey": "member:function:fixture_sdk::Thing::check",
                "id": "function:fixture_sdk::Thing::check",
                "rustPath": "fixture_sdk::Thing::check",
                "aliases": [],
                "kind": "function",
                "signature": "fn check(&self)",
                "rustArguments": [{"name": "self", "type": "&self", "receiver": True}],
                "surface": "member",
                "parentRustPath": "fixture_sdk::Thing",
                "trait": None,
            },
        ],
    }


def python_surface() -> dict[str, object]:
    return {
        "package": "fixture",
        "runtime": {
            "implementation": "cpython",
            "version": "3.14.0",
            "abi": "",
            "dependencies": {"pydantic": "2.12.0", "pydantic-core": "2.41.1"},
        },
        "surfaceDigest": "e" * 64,
        "implementationDigest": "d" * 64,
        "objects": [],
        "targets": {
            "fixture.Thing": {
                "kind": "class",
                "signature": {"display": "()", "parameters": []},
                "fields": [],
            }
        },
    }


def ledger() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "python-rust-sdk-parity-ledger",
        "sourcePin": {
            "sourceRevision": None,
            "inventorySignature": None,
            "featureProfileDigest": None,
        },
        "pythonPin": {"surfaceDigest": None, "implementationDigest": None},
        "entries": [
            {
                "rustPath": "fixture_sdk::Thing",
                "decision": "mapped",
                "pythonTarget": "fixture.Thing",
                "argumentMappings": [],
                "defaults": [],
                "units": [],
                "cardinality": [],
                "rationale": "Mapping metadata cannot verify itself.",
            }
        ],
    }


class InventoryTests(unittest.TestCase):
    def test_fixed_dispatch_argument_must_be_in_the_python_signature(self):
        item = {"kind": "function", "rustArguments": []}
        target = {"kind": "callable", "signature": {"parameters": [{"name": "kind"}]}}
        entry = {"argumentMappings": [], "fixedArguments": {"kind": "relationship"}}
        self.assertIsNone(parity._mapping_configuration_problem(item, entry, target))
        entry["fixedArguments"] = {"missing": "relationship"}
        self.assertIn(
            "fixed argument", parity._mapping_configuration_problem(item, entry, target)
        )

    def test_function_receiver_mapping_requires_actual_self_and_python_parameter(self):
        item = {
            "kind": "function",
            "rustArguments": [
                {"name": "self", "receiver": True},
                {"name": "other", "receiver": False},
            ],
        }
        target = {
            "kind": "callable",
            "signature": {"parameters": [{"name": "left"}, {"name": "right"}]},
        }
        entry = {
            "argumentMappings": [{"rustArgument": "other", "pythonArgument": "right"}],
            "receiverMapping": {"rustArgument": "self", "pythonArgument": "left"},
        }
        self.assertIsNone(parity._mapping_configuration_problem(item, entry, target))
        entry["receiverMapping"]["pythonArgument"] = "absent"
        self.assertIn(
            "receiver mapping",
            parity._mapping_configuration_problem(item, entry, target),
        )
        entry["receiverMapping"]["pythonArgument"] = "left"
        item["rustArguments"][0]["receiver"] = False
        self.assertIsNotNone(parity._mapping_configuration_problem(item, entry, target))

    def test_nested_schema_error_payload_requires_the_live_detail_path(self):
        target = {
            "kind": "type-alias",
            "signature": {"parameters": []},
            "alias": {
                "kind": "discriminated-union",
                "discriminator": "variant",
                "unionMembers": [
                    {
                        "discriminatorValues": ["UnsupportedVersion"],
                        "fields": [
                            {"name": "variant"},
                            {"name": "details", "modelFields": [{"name": "observed"}]},
                        ],
                    }
                ],
            },
        }
        item = {
            "kind": "variant",
            "rustPath": "yosoi::contracts::ContractSchemaError::UnsupportedVersion",
            "symbolKey": "unsupported-version",
            "signature": "UnsupportedVersion { observed: u32 }",
            "rustArguments": [{"name": "observed", "type": "u32"}],
        }
        entry = seed_ledger._entry(
            item,
            "yosoi.contracts.ContractSchemaFailure",
            target,
            {},
            "Typed schema error",
        )
        self.assertIsNotNone(entry)
        self.assertEqual(
            entry["argumentMappings"][0]["pythonArgument"], "details.observed"
        )
        self.assertIsNone(parity._mapping_configuration_problem(item, entry, target))
        entry["argumentMappings"][0]["pythonArgument"] = "details.missing"
        self.assertIn(
            "selected Python fields",
            parity._mapping_configuration_problem(item, entry, target),
        )

    def test_public_class_constants_are_preserved_without_instance_attributes(self):
        class Scalar:
            TYPE_ID = "fixture.scalar"
            _PRIVATE = "hidden"
            ordinary = "instance detail"

        descriptions = parity._class_member_descriptions(Scalar, ["fixture.Scalar"])
        constants = {
            item["target"]: item
            for item in descriptions
            if item["kind"] == "class-constant"
        }
        self.assertEqual(set(constants), {"fixture.Scalar.TYPE_ID"})
        self.assertEqual(constants["fixture.Scalar.TYPE_ID"]["value"], "fixture.scalar")

    def test_alias_of_alias_retains_discriminator_and_payload_schema(self):
        from typing import Annotated, Literal, TypeAliasType

        from pydantic import BaseModel, Field

        class Failed(BaseModel):
            kind: Literal["failed"]
            message: str

        class Empty(BaseModel):
            kind: Literal["empty"]

        original = TypeAliasType(
            "Original", Annotated[Failed | Empty, Field(discriminator="kind")]
        )
        alias = TypeAliasType("Alias", original)
        shape = parity._type_alias_shape(alias, "fixture")
        self.assertEqual(shape["kind"], "discriminated-union")
        self.assertEqual(shape["discriminator"], "kind")
        failed = next(
            member
            for member in shape["unionMembers"]
            if member["name"].endswith("Failed")
        )
        self.assertEqual(failed["discriminatorValues"], ["failed"])
        self.assertEqual(
            {field["name"] for field in failed["fields"]}, {"kind", "message"}
        )

    def test_tagged_payload_mapping_is_checked_against_live_member_schema(self):
        item = {"kind": "variant", "rustArguments": [{"name": "0"}]}
        target = {
            "kind": "type-alias",
            "alias": {
                "kind": "discriminated-union",
                "discriminator": "kind",
                "unionMembers": [
                    {
                        "discriminatorValues": ["browser_failure"],
                        "fields": [{"name": "kind"}, {"name": "value"}],
                    }
                ],
            },
        }
        entry = {
            "variantBinding": {
                "discriminator": "kind",
                "tag": "browser_failure",
                "input": "TypeAdapter.validate_python",
            },
            "argumentMappings": [{"rustArgument": "0", "pythonArgument": "value"}],
        }
        self.assertIsNone(parity._mapping_configuration_problem(item, entry, target))
        entry["variantBinding"]["tag"] = "missing_tag"
        self.assertIn(
            "exactly one", parity._mapping_configuration_problem(item, entry, target)
        )
        entry["variantBinding"]["tag"] = "browser_failure"
        entry["argumentMappings"][0]["pythonArgument"] = "missing_field"
        self.assertIn(
            "selected Python fields",
            parity._mapping_configuration_problem(item, entry, target),
        )

    def test_output_error_details_validate_parent_identity_and_public_fields(self):
        item = {
            "kind": "variant",
            "rustPath": "yosoi::PolicyError::DuplicateAcquisition",
            "parentRustPath": "yosoi::PolicyError",
            "rustArguments": [
                {"name": "0", "type": "AcquisitionKind", "receiver": False}
            ],
        }
        target = {"kind": "class", "signature": None, "fields": []}
        python_targets = {
            "yosoi.errors.RustErrorDetails": {"kind": "class", "fields": []},
            **{
                f"yosoi.errors.RustErrorDetails.{name}": {
                    "target": f"yosoi.errors.RustErrorDetails.{name}",
                    "kind": "field",
                    "annotation": annotation,
                    "field": {"name": name, "annotation": annotation},
                }
                for name, annotation in (
                    ("rust_type", "str"),
                    ("variant", "str | None"),
                    ("details", "Mapping[str, Any]"),
                    ("source_chain", "tuple[str, ...]"),
                )
            },
        }
        entry = {
            "pythonTarget": "yosoi.errors.PolicyError",
            "mappingDirection": "output",
            "argumentMappings": [],
            "outputBinding": {
                "kind": "error-details",
                "schemaTarget": "yosoi.errors.RustErrorDetails",
                "discriminator": "variant",
                "tag": "DuplicateAcquisition",
                "rustType": "yosoi_policy::PolicyError",
                "pythonFields": [
                    {
                        "rustArgument": "0",
                        "pythonFieldPath": "details.acquisition",
                        "conversion": "AcquisitionKind tagged JSON value",
                    }
                ],
            },
        }
        self.assertIsNone(
            parity._mapping_configuration_problem(item, entry, target, python_targets)
        )
        entry["outputBinding"]["rustType"] = "yosoi_policy::OtherError"
        self.assertIn(
            "rustType",
            parity._mapping_configuration_problem(item, entry, target, python_targets),
        )
        entry["outputBinding"]["rustType"] = "yosoi_policy::PolicyError"
        entry["outputBinding"]["pythonFields"][0]["pythonFieldPath"] = "source_chain[*]"
        self.assertIsNone(
            parity._mapping_configuration_problem(item, entry, target, python_targets)
        )
        entry["outputBinding"]["pythonFields"][0]["pythonFieldPath"] = "private_handle"
        self.assertIn(
            "output Python field path",
            parity._mapping_configuration_problem(item, entry, target, python_targets),
        )
        entry["outputBinding"]["pythonFields"][0]["pythonFieldPath"] = "$"
        self.assertIsNone(
            parity._mapping_configuration_problem(item, entry, target, python_targets)
        )
        entry["outputBinding"]["kind"] = "outcome-view"
        entry["outputBinding"]["tag"] = "duplicate_acquisition"
        self.assertIn(
            "output Python field path",
            parity._mapping_configuration_problem(item, entry, target, python_targets),
        )
        wrapper = {
            "kind": "variant",
            "rustPath": "yosoi::contracts::ContractLocatorError::Plan",
            "parentRustPath": "yosoi::contracts::ContractLocatorError",
            "rustArguments": [
                {
                    "name": "0",
                    "type": "yosoi_documents::PlanError",
                    "receiver": False,
                }
            ],
        }
        entry["outputBinding"] = {
            "kind": "error-details",
            "schemaTarget": "yosoi.errors.RustErrorDetails",
            "discriminator": "rust_type",
            "tag": "yosoi_documents::PlanError",
            "rustType": "yosoi_documents::PlanError",
            "pythonFields": [
                {
                    "rustArgument": "0",
                    "pythonFieldPath": "$",
                    "conversion": "complete transparent public Plan error metadata",
                }
            ],
        }
        self.assertIsNone(
            parity._mapping_configuration_problem(
                wrapper, entry, target, python_targets
            )
        )
        entry["outputBinding"]["pythonFields"] = [
            {
                "rustArgument": "0",
                "pythonFieldPath": "variant",
                "conversion": "inner PlanError variant metadata",
            },
            {
                "rustArgument": "0",
                "pythonFieldPath": "details",
                "conversion": "inner PlanError structured details mapping",
            },
            {
                "rustArgument": "0",
                "pythonFieldPath": "source_chain",
                "conversion": "public display source chain",
            },
        ]
        self.assertIsNone(
            parity._mapping_configuration_problem(
                wrapper, entry, target, python_targets
            )
        )

    def test_output_outcome_view_checks_readonly_status_slot_and_variant_tag(self):
        item = {
            "kind": "variant",
            "rustPath": "yosoi::contracts::ContractOutcome::NoMatch",
            "parentRustPath": "yosoi::contracts::ContractOutcome",
            "rustArguments": [],
        }
        target = {"kind": "class", "fields": []}
        python_targets = {
            "yosoi.contracts.ContractOutcome": {"kind": "class", "fields": []},
            "yosoi.contracts.ContractOutcome.status": {
                "target": "yosoi.contracts.ContractOutcome.status",
                "kind": "field",
                "annotation": "str",
            },
        }
        entry = {
            "pythonTarget": "yosoi.contracts.ContractOutcome",
            "mappingDirection": "output",
            "argumentMappings": [],
            "outputBinding": {
                "kind": "outcome-view",
                "schemaTarget": "yosoi.contracts.ContractOutcome",
                "discriminator": "status",
                "tag": "no_match",
                "pythonFields": [],
            },
        }
        self.assertIsNone(
            parity._mapping_configuration_problem(item, entry, target, python_targets)
        )
        entry["outputBinding"]["tag"] = "unknown_status"
        self.assertIn(
            "output tag",
            parity._mapping_configuration_problem(item, entry, target, python_targets),
        )
        entry["outputBinding"]["tag"] = "no_match"
        python_targets.pop("yosoi.contracts.ContractOutcome.status")
        self.assertIn(
            "discriminator",
            parity._mapping_configuration_problem(item, entry, target, python_targets),
        )

    def test_output_external_union_validates_literal_unit_and_payload_tags(self):
        alias_target = "yosoi.diagnostics.SearchAttemptDiagnostic"
        target = {
            "kind": "type-alias",
            "alias": {
                "kind": "union",
                "unionMembers": [
                    {
                        "literalValues": [
                            "browser_cancelled",
                            "browser_cleanup_failed",
                        ],
                        "fields": [],
                    },
                    {
                        "literalValues": [],
                        "fields": [
                            {"name": "browser_failure", "literalChoices": ["timeout"]}
                        ],
                    },
                ],
            },
        }
        python_targets = {alias_target: target}
        unit = {
            "kind": "variant",
            "rustPath": "yosoi::search::SearchAttemptDiagnostic::BrowserCancelled",
            "parentRustPath": "yosoi::search::SearchAttemptDiagnostic",
            "rustArguments": [],
        }
        entry = {
            "pythonTarget": alias_target,
            "mappingDirection": "output",
            "argumentMappings": [],
            "outputBinding": {
                "kind": "outcome-view",
                "schemaTarget": alias_target,
                "discriminator": "external",
                "tag": "browser_cancelled",
                "pythonFields": [],
            },
        }
        self.assertIsNone(
            parity._mapping_configuration_problem(unit, entry, target, python_targets)
        )
        entry["outputBinding"]["tag"] = "removed_unit_tag"
        self.assertIn(
            "external output tag",
            parity._mapping_configuration_problem(unit, entry, target, python_targets),
        )
        payload = {
            **unit,
            "rustPath": "yosoi::search::SearchAttemptDiagnostic::BrowserFailure",
            "rustArguments": [
                {"name": "0", "type": "BrowserFailureReason", "receiver": False}
            ],
        }
        entry["outputBinding"]["tag"] = "browser_failure"
        entry["outputBinding"]["pythonFields"] = [
            {
                "rustArgument": "0",
                "pythonFieldPath": "browser_failure",
                "conversion": "BrowserFailureReason literal",
            }
        ]
        self.assertIsNone(
            parity._mapping_configuration_problem(
                payload, entry, target, python_targets
            )
        )
        entry["outputBinding"]["pythonFields"][0]["pythonFieldPath"] = "missing_field"
        self.assertIn(
            "output Python field path",
            parity._mapping_configuration_problem(
                payload, entry, target, python_targets
            ),
        )

    def test_output_discriminated_union_uses_literal_tag_before_payload_fields(self):
        item = {
            "kind": "variant",
            "rustPath": "yosoi::contracts::RuntimeContractOutcome::NoMatch",
            "parentRustPath": "yosoi::contracts::RuntimeContractOutcome",
            "rustArguments": [{"name": "document_id", "receiver": False}],
        }
        target = {
            "kind": "type-alias",
            "fields": [],
            "alias": {
                "kind": "discriminated-union",
                "discriminator": "status",
                "unionMembers": [
                    {
                        "discriminatorValues": ["no_match"],
                        "fields": [{"name": "status"}, {"name": "document_id"}],
                    }
                ],
            },
        }
        entry = {
            "pythonTarget": "yosoi.runtime_contracts.RuntimeContractOutcomeData",
            "mappingDirection": "output",
            "argumentMappings": [],
            "outputBinding": {
                "kind": "outcome-view",
                "schemaTarget": "yosoi.runtime_contracts.RuntimeContractOutcomeData",
                "discriminator": "status",
                "tag": "no_match",
                "pythonFields": [
                    {
                        "rustArgument": "document_id",
                        "pythonFieldPath": "document_id",
                        "conversion": "DocumentId string",
                    }
                ],
            },
        }
        targets = {entry["pythonTarget"]: target}
        self.assertIsNone(
            parity._mapping_configuration_problem(item, entry, target, targets)
        )
        entry["outputBinding"]["tag"] = "removed_status"
        self.assertIn(
            "output tag",
            parity._mapping_configuration_problem(item, entry, target, targets),
        )

    def test_output_binding_is_not_an_input_constructor_mapping(self):
        item = {
            "kind": "variant",
            "rustPath": "yosoi::map::LimitReached::Hosts",
            "parentRustPath": "yosoi::map::LimitReached",
            "rustArguments": [],
        }
        target = {
            "kind": "class",
            "fields": [
                {"name": "kind", "literalChoices": ["limit"]},
                {"name": "value", "literalChoices": ["hosts", "urls"]},
            ],
        }
        python_targets = {
            "yosoi.map.MapTermination": target,
            "yosoi.map.MapTermination.kind": {
                "kind": "field",
                "field": target["fields"][0],
            },
            "yosoi.map.MapTermination.value": {
                "kind": "field",
                "field": target["fields"][1],
            },
        }
        entry = {
            "pythonTarget": "yosoi.map.MapTermination",
            "mappingDirection": "output",
            "argumentMappings": [],
            "outputBinding": {
                "kind": "outcome-view",
                "schemaTarget": "yosoi.map.MapTermination",
                "discriminator": "value",
                "tag": "hosts",
                "pythonFields": [],
            },
        }
        self.assertIsNone(
            parity._mapping_configuration_problem(item, entry, target, python_targets)
        )
        entry["argumentMappings"] = [
            {"rustArgument": "0", "pythonArgument": "value", "conversion": "str"}
        ]
        self.assertIn(
            "constructor argument",
            parity._mapping_configuration_problem(item, entry, target, python_targets),
        )

    def test_plain_tagged_model_variant_uses_nested_public_literal_discriminator(self):
        item = {
            "kind": "variant",
            "rustPath": "yosoi::policy::Acquisition::Exact",
            "rustArguments": [
                {"name": "acquisition", "type": "AcquisitionKind", "receiver": False},
                {
                    "name": "documents",
                    "type": "Vec<DocumentRequest>",
                    "receiver": False,
                },
            ],
        }
        document_selection = [
            {"name": "kind", "literalChoices": ["current", "exact"]},
            {"name": "documents", "literalChoices": []},
        ]
        target = {
            "kind": "class",
            "signature": {"parameters": [{"name": "kind"}, {"name": "documents"}]},
            "fields": [
                {"name": "kind", "literalChoices": ["direct_http", "browser"]},
                {"name": "documents", "modelFields": document_selection},
            ],
        }
        entry = {
            "argumentMappings": [
                {
                    "rustArgument": "acquisition",
                    "pythonArgument": "kind",
                    "conversion": "AcquisitionKind tag",
                },
                {
                    "rustArgument": "documents",
                    "pythonArgument": "documents.documents",
                    "conversion": "ordered document selection",
                },
            ],
            "variantBinding": {
                "discriminator": "documents.kind",
                "tag": "exact",
                "input": "TypeAdapter.validate_python",
            },
        }
        self.assertIsNone(parity._mapping_configuration_problem(item, entry, target))
        entry["variantBinding"]["tag"] = "removed"
        self.assertIn(
            "literal choices",
            parity._mapping_configuration_problem(item, entry, target),
        )

    def test_python_model_introspection_keeps_dataclass_fields_and_public_slots(self):
        from dataclasses import dataclass

        @dataclass(frozen=True, slots=True)
        class RustErrorDetails:
            rust_type: str
            variant: str | None
            details: dict[str, object]
            source_chain: tuple[str, ...] = ()

        class Outcome:
            __slots__ = ("status", "_handle")
            __annotations__ = {"status": str, "_handle": object}

        rust_members = parity._class_member_descriptions(
            RustErrorDetails, ["yosoi.errors.RustErrorDetails"]
        )
        rust_targets = {item["target"] for item in rust_members}
        self.assertTrue(
            {
                "yosoi.errors.RustErrorDetails.rust_type",
                "yosoi.errors.RustErrorDetails.variant",
                "yosoi.errors.RustErrorDetails.details",
                "yosoi.errors.RustErrorDetails.source_chain",
            }.issubset(rust_targets)
        )
        self.assertFalse(any(target.endswith("._handle") for target in rust_targets))
        outcome_members = parity._class_member_descriptions(
            Outcome, ["yosoi.contracts.Outcome"]
        )
        self.assertEqual(
            [item["target"] for item in outcome_members],
            ["yosoi.contracts.Outcome.status"],
        )

    def test_union_alias_tags_preserve_multiple_literals_without_payload_constructor(
        self,
    ):
        target = "yosoi.diagnostics.PartialReason"
        description = {
            "kind": "type-alias",
            "signature": {"parameters": []},
            "alias": {
                "unionMembers": [
                    {
                        "discriminatorValues": [
                            "source_family_partial",
                            "browser_artifact_truncated",
                        ]
                    }
                ]
            },
        }
        parent = {"rustPath": "yosoi::request::PartialReason"}
        python = {"targets": {target: description}}
        self.assertEqual(
            seed_ledger._variant_literal_target(
                parent, "SourceFamilyPartial", target, python
            ),
            (target, "source_family_partial"),
        )
        self.assertEqual(
            seed_ledger._variant_literal_target(
                parent, "UnknownVariant", target, python
            ),
            (None, None),
        )
        # The alias describes tagged values; it exposes no payload constructor.
        self.assertIsNone(
            seed_ledger._argument_mappings(
                {
                    "kind": "variant",
                    "rustPath": parent["rustPath"] + "::BrowserArtifactTruncated",
                    "rustArguments": [{"name": "family", "type": "WebArtifactFamily"}],
                },
                description,
            )
        )

    def test_seed_migration_preserves_overload_identity_when_source_changes(
        self,
    ) -> None:
        path = "yosoi::contracts::Error::from"
        entry = {
            "rustPath": path,
            "trait": "From",
            "symbolKey": "member:@signature:first@source:old",
        }
        same = {
            "rustPath": path,
            "trait": "From",
            "symbolKey": "member:@signature:first@source:new",
            "aliases": [],
        }
        other = {**same, "symbolKey": "member:@signature:second@source:new"}
        self.assertTrue(seed_ledger._matches_prior_mapping(entry, same))
        self.assertFalse(seed_ledger._matches_prior_mapping(entry, other))
        self.assertFalse(
            seed_ledger._matches_prior_mapping(entry, {**same, "trait": "TryFrom"})
        )

    def test_union_properties_require_every_concrete_member(self) -> None:
        targets = {
            "sdk.Result": {
                "alias": {
                    "unionMembers": [
                        {"target": "sdk.Produced"},
                        {"target": "sdk.Unavailable"},
                    ]
                }
            },
            "sdk.Produced.document": {"kind": "field"},
            "sdk.Produced.only_here": {"kind": "field"},
            "sdk.Unavailable.document": {"kind": "property"},
        }
        parity._add_union_properties(targets)
        self.assertEqual(targets["sdk.Result.document"]["kind"], "union-property")
        self.assertEqual(
            targets["sdk.Result.document"]["members"],
            ["sdk.Produced.document", "sdk.Unavailable.document"],
        )
        self.assertNotIn("sdk.Result.only_here", targets)

    def test_frontend_summary_preserves_incomplete_status_and_counts(self) -> None:
        report = parity.build_report(inventory(), python_surface(), ledger())
        summary = parity.summary_from_report(report, "f" * 64)
        self.assertEqual(summary["parityStatus"], report["parityStatus"])
        self.assertEqual(summary["coverage"]["counts"], report["coverage"]["counts"])
        self.assertEqual(summary["reportSha256"], "f" * 64)
        self.assertNotIn("objects", summary["python"])
        self.assertNotIn("items", summary["coverage"])

    def test_fixed_variant_tag_must_exist_in_live_model_choices(self) -> None:
        item = {
            "kind": "variant",
            "rustArguments": [{"name": "0", "type": "String", "receiver": False}],
        }
        entry = {
            "argumentMappings": [{"rustArgument": "0", "pythonArgument": "value"}],
            "fixedArguments": {"kind": "removed_tag"},
        }
        target = {
            "kind": "class",
            "signature": {"parameters": [{"name": "kind"}, {"name": "value"}]},
            "fields": [{"name": "kind", "literalChoices": ["css"]}],
        }
        self.assertIn(
            "literal choices",
            parity._mapping_configuration_problem(item, entry, target),
        )
        entry["fixedArguments"]["kind"] = "css"
        self.assertIsNone(parity._mapping_configuration_problem(item, entry, target))

    def test_members_in_sdk_base_modules_are_available_without_framework_members(
        self,
    ) -> None:
        class Framework:
            def framework_method(self):
                pass

        class Base(Framework):
            def as_str(self) -> str:
                return "value"

        class Child(Base):
            pass

        Framework.__module__ = "framework.models"
        Base.__module__ = "yosoi.scalars"
        Child.__module__ = "yosoi.request"
        members = parity._class_member_descriptions(Child, ["yosoi.request.Child"])
        targets = {member["target"] for member in members}
        self.assertIn("yosoi.request.Child.as_str", targets)
        self.assertNotIn("yosoi.request.Child.framework_method", targets)

    def test_validator_signatures_are_stable_across_processes(self) -> None:
        code = """
import sys
from typing import Annotated
from pydantic import BaseModel, AfterValidator
sys.path.insert(0, sys.argv[1])
import parity
def factory(bound):
    def validate(value):
        return bound(value)
    return validate
class Record(BaseModel):
    value: Annotated[int, AfterValidator(factory(int))]
class Different(BaseModel):
    value: Annotated[int, AfterValidator(factory(str))]
first = parity._describe_signature(Record)
second = parity._describe_signature(Different)
assert first != second, "captured scalar types must remain distinguishable"
print(parity.digest_json(first))
"""
        command = [sys.executable, "-c", code, str(SCRIPT.parent)]
        first = subprocess.check_output(command, text=True, timeout=15)
        second = subprocess.check_output(command, text=True, timeout=15)
        self.assertEqual(first, second)

    def test_seed_ledger_rebases_legacy_crate_root_from_inventory(self) -> None:
        rust = {
            "sdk": {"crate": "yosoi_sdk"},
            "items": [
                {
                    "rustPath": "yosoi_sdk::Thing",
                    "aliases": ["yosoi_sdk::model::Thing"],
                    "parentRustPath": "yosoi_sdk::module",
                }
            ],
        }
        canonical = seed_ledger._inventory_with_mapping_root(rust)
        self.assertEqual(canonical["items"][0]["rustPath"], "yosoi::Thing")
        self.assertEqual(canonical["items"][0]["aliases"], ["yosoi::model::Thing"])
        self.assertEqual(canonical["items"][0]["parentRustPath"], "yosoi::module")

        old_ledger = {
            "entries": [{"rustPath": "yosoi_sdk::Thing", "decision": "mapped"}]
        }
        canonical_ledger = seed_ledger._ledger_with_mapping_root(old_ledger)
        self.assertEqual(canonical_ledger["entries"][0]["rustPath"], "yosoi::Thing")
        restored = seed_ledger._ledger_with_source_root(canonical_ledger, "yosoi_sdk")
        self.assertEqual(restored["entries"][0]["rustPath"], "yosoi_sdk::Thing")

    def test_seed_ledger_keeps_current_crate_root_and_fails_unknown_root_closed(
        self,
    ) -> None:
        rust = {"sdk": {"crate": "yosoi"}, "items": []}
        self.assertIs(seed_ledger._inventory_with_mapping_root(rust), rust)
        with self.assertRaises(parity.ParityError):
            seed_ledger._inventory_with_mapping_root(
                {"sdk": {"crate": "future_sdk"}, "items": []}
            )

    def test_seed_ledger_has_stable_mapping_metadata(self) -> None:
        root = Path(__file__).resolve().parents[2]
        loaded = parity.load_ledger(root / "python/parity/ledger.json")
        self.assertTrue(loaded["entries"])

    def test_member_signatures_describe_the_bound_python_call(self) -> None:
        class Fixture:
            def method(self, value: str) -> str:
                return value

            @property
            def field(self) -> str:
                return "value"

        method = parity._describe_signature(Fixture.method, bound_member=True)
        field = parity._describe_signature(Fixture.field.fget, bound_member=True)
        self.assertEqual([item["name"] for item in method["parameters"]], ["value"])
        self.assertEqual(method["display"], "(value: 'str') -> 'str'")
        self.assertEqual(field["parameters"], [])

    def test_public_extension_exceptions_are_introspected_at_reexport_target(
        self,
    ) -> None:
        class NativeError(Exception):
            pass

        NativeError.__module__ = "_native"
        self.assertTrue(
            parity._is_public_native_exception(NativeError, "yosoi.errors", "yosoi")
        )
        self.assertFalse(
            parity._is_public_native_exception(NativeError, "yosoi._internal", "yosoi")
        )

    def test_public_members_in_same_module_base_are_introspected(self) -> None:
        class ScalarBase:
            @classmethod
            def try_new(cls, value: int) -> int:
                return value

            def get(self) -> int:
                return 1

        class Scalar(ScalarBase):
            def __len__(self) -> int:
                return 1

            pass

        targets = {
            item["target"]: item
            for item in parity._class_member_descriptions(Scalar, ["fixture.Scalar"])
        }
        self.assertIn("fixture.Scalar.try_new", targets)
        self.assertIn("fixture.Scalar.get", targets)
        self.assertIn("fixture.Scalar.__len__", targets)
        self.assertEqual(targets["fixture.Scalar.get"]["signature"]["parameters"], [])

    def test_loads_complete_pages_and_deduplicates_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pages = {
                "index": {
                    "schemaVersion": 1,
                    "id": "module:fixture_sdk",
                    "publicPath": "fixture_sdk",
                    "kind": "module",
                    "signature": "pub crate fixture_sdk",
                    "aliases": [],
                    "members": [],
                },
                "struct/thing": {
                    "schemaVersion": 1,
                    "id": "struct:fixture_sdk::Thing",
                    "publicPath": "fixture_sdk::Thing",
                    "kind": "struct",
                    "signature": "pub struct Thing",
                    "aliases": ["fixture_sdk::model::Thing"],
                    "members": [
                        {
                            "id": "struct_field:fixture_sdk::Thing::value",
                            "publicPath": "fixture_sdk::Thing::value",
                            "kind": "struct_field",
                            "signature": "pub value: u64",
                        },
                        {
                            "id": "function:fixture_sdk::Thing::check",
                            "publicPath": "fixture_sdk::Thing::check",
                            "kind": "function",
                            "signature": "fn check(&self)",
                        },
                    ],
                },
            }
            descriptors = {}
            for slug, page in pages.items():
                raw = write_json(root / "en" / "pages" / f"{slug}.json", page)
                descriptors[slug] = {
                    "file": f"pages/{slug}.json",
                    "localeHashes": {"en": hashlib.sha256(raw).hexdigest()},
                    "aliases": page["aliases"],
                }
            write_json(
                root / "manifest.json",
                {
                    "schemaVersion": 1,
                    "kind": "rust-api-reference",
                    "source": {"commit": "a" * 40},
                    "sdk": {
                        "crate": "fixture_sdk",
                        "package": "fixture-sdk",
                        "version": "0.1.0",
                    },
                    "build": {
                        "features": [],
                        "target": "x86_64-unknown-linux-gnu",
                        "generatorDigest": "d" * 64,
                    },
                    "locales": ["en"],
                    "pages": descriptors,
                },
            )
            result = parity.load_rust_inventory(root)
            self.assertEqual(len(result["items"]), 3)
            thing = result["items"][2]
            self.assertEqual(thing["aliases"], ["fixture_sdk::model::Thing"])
            self.assertEqual(result["sourceRevision"], "a" * 40)
            check = next(item for item in result["items"] if item["kind"] == "function")
            self.assertEqual(
                check["rustArguments"],
                [{"name": "self", "type": "&self", "receiver": True}],
            )

    def test_keeps_overloaded_from_trait_methods_as_distinct_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            page = {
                "schemaVersion": 1,
                "id": "struct:fixture_sdk::ContractLocatorError",
                "publicPath": "fixture_sdk::ContractLocatorError",
                "kind": "struct",
                "signature": "pub struct ContractLocatorError",
                "aliases": [],
                "members": [
                    {
                        "id": "function:fixture_sdk::ContractLocatorError::from",
                        "publicPath": "fixture_sdk::ContractLocatorError::from",
                        "kind": "function",
                        "signature": "fn from(source: QueryError) -> Self",
                        "trait": "From",
                        "source": {
                            "file": "crates/yosoi/src/contracts.rs",
                            "lineStart": 20,
                            "lineEnd": 22,
                        },
                    },
                    {
                        "id": "function:fixture_sdk::ContractLocatorError::from",
                        "publicPath": "fixture_sdk::ContractLocatorError::from",
                        "kind": "function",
                        "signature": "fn from(source: PlanError) -> Self",
                        "trait": "From",
                        "source": {
                            "file": "crates/yosoi/src/contracts.rs",
                            "lineStart": 24,
                            "lineEnd": 26,
                        },
                    },
                    {
                        "id": "function:fixture_sdk::ContractLocatorError::from",
                        "publicPath": "fixture_sdk::ContractLocatorError::from",
                        "kind": "function",
                        "signature": "fn from(source: QueryError) -> Self",
                        "trait": "From",
                        "source": {
                            "file": "crates/yosoi/src/contracts.rs",
                            "lineStart": 20,
                            "lineEnd": 22,
                        },
                    },
                ],
            }
            index = {
                "schemaVersion": 1,
                "id": "module:fixture_sdk",
                "publicPath": "fixture_sdk",
                "kind": "module",
                "signature": "pub crate fixture_sdk",
                "aliases": [],
                "members": [],
            }
            descriptors = {}
            for slug, value in (
                ("index", index),
                ("struct/contract-locator-error", page),
            ):
                raw = write_json(root / "en" / "pages" / f"{slug}.json", value)
                descriptors[slug] = {
                    "file": f"pages/{slug}.json",
                    "localeHashes": {"en": hashlib.sha256(raw).hexdigest()},
                    "aliases": value["aliases"],
                }
            write_json(
                root / "manifest.json",
                {
                    "schemaVersion": 1,
                    "kind": "rust-api-reference",
                    "source": {"commit": "a" * 40},
                    "sdk": {
                        "crate": "fixture_sdk",
                        "package": "fixture-sdk",
                        "version": "0.1.0",
                    },
                    "build": {
                        "features": [],
                        "target": "x86_64-unknown-linux-gnu",
                        "generatorDigest": "d" * 64,
                    },
                    "locales": ["en"],
                    "pages": descriptors,
                },
            )
            result = parity.load_rust_inventory(root)
            from_items = [
                item
                for item in result["items"]
                if item["rustPath"] == "fixture_sdk::ContractLocatorError::from"
            ]
            self.assertEqual(len(from_items), 2)
            self.assertEqual(
                {item["signature"] for item in from_items},
                {
                    "fn from(source: QueryError) -> Self",
                    "fn from(source: PlanError) -> Self",
                },
            )
            self.assertEqual(len({item["symbolKey"] for item in from_items}), 2)

    def test_mapping_and_test_name_do_not_make_item_verified(self) -> None:
        report = parity.build_report(inventory(), python_surface(), ledger())
        statuses = {
            item["rustPath"]: item["status"] for item in report["coverage"]["items"]
        }
        self.assertEqual(statuses["fixture_sdk::Thing"], "mapped")
        self.assertEqual(statuses["fixture_sdk::Thing::value"], "missing")
        self.assertEqual(report["coverage"]["denominator"], 3)
        self.assertEqual(report["coverage"]["counts"]["verified"], 0)
        self.assertTrue(parity.strict_failures(report))

    def test_report_exposes_target_and_semantic_candidate_for_review(self) -> None:
        candidate = {
            "rustPath": "fixture_sdk::Thing::check",
            "symbolKey": "member:function:fixture_sdk::Thing::check",
            "decision": "language-specific",
            "pythonTarget": "fixture.Thing.check",
            "argumentMappings": [],
            "defaults": [],
            "units": [],
            "cardinality": [],
            "rationale": "An owner must review the semantic mapping.",
            "semanticEquivalent": "Python method with the same value-level behavior.",
            "review": {
                "status": "proposed",
                "rationale": "An owner must review the semantic mapping.",
                "pythonEquivalent": "Python method with the same value-level behavior.",
            },
        }
        source = ledger()
        source["entries"].append(candidate)
        report = parity.build_report(inventory(), python_surface(), source)
        check = next(
            item
            for item in report["coverage"]["items"]
            if item["rustPath"] == "fixture_sdk::Thing::check"
        )
        self.assertEqual(check["status"], "missing")
        self.assertEqual(check["mapping"]["pythonTarget"], "fixture.Thing.check")
        self.assertEqual(
            check["mapping"]["semanticEquivalent"],
            "Python method with the same value-level behavior.",
        )

    def test_callable_arguments_need_introspected_mapping_and_evidence(self) -> None:
        parsed = parity._rust_function_arguments(
            "pub async fn send<'a>(&'a self, seed: impl Into<String>, "
            "routes: Vec<(String, usize)>) -> Result<(), Error>"
        )
        self.assertEqual(
            [argument["name"] for argument in parsed],
            ["self", "seed", "routes"],
        )
        self.assertEqual(parsed[-1]["type"], "Vec<(String, usize)>")
        rust_item = {
            "symbolKey": "member:function:fixture_sdk::make",
            "rustPath": "fixture_sdk::make",
            "aliases": [],
            "kind": "function",
            "rustArguments": [{"name": "seed", "type": "String", "receiver": False}],
            "trait": None,
        }
        entry = {
            "pythonTarget": "fixture.make",
            "argumentMappings": [
                {
                    "rustArgument": "seed",
                    "pythonArgument": "seed",
                    "conversion": "str",
                }
            ],
            "defaults": [],
            "units": [],
            "cardinality": [],
        }
        target = {
            "signature": {
                "parameters": [{"name": "seed"}],
            }
        }
        self.assertIsNone(
            parity._mapping_configuration_problem(rust_item, entry, target)
        )
        self.assertIn(
            "unmapped Rust arguments",
            parity._mapping_configuration_problem(
                rust_item, {**entry, "argumentMappings": []}, target
            ),
        )
        self.assertIn(
            "unmapped required Python arguments: context",
            parity._mapping_configuration_problem(
                rust_item,
                entry,
                {
                    "kind": "class",
                    "signature": {
                        "parameters": [
                            {"name": "seed", "hasDefault": False},
                            {"name": "context", "hasDefault": False},
                        ]
                    },
                },
            ),
        )
        case = {
            "testId": "test_parity.py::mapped_callable",
            "rustPath": rust_item["rustPath"],
            "pythonTarget": entry["pythonTarget"],
            "outcome": "passed",
            "comparisons": [
                {
                    "name": "result",
                    "rustSha256": "f" * 64,
                    "pythonSha256": "f" * 64,
                    "equal": True,
                }
            ],
            "mappingChecks": [],
        }
        self.assertFalse(parity._case_passes(case, rust_item, entry))
        case["mappingChecks"] = [
            {
                "kind": "argument",
                "key": "seed",
                "rustSha256": "a" * 64,
                "pythonSha256": "a" * 64,
                "equal": True,
            }
        ]
        self.assertTrue(parity._case_passes(case, rust_item, entry))

    def test_variant_payloads_and_variadics_are_mapping_inputs(self) -> None:
        tuple_arguments = parity._rust_variant_arguments("Tuple(u64, Vec<(u8, u16)>)")
        self.assertEqual([item["name"] for item in tuple_arguments], ["0", "1"])
        self.assertEqual(tuple_arguments[1]["type"], "Vec<(u8, u16)>")
        record_arguments = parity._rust_variant_arguments(
            "Record { value: bool, label: String }"
        )
        self.assertEqual(
            [item["name"] for item in record_arguments], ["value", "label"]
        )

        variadic = parity._rust_function_arguments(
            "pub unsafe fn write(target: u32, ...) -> usize"
        )
        self.assertEqual([item["name"] for item in variadic], ["target", "..."])
        item = {
            "kind": "function",
            "rustArguments": variadic,
        }
        entry = {
            "argumentMappings": [
                {
                    "rustArgument": "target",
                    "pythonArgument": "target",
                    "conversion": "int",
                }
            ]
        }
        target = {"signature": {"parameters": [{"name": "target"}, {"name": "args"}]}}
        self.assertIn(
            "unmapped Rust arguments: ...",
            parity._mapping_configuration_problem(item, entry, target),
        )

    def test_mapped_rust_trait_requires_explicit_semantic_equivalent(self) -> None:
        problem = parity._mapping_configuration_problem(
            {"kind": "trait"}, {}, {"signature": None}
        )
        self.assertIn("semantic equivalent", problem)
        self.assertIsNone(
            parity._mapping_configuration_problem(
                {"kind": "trait"},
                {"semanticEquivalent": "Python runtime-checkable Protocol"},
                {"signature": None},
            )
        )

    def test_identity_view_method_can_map_to_owning_python_type(self) -> None:
        problem = parity._mapping_configuration_problem(
            {
                "kind": "function",
                "rustArguments": [{"name": "self", "receiver": True}],
            },
            {
                "semanticEquivalent": "The Python owner is the Rust borrowed view.",
                "argumentMappings": [],
            },
            {
                "kind": "class",
                "signature": {"parameters": [{"name": "id", "hasDefault": False}]},
            },
        )
        self.assertIsNone(problem)

    def test_only_snapshot_bound_comparison_evidence_verifies_mapping(self) -> None:
        rust = inventory()
        python = python_surface()
        with tempfile.TemporaryDirectory() as temporary:
            evidence_path = Path(temporary) / "evidence.json"
            results_path = Path(temporary) / "results.json"
            comparison = "f" * 64
            raw = {
                "schemaVersion": 1,
                "kind": "yosoi-python-rust-conformance",
                "runId": "run-1",
                "executedAt": "2026-10-04T12:00:00Z",
                "outcome": "passed",
                "runner": {"command": ["pytest", "-q", "test_parity.py::case"]},
                "source": {
                    "sourceRevision": rust["sourceRevision"],
                    "inventorySignature": rust["inventorySignature"],
                    "featureProfileDigest": rust["featureProfileDigest"],
                },
                "python": {
                    "surfaceDigest": python["surfaceDigest"],
                    "implementationDigest": python["implementationDigest"],
                    "runtime": python["runtime"],
                },
                "cases": [
                    {
                        "testId": "test_parity.py::case",
                        "rustPath": "fixture_sdk::Thing",
                        "pythonTarget": "fixture.Thing",
                        "outcome": "passed",
                        "mappingChecks": [],
                        "comparisons": [
                            {
                                "name": "normalized result",
                                "rustSha256": comparison,
                                "pythonSha256": comparison,
                                "equal": True,
                            }
                        ],
                    }
                ],
            }
            result_artifact = {
                "schemaVersion": 1,
                "kind": "yosoi-python-rust-conformance-results",
                **{
                    name: raw[name]
                    for name in ("runId", "outcome", "source", "python", "cases")
                },
            }
            result_bytes = write_json(results_path, result_artifact)
            raw["resultArtifact"] = {
                "path": "results.json",
                "sha256": hashlib.sha256(result_bytes).hexdigest(),
            }
            write_json(evidence_path, raw)
            evidence = parity._load_evidence(evidence_path, rust, python)
            report = parity.build_report(rust, python, ledger(), [evidence])
            thing = next(
                item
                for item in report["coverage"]["items"]
                if item["rustPath"] == "fixture_sdk::Thing"
            )
            self.assertEqual(thing["status"], "verified")

            raw["source"]["sourceRevision"] = "9" * 40
            result_artifact["source"] = raw["source"]
            result_bytes = write_json(results_path, result_artifact)
            raw["resultArtifact"]["sha256"] = hashlib.sha256(result_bytes).hexdigest()
            write_json(evidence_path, raw)
            stale = parity._load_evidence(evidence_path, rust, python)
            report = parity.build_report(rust, python, ledger(), [stale])
            thing = next(
                item
                for item in report["coverage"]["items"]
                if item["rustPath"] == "fixture_sdk::Thing"
            )
            self.assertEqual(thing["status"], "stale")

    def test_live_introspection_records_python_aliases_and_type_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "surface_fixture"
            package.mkdir()
            (package / "__init__.py").write_text(
                "from .module import Choice, Model as Model, Outcome, Provider\n"
                "from . import module as module\n"
                "__all__ = ['Choice', 'Model', 'Outcome', 'Provider', 'module']\n",
                encoding="utf-8",
            )
            (package / "module.py").write_text(
                "from typing import Annotated, Literal, TypeAliasType\n"
                "from enum import StrEnum\n"
                "class Provider(StrEnum):\n"
                "    first = 'first'\n"
                "    second = 'second'\n"
                "class Discriminator:\n"
                "    def __init__(self, value): self.discriminator = value\n"
                "class Answer:\n"
                "    status: Literal['answer']\n"
                "class Empty:\n"
                "    status: Literal['empty']\n"
                "Choice = TypeAliasType('Choice', Literal['a', 'b'])\n"
                "Outcome = TypeAliasType('Outcome', "
                "Annotated[Answer | Empty, Discriminator('status')])\n"
                "class Model:\n"
                "    def select(self, name: str = 'x') -> str:\n"
                "        return name\n",
                encoding="utf-8",
            )
            result = parity.introspect_python_package("surface_fixture", root)
            self.assertIn("surface_fixture.Choice", result["targets"])
            self.assertIn("surface_fixture.Model.select", result["targets"])
            self.assertIn("surface_fixture.module.Model", result["targets"])
            self.assertEqual(
                result["targets"]["surface_fixture.Model"]["kind"], "class"
            )
            choices = result["targets"]["surface_fixture.Choice"]["alias"]
            self.assertEqual(choices["kind"], "literal")
            self.assertEqual(choices["choices"], ["a", "b"])
            outcome = result["targets"]["surface_fixture.Outcome"]["alias"]
            self.assertEqual(outcome["kind"], "discriminated-union")
            self.assertEqual(outcome["discriminator"], "status")
            self.assertEqual(
                {
                    (item["name"], item["discriminatorValue"])
                    for item in outcome["unionMembers"]
                },
                {("Answer", "answer"), ("Empty", "empty")},
            )
            self.assertEqual(
                result["targets"]["surface_fixture.Provider.first"]["value"],
                "first",
            )


if __name__ == "__main__":
    unittest.main()
