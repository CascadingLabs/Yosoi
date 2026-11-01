"""Pure network mapping/inventory checks; no native or provider operations run."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import network_surface_mappings as mappings
import sdk_contract

import parity


class NetworkMappingTests(unittest.TestCase):
    def test_public_primitive_module_constants_keep_distinct_names(self):
        name = "network_constants_fixture"
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                package = root / name
                package.mkdir()
                (package / "__init__.py").write_text(
                    "SCHEMA = 'fixture.v1'\n"
                    "RESOURCE_BYTES = 8388608\nTOTAL_BYTES = 8388608\n"
                    "ENABLED = False\nOPTIONAL = None\nRATIO = 0.5\n"
                    "lowercase = 1\n_PRIVATE = 2\nLIST = []\n"
                    "NONFINITE = float('inf')\n"
                )
                result = parity.introspect_python_package(name, root)
            targets = result["targets"]
            for key, expected in {
                "SCHEMA": "fixture.v1",
                "RESOURCE_BYTES": 8388608,
                "TOTAL_BYTES": 8388608,
                "ENABLED": False,
                "OPTIONAL": None,
                "RATIO": 0.5,
            }.items():
                target = f"{name}.{key}"
                self.assertEqual(
                    targets[target],
                    {
                        "kind": "module-constant",
                        "canonicalTarget": target,
                        "value": expected,
                    },
                )
            for excluded in ("lowercase", "_PRIVATE", "LIST", "NONFINITE"):
                self.assertNotIn(f"{name}.{excluded}", targets)
            self.assertNotEqual(
                targets[f"{name}.RESOURCE_BYTES"]["canonicalTarget"],
                targets[f"{name}.TOTAL_BYTES"]["canonicalTarget"],
            )
        finally:
            sys.modules.pop(name, None)

    def test_compact_constants_and_type_aliases_remain_scoped_items(self):
        rows = [
            {
                "rustPath": "yosoi::surface::NETWORK_OBSERVATION_SCHEMA",
                "kind": "constant",
                "pythonTarget": "yosoi.surface.NETWORK_OBSERVATION_SCHEMA",
            },
            {
                "rustPath": "yosoi::surface::NetworkObservation",
                "kind": "type_alias",
                "pythonTarget": "yosoi.surface.NetworkObservation",
            },
        ]
        for row in rows:
            row.update(
                signatureSha256="a" * 64,
                pythonTargetSha256="b" * 64,
                rationale="Explicit public native value or exact NetworkWindow alias.",
            )
        compact = {
            "schemaVersion": 1,
            "kind": "yosoi-surface-sdk-contract",
            "declarations": rows,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "surface-contract.json"
            path.write_text(json.dumps(compact))
            declarations, entries = sdk_contract.load_surface_contract(path)
        self.assertEqual(len(entries), 2)
        for declaration in declarations:
            self.assertEqual(declaration["surface"], "item")
            self.assertTrue(declaration["symbolKey"].startswith("page:"))
            self.assertEqual(declaration["classification"], "sdk")
        self.assertEqual(
            {row["kind"] for row in declarations}, {"constant", "type_alias"}
        )

    def test_missing_public_counterpart_stays_missing(self):
        item = {
            "rustPath": "yosoi::surface::NetworkPayload::bytes",
            "kind": "function",
            "trait": None,
            "signature": "pub fn bytes(&self) -> &[u8]",
            "symbolKey": "bytes",
            "rustArguments": [{"name": "self", "receiver": True, "type": "&self"}],
        }
        self.assertIsNone(mappings.network_mapping(item, {"targets": {}}))

    def test_file_payload_view_preserves_the_typed_public_value(self):
        item = {
            "rustPath": "yosoi::surface::NetworkPayloadValue::File",
            "parentRustPath": "yosoi::surface::NetworkPayloadValue",
            "kind": "variant",
            "trait": None,
            "signature": "File(Box<FileDocument>)",
            "symbolKey": "file",
            "rustArguments": [
                {
                    "name": "0",
                    "type": "Box<yosoi::documents::FileDocument>",
                    "receiver": False,
                }
            ],
        }
        target_name = "yosoi.surface.NetworkPayload"
        target = {
            "kind": "class",
            "canonicalTarget": target_name,
            "fields": [
                {
                    "name": "reference",
                    "modelFields": [
                        {
                            "name": "document_kind",
                            "literalChoices": ["html", "json", "file"],
                        }
                    ],
                },
                {"name": "value"},
            ],
        }
        python = {"targets": {target_name: target}}
        entry = mappings.network_mapping(item, python)
        self.assertEqual(entry["mappingDirection"], "output")
        self.assertEqual(entry["outputBinding"]["tag"], "file")
        self.assertEqual(
            entry["outputBinding"]["pythonFields"][0]["pythonFieldPath"], "value"
        )
        self.assertIsNone(
            parity._mapping_configuration_problem(
                item, entry, target, python["targets"]
            )
        )
        broken = copy.deepcopy(entry)
        broken["outputBinding"]["pythonFields"][0]["pythonFieldPath"] = "missing_value"
        self.assertIsNotNone(
            parity._mapping_configuration_problem(
                item, broken, target, python["targets"]
            )
        )

    def test_async_rust_behavior_source_is_checked_by_actual_test_name(self):
        name = "yosoi.Document"
        binding = {
            "schemaTarget": name,
            "behaviorEvidence": [
                {
                    "path": "python/tests/test_surface_network.py",
                    "test": (
                        "test_offline_network_payload_accepts_exact_owned_reference"
                    ),
                },
                {
                    "path": "crates/yosoi/tests/surface_network.rs",
                    "test": (
                        "cli_restores_network_payloads_from_portable_outcomes_"
                        "without_a_browser"
                    ),
                },
            ],
        }
        targets = {name: {"kind": "class", "canonicalTarget": name}}
        self.assertIsNone(
            parity._concrete_model_behavior_problem(binding, name, targets)
        )
        binding["behaviorEvidence"][1]["test"] = "test_that_does_not_exist"
        self.assertIn(
            "absent", parity._concrete_model_behavior_problem(binding, name, targets)
        )


if __name__ == "__main__":
    unittest.main()
