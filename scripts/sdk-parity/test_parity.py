"""Focused unit coverage for the parity inventory join and evidence gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("parity.py")
SPEC = importlib.util.spec_from_file_location("sdk_parity", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
parity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parity
SPEC.loader.exec_module(parity)


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
            parity._is_public_native_exception(NativeError, "yosoi.errors", "yosoi-engine")
        )
        self.assertFalse(
            parity._is_public_native_exception(NativeError, "yosoi._internal", "yosoi-engine")
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
