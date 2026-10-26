"""Guard the representation coverage promised by the Surface parity gate."""

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_surface_conformance as surface


class SurfaceVectorsTest(unittest.TestCase):
    def test_repository_vectors_cover_every_supported_document_class(self) -> None:
        path = (
            Path(__file__).resolve().parents[2] / "python/parity/surface-vectors.json"
        )
        self.assertEqual(len(surface.load_vectors(path)), 6)

    def test_empty_duplicate_and_unknown_fixture_sets_cannot_pass(self) -> None:
        path = (
            Path(__file__).resolve().parents[2] / "python/parity/surface-vectors.json"
        )
        original = json.loads(path.read_text())
        duplicate = json.loads(json.dumps(original))
        duplicate["cases"][-1] = duplicate["cases"][0]
        wrong_schema = {**original, "schemaVersion": 2}
        for value in ([], {"schemaVersion": 1, "cases": []}, duplicate, wrong_schema):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                fixture = Path(folder) / "vectors.json"
                fixture.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    surface.load_vectors(fixture)

    def test_behavior_evidence_uses_public_root_and_only_exercised_operations(self):
        mapped = {
            "rustPath": "yosoi::Surface::new",
            "pythonTarget": "yosoi.Surface",
            "symbolKey": "new",
            "decision": "mapped",
            "argumentMappings": [],
        }
        unexercised = {**mapped, "rustPath": "yosoi::Surface::combine"}
        other_owner = {**mapped, "rustPath": "yosoi::Other::new"}
        rust = {
            "sourceRevision": "1" * 40,
            "inventorySignature": "a" * 64,
            "featureProfileDigest": "b" * 64,
        }
        python = {
            "surfaceDigest": "c" * 64,
            "implementationDigest": "d" * 64,
            "runtime": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            args = argparse.Namespace(
                rust_reference=Path(directory), ledger=Path(directory), out=output
            )
            values = [{"name": "shared-vector", "content": "Arc desk lamp"}]
            with (
                patch.object(surface.parity, "load_rust_inventory", return_value=rust),
                patch.object(
                    surface.parity, "introspect_python_package", return_value=python
                ),
                patch.object(
                    surface.parity,
                    "load_ledger",
                    return_value={"entries": [mapped, unexercised, other_owner]},
                ),
            ):
                surface.write_evidence(args, values, values)
            evidence = json.loads(output.read_text())
            self.assertEqual(
                [case["rustPath"] for case in evidence["cases"]],
                ["yosoi::Surface::new"],
            )
            self.assertTrue(evidence["cases"][0]["comparisons"][0]["equal"])
            raw = output.with_name("evidence-results.json")
            self.assertEqual(
                evidence["resultArtifact"]["sha256"],
                surface.parity.digest_bytes(raw.read_bytes()),
            )


if __name__ == "__main__":
    unittest.main()
