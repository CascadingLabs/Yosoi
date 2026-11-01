"""Focused image fixture validation, actual wheel observations, and attribution."""

from __future__ import annotations

import asyncio
import copy
import struct
import unittest
import zlib

import image_surface_conformance as contract
import image_surface_runtime as runtime
import run_sdk_parity
import sdk_contract


def png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    rows = bytearray()
    for y in range(4):
        rows.append(0)
        for x in range(8):
            rows.extend(
                {
                    (True, True): (255, 0, 0, 255),
                    (False, True): (0, 255, 0, 255),
                    (True, False): (0, 0, 255, 255),
                    (False, False): (255, 255, 0, 255),
                }[x < 4, y < 2]
            )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 4, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class ImageContractTests(unittest.TestCase):
    def test_known_png_and_checksum_rejection(self) -> None:
        payload = png()
        width, height, pixels = contract.rgba_png(payload)
        self.assertEqual((width, height), (8, 4))
        self.assertEqual(pixels[:4], [255, 0, 0, 255])
        damaged = bytearray(payload)
        damaged[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            contract.rgba_png(bytes(damaged))

    def test_truncation_and_trailing_data_rejected(self) -> None:
        for payload in (png()[:-1], png() + b"extra"):
            with self.assertRaises(ValueError):
                contract.rgba_png(payload)

    def test_rgb_png_used_by_jpeg_transforms_expands_alpha(self) -> None:
        def chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + tag
                + data
                + struct.pack(">I", zlib.crc32(tag + data))
            )

        payload = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x01\x02\x03"))
            + chunk(b"IEND", b"")
        )
        self.assertEqual(contract.rgba_png(payload), (1, 1, [1, 2, 3, 255]))

    def test_metadata_only_fixture_rejected(self) -> None:
        with self.assertRaises(ValueError):
            contract.validate_artifact({"class": "PixelArtifact", "info": {}})
        with self.assertRaises(ValueError):
            contract.validate_fixture_set(
                {
                    "schemaVersion": 1,
                    "kind": contract.FIXTURE_KIND,
                    "cases": [],
                    "errorCases": [],
                }
            )

    def test_additive_required_suite_registration(self) -> None:
        self.assertIn(
            ("image_surface_conformance", "run_image_surface_conformance.py", True),
            run_sdk_parity.EXAMPLES,
        )
        self.assertIn("run_image_surface_conformance.py", sdk_contract.REQUIRED_SUITES)
        self.assertEqual(len(run_sdk_parity.EXAMPLES), 12)
        self.assertEqual(len(sdk_contract.REQUIRED_SUITES), 12)

    def test_attribution_requires_pinned_declaration_and_actual_arguments(self) -> None:
        path = "yosoi::surface::ImageSurface::overview_image"
        row = contract.comparison(
            {
                "name": "overview",
                "rustPath": path,
                "input": {"max_side": 4},
                "rust": {"width": 4},
            },
            {"width": 4},
            {"max_side": 4},
        )
        rust = {"items": [{"rustPath": path, "symbolKey": "overview-symbol"}]}
        entry = {
            "decision": "mapped",
            "rustPath": path,
            "symbolKey": "overview-symbol",
            "pythonTarget": "yosoi.ImageSurface.overview_image",
            "argumentMappings": [
                {"rustArgument": "max_side", "pythonArgument": "max_side"}
            ],
        }
        with self.assertRaisesRegex(ValueError, "pinned mapping"):
            contract.evidence_cases([row], rust, {"entries": []})
        evidence = contract.evidence_cases([row], rust, {"entries": [entry]})
        self.assertEqual(evidence[0]["outcome"], "passed")
        row["mappingValues"]["python"]["max_side"] = 5
        evidence = contract.evidence_cases([row], rust, {"entries": [entry]})
        self.assertEqual(evidence[0]["outcome"], "failed")
        del row["mappingValues"]["python"]["max_side"]
        with self.assertRaisesRegex(ValueError, "lacks max_side"):
            contract.evidence_cases([row], rust, {"entries": [entry]})

    def test_receiver_default_and_unit_checks_are_observed(self) -> None:
        path = "yosoi::surface::ImageSurface::crop_rect"
        values = {
            "self": {"observation": "actual-observation"},
            "max_png_bytes": 8388608,
            "width": 4,
        }
        row = contract.comparison(
            {"name": "crop", "rustPath": path, "input": values, "rust": 1},
            1,
            copy.deepcopy(values),
        )
        entry = {
            "decision": "mapped",
            "rustPath": path,
            "symbolKey": "crop-symbol",
            "pythonTarget": "yosoi.ImageSurface.crop_rect",
            "receiverMapping": {"rustArgument": "self", "pythonArgument": "self"},
            "defaults": [{"id": "crop:max_png_bytes"}],
            "units": [{"id": "crop:width"}],
        }
        result = contract.evidence_cases(
            [row],
            {"items": [{"rustPath": path, "symbolKey": "crop-symbol"}]},
            {"entries": [entry]},
        )
        self.assertEqual(
            {check["kind"] for check in result[0]["mappingChecks"]},
            {"receiver", "default", "unit"},
        )
        self.assertTrue(all(check["equal"] for check in result[0]["mappingChecks"]))


class InstalledImageObservationTests(unittest.TestCase):
    def setUp(self) -> None:
        import yosoi as ys

        self.ys = ys
        self.sf = ys.surface
        self.document = ys.ImageDocument.from_bytes("image-parity", png())
        self.direct = self.sf.PixelArtifact.from_image_document(self.document)
        self.surface = self.sf.ImageSurface(self.document, tile_side=32)

    def test_actual_pixels_digest_and_metadata(self) -> None:
        direct = runtime.artifact(self.direct)
        contract.validate_artifact(direct)
        self.assertEqual(bytes(direct["bytes"]), self.document.bytes)
        cropped = self.surface.crop_rect(self.sf.PixelRect(x=0, y=0, width=4, height=2))
        snapshot = runtime.artifact(cropped.artifact)
        contract.validate_artifact(snapshot)
        self.assertEqual(snapshot["rgba"], [255, 0, 0, 255] * 8)
        changed = copy.deepcopy(snapshot)
        changed["rgba"][0] = 0
        with self.assertRaisesRegex(ValueError, "actual PNG pixels"):
            contract.validate_artifact(changed)
        changed = copy.deepcopy(snapshot)
        changed["info"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "digest"):
            contract.validate_artifact(changed)

    def test_actual_archive_and_fresh_portable_restore(self) -> None:
        cropped = self.surface.crop_rect(
            self.sf.PixelRect(x=0, y=0, width=4, height=2)
        ).artifact
        observed, arguments = asyncio.run(
            runtime.archive_observation(
                self.ys, self.sf, self.surface, self.direct, cropped, 32
            )
        )
        self.assertEqual(observed["artifact_class"], "PixelArtifact")
        self.assertEqual(observed["outcome_class"], "Outcome")
        self.assertEqual(observed["source_count"], 2)
        self.assertEqual(observed["root"], runtime.artifact(self.direct))
        self.assertEqual(observed["crop"], runtime.artifact(cropped))
        self.assertEqual(arguments["archive"], "original")
        self.assertIn("document", arguments["reference"])


if __name__ == "__main__":
    unittest.main()
