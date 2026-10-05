from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).with_name("sdk_contract.py")
SPEC = importlib.util.spec_from_file_location("sdk_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sdk_contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sdk_contract)


def rust_item(
    path: str,
    kind: str,
    signature: str,
    *,
    trait: str | None = None,
    surface: str = "item",
    parent: str | None = None,
    key: str | None = None,
) -> dict[str, Any]:
    return {
        "symbolKey": key or f"symbol:{path}:{kind}:{trait or ''}",
        "id": f"{kind}:{path}",
        "rustPath": path,
        "kind": kind,
        "trait": trait,
        "surface": surface,
        "parentRustPath": parent,
        "signature": signature,
        "aliases": [],
    }


def make_inputs() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    declarations = [
        rust_item("yosoi::map::MapRequest", "struct", "pub struct MapRequest"),
        rust_item(
            "yosoi::map::MapRequest::depth",
            "struct_field",
            "pub depth: u8",
            surface="member",
            parent="yosoi::map::MapRequest",
        ),
        rust_item(
            "yosoi::map::MapRequest::with_depth",
            "function",
            "pub fn with_depth(self, depth: u8) -> Self",
            surface="member",
            parent="yosoi::map::MapRequest",
        ),
    ]
    python_target = {
        "kind": "class",
        "canonicalTarget": "yosoi.map.MapRequest",
        "signature": {"display": "() -> MapRequest", "parameters": []},
        "fields": [{"name": "depth", "annotation": "int", "required": False}],
        "alias": None,
    }
    python = {
        "package": "yosoi",
        "runtime": {"version": "3.14"},
        "surfaceDigest": "a" * 64,
        "implementationDigest": "b" * 64,
        "targets": {"yosoi.map.MapRequest": python_target},
    }
    report_items = []
    for item in declarations:
        mapped = item["kind"] in {"struct", "struct_field", "function"}
        report_items.append(
            {
                **item,
                "status": "mapped",
                "evidence": [],
                "python": {"target": "yosoi.map.MapRequest"},
                "mapping": {
                    "decision": "mapped" if mapped else "missing",
                    "pythonTarget": "yosoi.map.MapRequest" if mapped else None,
                    "semanticEquivalent": "Same public capability" if mapped else None,
                    "rationale": "Reviewed mapping" if mapped else None,
                    "review": None,
                },
            }
        )
    inventory_report = {
        "source": {"revision": "1" * 40, "inventorySignature": "c" * 64},
        "python": python,
        "coverage": {"items": report_items},
    }
    rust = {
        "sourceRevision": "1" * 40,
        "inventorySignature": "c" * 64,
        "featureProfileDigest": "d" * 64,
        "fixtureExecutables": {"diagnostics": "e" * 64},
        "items": declarations,
    }
    ledger = {
        "schemaVersion": 1,
        "kind": "python-rust-sdk-parity-ledger",
        "sourcePin": {"sourceRevision": "old"},
        "pythonPin": {"surfaceDigest": "old"},
        "entries": [],
    }
    for item in report_items:
        mapping = item.get("mapping")
        if mapping is not None:
            ledger["entries"].append(
                {
                    "rustPath": item["rustPath"],
                    "trait": item.get("trait"),
                    "symbolKey": "old-key",
                    "rustSignatureSha256": sdk_contract._digest_text(item["signature"]),
                    **sdk_contract._mapping_projection(mapping),
                }
            )
    return inventory_report, rust, python, ledger


def evidence_documents(*, stale_suite: str | None = None) -> list[dict[str, Any]]:
    documents = []
    for name in sdk_contract.REQUIRED_SUITES:
        matches = {"sourceRevision": True, "pythonRuntime": True, "nativeBinary": True}
        if name == stale_suite:
            matches["nativeBinary"] = False
        documents.append(
            {
                "runner": {"command": ["python", f"scripts/sdk-parity/{name}"]},
                "outcome": "passed",
                "snapshotMatches": matches,
                "snapshotMatchesAll": all(matches.values()),
                "cases": [{"comparisons": [{"name": "fixture", "equal": True}]}],
            }
        )
    return documents


class SdkContractTests(unittest.TestCase):
    def test_new_root_namespace_cannot_escape_scope_review(self) -> None:
        report, rust, python, ledger = make_inputs()
        contract = sdk_contract.build_contract(report)
        rust["items"].append(rust_item("yosoi::engine", "module", "pub mod engine"))
        _, drift = sdk_contract.prepare_ledger(contract, rust, python, ledger)
        self.assertTrue(
            any(
                item["kind"] == "rust-declaration-added"
                and item["rustPath"] == "yosoi::engine"
                for item in drift
            )
        )

    def setUp(self) -> None:
        self.inventory_report, self.rust, self.python, self.ledger = make_inputs()
        self.contract = sdk_contract.build_contract(self.inventory_report)

    def prepare(
        self,
        *,
        rust: dict[str, Any] | None = None,
        python: dict[str, Any] | None = None,
    ):
        return sdk_contract.prepare_ledger(
            self.contract,
            rust or self.rust,
            python or self.python,
            self.ledger,
        )

    def test_new_public_declaration_is_structural_drift(self) -> None:
        rust = copy.deepcopy(self.rust)
        rust["items"].append(
            rust_item("yosoi::map::MapRequest::new_api", "function", "pub fn new_api()")
        )
        _fresh, drift = self.prepare(rust=rust)
        self.assertEqual([entry["kind"] for entry in drift], ["rust-declaration-added"])

    def test_changed_function_argument_is_structural_drift(self) -> None:
        rust = copy.deepcopy(self.rust)
        rust["items"][-1]["signature"] = "pub fn with_depth(self, depth: u16) -> Self"
        _fresh, drift = self.prepare(rust=rust)
        self.assertIn("rust-signature-changed", [entry["kind"] for entry in drift])

    def test_deleted_public_field_is_structural_drift(self) -> None:
        rust = copy.deepcopy(self.rust)
        rust["items"].pop(1)
        _fresh, drift = self.prepare(rust=rust)
        self.assertIn("rust-declaration-removed", [entry["kind"] for entry in drift])

    def test_python_argument_change_is_structural_drift(self) -> None:
        python = copy.deepcopy(self.python)
        python["targets"]["yosoi.map.MapRequest"]["signature"]["display"] = (
            "(depth: int) -> MapRequest"
        )
        _fresh, drift = self.prepare(python=python)
        self.assertIn("python-target-changed", [entry["kind"] for entry in drift])

    def test_python_schema_alias_change_is_structural_drift(self) -> None:
        python = copy.deepcopy(self.python)
        python["targets"]["yosoi.map.MapRequest"]["alias"] = "RenamedMapRequest"
        _fresh, drift = self.prepare(python=python)
        self.assertIn("python-target-changed", [entry["kind"] for entry in drift])

    def test_missing_python_mapped_target_is_structural_drift(self) -> None:
        python = copy.deepcopy(self.python)
        python["targets"].pop("yosoi.map.MapRequest")
        _fresh, drift = self.prepare(python=python)
        self.assertIn("python-target-removed", [entry["kind"] for entry in drift])

    def test_source_and_native_hash_changes_rebase_only_ephemeral_pins(self) -> None:
        rust = copy.deepcopy(self.rust)
        rust["sourceRevision"] = "2" * 40
        rust["fixtureExecutables"] = {"diagnostics": "f" * 64}
        python = copy.deepcopy(self.python)
        python["implementationDigest"] = "9" * 64
        before = copy.deepcopy(self.ledger)
        fresh, drift = self.prepare(rust=rust, python=python)
        self.assertEqual(drift, [])
        self.assertEqual(self.ledger, before)
        self.assertEqual(fresh["sourcePin"]["sourceRevision"], "2" * 40)
        self.assertEqual(fresh["pythonPin"]["implementationDigest"], "9" * 64)
        function_entry = next(
            entry
            for entry in fresh["entries"]
            if entry["rustPath"] == "yosoi::map::MapRequest::with_depth"
        )
        self.assertEqual(function_entry["symbolKey"], rust["items"][-1]["symbolKey"])
        report_input = copy.deepcopy(self.inventory_report)
        report_input["source"]["revision"] = rust["sourceRevision"]
        report_input["source"]["inventorySignature"] = rust["inventorySignature"]
        sdk_report = sdk_contract.evaluate_contract(
            self.contract,
            rust,
            python,
            report_input,
            evidence_documents(),
            drift,
        )
        self.assertEqual(sdk_report["parityStatus"], "complete")
        self.assertEqual(
            sdk_report["generatedFrom"]["fixtureExecutables"],
            rust["fixtureExecutables"],
        )

    def test_changed_ledger_argument_mapping_is_structural_drift(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["entries"][-1]["argumentMappings"] = [
            {
                "rustArgument": "depth",
                "pythonArgument": "limit",
                "conversion": "changed mapping",
            }
        ]
        _fresh, drift = sdk_contract.prepare_ledger(
            self.contract, self.rust, self.python, ledger
        )
        self.assertIn("ledger-mapping-changed", [entry["kind"] for entry in drift])

    def test_exact_trait_symbol_keys_win_and_debug_display_stay_distinct(self) -> None:
        rust_path = "yosoi::search::SearchResultUrl::fmt"
        signature = "fn fmt(&self, f: &mut Formatter<'_>) -> Result"
        signature_digest = sdk_contract._digest_text(signature)

        def trait_item(trait: str, source: str) -> dict[str, Any]:
            return rust_item(
                rust_path,
                "function",
                signature,
                trait=trait,
                surface="member",
                parent="yosoi::search::SearchResultUrl",
                key=(
                    f"member:function:{rust_path}@signature:{signature_digest}"
                    f"@trait:{trait}@source:{source}"
                ),
            )

        debug_item = trait_item("Debug", "a" * 64)
        display_item = trait_item("Display", "b" * 64)
        report = {
            "source": {"revision": "1" * 40, "inventorySignature": "c" * 64},
            "python": {"targets": {}},
            "coverage": {
                "items": [
                    {
                        **debug_item,
                        "status": "missing",
                        "python": None,
                        "mapping": None,
                        "evidence": [],
                    },
                    {
                        **display_item,
                        "status": "missing",
                        "python": None,
                        "mapping": None,
                        "evidence": [],
                    },
                ]
            },
        }
        contract = sdk_contract.build_contract(report)
        python = {
            "surfaceDigest": "d" * 64,
            "implementationDigest": "e" * 64,
            "targets": {},
        }
        rust = {
            "sourceRevision": "1" * 40,
            "inventorySignature": "c" * 64,
            "featureProfileDigest": "f" * 64,
            "items": [debug_item, display_item],
        }
        ledger = {
            "entries": [
                {
                    "rustPath": rust_path,
                    "trait": "Display",  # symbolKey is the authoritative selector
                    "symbolKey": debug_item["symbolKey"],
                    "decision": "mapped",
                    "pythonTarget": "repr",
                },
                {
                    "rustPath": rust_path,
                    "trait": "Display",
                    "symbolKey": display_item["symbolKey"],
                    "decision": "mapped",
                    "pythonTarget": "str",
                },
            ]
        }
        fresh, drift = sdk_contract.prepare_ledger(contract, rust, python, ledger)
        self.assertEqual(drift, [])
        self.assertEqual(
            [entry["symbolKey"] for entry in fresh["entries"]],
            [debug_item["symbolKey"], display_item["symbolKey"]],
        )

        current_debug = trait_item("Debug", "1" * 64)
        current_display = trait_item("Display", "2" * 64)
        rust["items"] = [current_debug, current_display]
        fresh, drift = sdk_contract.prepare_ledger(contract, rust, python, ledger)
        self.assertEqual(drift, [])
        self.assertEqual(
            [entry["symbolKey"] for entry in fresh["entries"]],
            [current_debug["symbolKey"], current_display["symbolKey"]],
        )

    def test_stale_native_binary_proof_fails(self) -> None:
        _fresh, drift = self.prepare()
        report = sdk_contract.evaluate_contract(
            self.contract,
            self.rust,
            self.python,
            self.inventory_report,
            evidence_documents(stale_suite="run_serde_conformance.py"),
            drift,
        )
        self.assertEqual(report["parityStatus"], "stale")
        self.assertIn(
            "run_serde_conformance.py",
            report["behaviorStatus"]["staleSuites"],
        )
        self.assertTrue(sdk_contract.sdk_failures(report))

    def test_live_checker_missing_status_does_not_count_as_mapped(self) -> None:
        _fresh, drift = self.prepare()
        report_input = copy.deepcopy(self.inventory_report)
        report_input["coverage"]["items"][1]["status"] = "missing"
        sdk_report = sdk_contract.evaluate_contract(
            self.contract,
            self.rust,
            self.python,
            report_input,
            evidence_documents(),
            drift,
        )
        self.assertFalse(sdk_report["mappingStatus"]["complete"])
        self.assertEqual(sdk_report["counts"]["mapped"], 2)
        self.assertTrue(sdk_contract.sdk_failures(sdk_report))

    def test_all_nine_fresh_capabilities_can_pass_with_mapped_items_unverified(
        self,
    ) -> None:
        _fresh, drift = self.prepare()
        report = sdk_contract.evaluate_contract(
            self.contract,
            self.rust,
            self.python,
            self.inventory_report,
            evidence_documents(),
            drift,
        )
        self.assertEqual(report["parityStatus"], "complete")
        self.assertEqual(report["behaviorStatus"]["passed"], True)
        self.assertEqual(report["counts"]["mappedButUnverified"], 3)
        self.assertEqual(sdk_contract.sdk_failures(report), [])

    def test_contract_loader_rejects_out_of_scope_declaration(self) -> None:
        contract = copy.deepcopy(self.contract)
        declaration = copy.deepcopy(contract["declarations"][0])
        declaration["rustPath"] = "yosoi::engine::InternalThing"
        declaration["id"] = "yosoi::engine::InternalThing|struct|trait:"
        contract["declarations"].append(declaration)
        with self.assertRaisesRegex(ValueError, "outside the reviewed SDK scope"):
            sdk_contract._validate_contract(contract)

    def test_inconsistent_complete_summary_cannot_pass(self) -> None:
        report = {
            "parityStatus": "complete",
            "mappingStatus": {"complete": False},
            "behaviorStatus": {"passed": False},
            "structuralDrift": [],
        }
        self.assertTrue(sdk_contract.sdk_failures(report))


if __name__ == "__main__":
    unittest.main()
