"""Guard the representation coverage promised by the Surface parity gate."""

import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
