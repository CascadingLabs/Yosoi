"""Pure guards for actual video fixture generation, pixels and API mappings."""

from __future__ import annotations

import copy
import hashlib
import struct
import unittest
import zlib
from pathlib import Path

import run_sdk_parity
import run_video_conformance as runner
import sdk_contract
import video_conformance as fixture
from video_surface_mappings import video_mapping

import parity


def frame_snapshot():
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    raw = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0\x01\x02\x03\xff"))
        + chunk(b"IEND", b"")
    )
    digest = hashlib.sha256(raw).hexdigest()
    artifact = {"sha256": digest, "source": {"kind": "video_frame"}}
    return {
        "class": "DecodedFrame",
        "png": list(raw),
        "rgba": [1, 2, 3, 255],
        "info": {
            "width": 1,
            "height": 1,
            "requested_us": 0,
            "position_us": 0,
            "source_pts_us": 0,
            "png_bytes": len(raw),
            "png_sha256": digest,
            "pixel_artifact": artifact,
        },
        "pixel_artifact": {"info": artifact, "bytes": list(raw)},
    }


class VideoConformanceTests(unittest.TestCase):
    def test_generator_is_bounded_serial_and_contains_audio(self):
        command = runner.fixture_command("/ffmpeg", Path("/fixture.mp4"))
        self.assertEqual(command[0], "/ffmpeg")
        for flag, value in (
            ("-t", "1"),
            ("-threads:v", "1"),
            ("-threads:a", "1"),
            ("-filter_threads", "1"),
            ("-c:v", "mpeg4"),
            ("-c:a", "aac"),
        ):
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertIn("testsrc2=size=64x32:rate=4", command)
        self.assertIn("sine=frequency=440:sample_rate=8000", command)
        self.assertIn("1:a:0", command)
        self.assertNotIn("-an", command)
        self.assertIn("+bitexact", command)

    def test_missing_tools_fail_instead_of_skipping(self):
        with self.assertRaisesRegex(RuntimeError, "ffmpeg, ffprobe"):
            runner.require_tools(which=lambda _: None)

    def test_all_twelve_prior_suites_remain_and_video_is_additive(self):
        prior = {
            "python_conformance",
            "python_diagnostics_conformance",
            "python_schema_errors_conformance",
            "python_value_equality_conformance",
            "python_errors_conformance",
            "python_map_ordering_conformance",
            "python_serde_conformance",
            "python_document_errors_conformance",
            "python_webtarget_conformance",
            "media_documents_conformance",
            "surface_conformance",
            "image_surface_conformance",
        }
        names = [name for name, _, _ in run_sdk_parity.EXAMPLES]
        self.assertTrue(prior.issubset(names))
        self.assertIn(
            ("video_conformance", "run_video_conformance.py", True),
            run_sdk_parity.EXAMPLES,
        )
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("run_video_conformance.py", sdk_contract.REQUIRED_SUITES)
        self.assertEqual(
            len(run_sdk_parity.EXAMPLES), len(sdk_contract.REQUIRED_SUITES)
        )

    def test_actual_png_pixels_and_metadata_are_required(self):
        fixture.validate_frame(frame_snapshot())
        for field in ("png", "rgba", "pixel_artifact"):
            damaged = copy.deepcopy(frame_snapshot())
            damaged[field] = []
            with self.subTest(field=field), self.assertRaises(ValueError):
                fixture.validate_frame(damaged)
        damaged = frame_snapshot()
        damaged["info"]["png_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "digest"):
            fixture.validate_frame(damaged)

    def test_requested_time_is_not_substituted_for_measured_time(self):
        value = frame_snapshot()
        value["info"].update(requested_us=125000, position_us=0)
        with self.assertRaisesRegex(ValueError, "before the requested"):
            fixture.validate_frame(value)

    def test_archive_ids_are_validated_while_selected_values_are_compared(self):
        selected = frame_snapshot()
        left = {"document": "document:v1:00000000-0000-4000-8000-000000000001"}
        right = {"document": "document:v1:00000000-0000-4000-8000-000000000002"}
        arguments = {
            "reference": {"kind": "FrameArchiveRef", "selected_value": selected},
            "observed_storage_reference": left,
        }
        case = {
            "name": "archive-frame",
            "rustPath": fixture.CASE_PATHS["archive-frame"],
            "input": arguments,
            "rust": selected,
        }
        observed = copy.deepcopy(arguments)
        observed["observed_storage_reference"] = right
        row = fixture.comparison(case, selected, observed)
        self.assertTrue(row["equal"])
        self.assertEqual(
            row["mappingValues"]["rust"]["reference"],
            row["mappingValues"]["python"]["reference"],
        )
        self.assertNotEqual(
            row["mappingValues"]["rust"]["observed_storage_reference"],
            row["mappingValues"]["python"]["observed_storage_reference"],
        )
        observed["observed_storage_reference"] = {"document": "plan:v1:invalid"}
        with self.assertRaises(ValueError):
            fixture.comparison(case, selected, observed)
        observed = copy.deepcopy(arguments)
        observed["reference"]["selected_value"] = {"class": "wrong-body"}
        with self.assertRaisesRegex(ValueError, "selected value"):
            fixture.comparison(case, selected, observed)

    def test_video_archive_ref_retains_exact_observation(self):
        selected = {"class": "VideoSurface", "observation": {"id": "video:actual"}}
        args = {
            "reference": {"kind": "VideoArchiveRef", "selected_value": selected},
            "observed_storage_reference": {
                "document": "document:v1:00000000-0000-4000-8000-000000000001",
                "observation": "video:foreign",
            },
        }
        with self.assertRaisesRegex(ValueError, "observation"):
            fixture.validate_storage_reference("archive-video", args, selected)

    def test_cancellable_mapping_requires_actual_public_token_argument(self):
        path = "yosoi::VideoSurface::frame_cancellable"
        item = {
            "rustPath": path,
            "kind": "function",
            "trait": None,
            "symbolKey": "frame",
            "signature": (
                "pub async fn frame_cancellable(&self, reference: &Reference, "
                "cancellation: &CancellationToken)"
            ),
            "rustArguments": [
                {"name": "self", "receiver": True, "type": "&self"},
                {"name": "reference", "receiver": False, "type": "&Reference"},
                {
                    "name": "cancellation",
                    "receiver": False,
                    "type": "&CancellationToken",
                },
            ],
        }
        target = {
            "kind": "callable",
            "signature": {
                "parameters": [
                    {"name": "reference", "hasDefault": False},
                    {"name": "cancellation", "hasDefault": True, "default": None},
                ]
            },
        }
        python = {"targets": {"yosoi.VideoSurface.frame": target}}
        entry = video_mapping(item, python)
        self.assertEqual(entry["decision"], "mapped")
        self.assertEqual(entry["pythonTarget"], "yosoi.VideoSurface.frame")
        self.assertIn("cleanup", entry["semanticEquivalent"])
        self.assertIsNone(parity._mapping_configuration_problem(item, entry, target))
        target["signature"]["parameters"].pop()
        self.assertIsNone(video_mapping(item, python))

    def test_missing_or_duplicate_fixture_journeys_cannot_pass(self):
        with self.assertRaises(ValueError):
            fixture.validate_fixture_set(
                {
                    "schemaVersion": 1,
                    "kind": fixture.FIXTURE_KIND,
                    "cases": [],
                    "errorCases": [],
                }
            )


if __name__ == "__main__":
    unittest.main()
