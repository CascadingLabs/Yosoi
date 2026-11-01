"""Focused fixture-contract and attribution tests for media SDK parity."""

from __future__ import annotations

import hashlib
import unittest
from types import SimpleNamespace
from typing import Any

import media_documents_runtime as runtime
import run_media_documents_conformance as runner
from media_documents_conformance import (
    DEFAULT_FILE_MAX_BYTES,
    ERROR_PATH,
    EXPECTED_ERRORS,
    FILE_DOCUMENT_PATH,
    FILE_FACTORY_PATH,
    FILE_METADATA_PATH,
    FILE_READ_PATH,
    MAX_FILE_BYTES,
    MAX_SOURCE_BYTES,
    evidence_cases,
    validate_fixture_set,
)


def _snapshot(
    name: str,
    kind: str,
    payload: bytes,
    *,
    constructor: str | None = None,
    factory_defaults: bool = False,
    read_file_case: bool = False,
) -> dict[str, Any]:
    digest = hashlib.sha256(payload).hexdigest()
    source = "s" * 4_097 if name == "source-over-4k" else f"https://test.invalid/{name}"
    filename = "media-read-fixture.png" if read_file_case else f"{name}.bin"
    if read_file_case:
        metadata = dict.fromkeys(
            (
                "filename",
                "declared_media_type",
                "detected_media_type",
                "source",
                "capture_id",
                "session_id",
                "tab_id",
                "download_id",
                "probe_validated_video_container",
                "sha256",
            )
        )
        metadata["filename"] = filename
        metadata["detected_media_type"] = "image/png"
        metadata["sha256"] = digest
    elif factory_defaults:
        metadata = dict.fromkeys(
            (
                "filename",
                "declared_media_type",
                "detected_media_type",
                "source",
                "capture_id",
                "session_id",
                "tab_id",
                "download_id",
                "probe_validated_video_container",
                "sha256",
            )
        )
    else:
        metadata = {
            "filename": filename,
            "declared_media_type": "application/octet-stream",
            "detected_media_type": {
                "png": "image/png",
                "jpeg": "image/jpeg",
                "mp4": "video/mp4",
                "mp3": "audio/mpeg",
                "wav": "audio/wav",
            }.get(name.split("-")[1] if name.startswith("typed-") else name),
            "source": source,
            "capture_id": "capture-media-conformance",
            "session_id": "session-media-conformance",
            "tab_id": "tab-media-conformance",
            "download_id": f"download-{name}",
            "probe_validated_video_container": None,
            "sha256": digest,
        }
    if not factory_defaults and not read_file_case:
        metadata["detected_media_type"] = {
            "image": "image/png",
            "video": "video/mp4",
            "audio": "audio/mpeg",
            "binary": None,
        }[kind]
        metadata["sha256"] = digest
    else:
        metadata["sha256"] = digest
    input_metadata = (
        {"filename": filename}
        if read_file_case
        else {
            key: value
            for key, value in metadata.items()
            if key
            not in {
                "detected_media_type",
                "probe_validated_video_container",
                "sha256",
            }
        }
    )
    id_value = (
        "media-local-read"
        if read_file_case
        else f"media-{name}"
        if not constructor
        else f"{name}-id"
    )
    limits = (
        {"max_bytes": len(payload)}
        if read_file_case
        else (
            None
            if constructor == "from_bytes"
            else {
                "max_bytes": len(payload)
                if constructor == "from_bytes_with_limits"
                else DEFAULT_FILE_MAX_BYTES
            }
        )
    )
    if constructor is None and not read_file_case:
        limits = {"max_bytes": DEFAULT_FILE_MAX_BYTES}
    rust_arguments = {"id": id_value, "bytes": list(payload)}
    if read_file_case:
        rust_arguments = {
            "id": id_value,
            "path": filename,
            "limits": limits,
        }
    elif constructor is None or factory_defaults:
        rust_arguments.update(
            {
                "metadata": metadata,
                "limits": {"max_bytes": DEFAULT_FILE_MAX_BYTES},
            }
        )
    elif constructor == "from_bytes_with_limits":
        rust_arguments["limits"] = limits
    elif constructor == "from_bytes_with_metadata":
        rust_arguments["metadata"] = metadata
        rust_arguments["limits"] = limits
    return {
        "name": name,
        "input": {
            "id": id_value,
            "bytes": list(payload),
            "metadata": input_metadata,
            **({"filename": filename} if read_file_case else {}),
            "limits": limits,
            "constructor": constructor,
            "omit_optional_arguments": factory_defaults,
            "rust_arguments": rust_arguments,
        },
        "rust": {
            "kind": kind,
            "id": id_value,
            "metadata": metadata,
            "bytes": list(payload),
            "byte_len": len(payload),
            "sha256": digest,
        },
    }


def _fixtures() -> dict[str, Any]:
    payloads = {
        "png": ("image", b"\x89PNG\r\n\x1a\n"),
        "jpeg": ("image", b"\xff\xd8\xff\xe0JFIF\x00"),
        "mp4": ("video", b"\x00\x00\x00\x10ftypmp42"),
        "mp3": ("audio", b"ID3\x04\x00\x00\x00\x00\x00\x00"),
        "wav": ("audio", b"RIFF\x24\x00\x00\x00WAVEfmt "),
        "opaque": ("binary", b"unknown bytes"),
        "empty": ("binary", b""),
        "source-over-4k": ("binary", b"opaque"),
    }
    cases = [
        _snapshot(name, kind, payload) for name, (kind, payload) in payloads.items()
    ]
    for kind, payload in (
        ("image", payloads["png"][1]),
        ("video", payloads["mp4"][1]),
        ("audio", payloads["mp3"][1]),
        ("binary", payloads["opaque"][1]),
    ):
        for constructor in (
            "from_bytes",
            "from_bytes_with_limits",
            "from_bytes_with_metadata",
        ):
            cases.append(
                _snapshot(
                    f"typed-{kind}-{constructor}",
                    kind,
                    payload,
                    constructor=constructor,
                )
            )
    cases.append(
        _snapshot(
            "factory-defaults",
            "binary",
            payloads["opaque"][1],
            factory_defaults=True,
        )
    )
    cases.append(
        _snapshot(
            "local-read",
            "image",
            payloads["png"][1],
            read_file_case=True,
        )
    )
    error_specs = {
        "typed-mismatch": (
            "TypeMismatch",
            {"expected": "image", "detected": None},
            {"id": "wrong-image", "bytes": list(b"unknown")},
        ),
        "payload-too-large": (
            "TooLarge",
            {"maximum": 2, "observed": len(b"unknown")},
            {"id": "too-large", "bytes": list(b"unknown"), "max_bytes": 2},
        ),
        "hard-limit": (
            "LimitExceedsHardMaximum",
            {"configured": MAX_FILE_BYTES + 1, "maximum": MAX_FILE_BYTES},
            {"configured": MAX_FILE_BYTES + 1},
        ),
        "source-over-limit": (
            "MetadataTooLong",
            {
                "field": "source",
                "maximum": MAX_SOURCE_BYTES,
                "observed": MAX_SOURCE_BYTES + 1,
            },
            {"source_length": MAX_SOURCE_BYTES + 1},
        ),
    }
    error_cases = [
        {
            "name": name,
            "operation": name,
            "input": input_value,
            "rust": {
                "rust_type": "yosoi::documents::FileDocumentError",
                "variant": variant,
                "details": details,
                "source_chain": [],
            },
        }
        for name, (variant, details, input_value) in error_specs.items()
    ]
    return {
        "schemaVersion": 1,
        "kind": "yosoi-media-documents-conformance-fixtures",
        "cases": cases,
        "errorCases": error_cases,
        "standaloneMetadata": {
            "filename": None,
            "declared_media_type": None,
            "detected_media_type": None,
            "source": None,
            "capture_id": None,
            "session_id": None,
            "tab_id": None,
            "download_id": None,
            "probe_validated_video_container": None,
            "sha256": None,
        },
        "equality": {
            "same_value_different_handles_and_limits": True,
            "different_identity": False,
        },
        "fileLimits": {
            "defaultMaxBytes": DEFAULT_FILE_MAX_BYTES,
            "hardMaxBytes": MAX_FILE_BYTES,
            "sourceMaxBytes": MAX_SOURCE_BYTES,
        },
    }


class MediaDocumentsConformanceTests(unittest.TestCase):
    def test_fixture_contract_covers_signatures_limits_and_value_semantics(self):
        cases, errors, standalone, equality, file_limits = validate_fixture_set(
            _fixtures()
        )
        self.assertEqual(len(cases), 22)
        self.assertEqual(len(errors), 4)
        self.assertEqual(
            set(EXPECTED_ERRORS.values()),
            {"TypeMismatch", "TooLarge", "LimitExceedsHardMaximum", "MetadataTooLong"},
        )
        self.assertIsNone(standalone["sha256"])
        self.assertTrue(equality["same_value_different_handles_and_limits"])
        self.assertEqual(file_limits["sourceMaxBytes"], MAX_SOURCE_BYTES)
        self.assertEqual(
            {case["rust"]["kind"] for case in cases},
            {"image", "video", "audio", "binary"},
        )

    def test_fixture_contract_rejects_omissions_and_byte_mismatch(self):
        fixture_set = _fixtures()
        fixture_set["cases"].pop()
        with self.assertRaisesRegex(ValueError, "fixture names"):
            validate_fixture_set(fixture_set)

        fixture_set = _fixtures()
        fixture_set["cases"][0]["rust"]["bytes"][0] ^= 1
        with self.assertRaisesRegex(ValueError, "value contract"):
            validate_fixture_set(fixture_set)

    def test_python_comparison_detects_wrong_concrete_class_or_payload(self):
        case = _fixtures()["cases"][0]
        observed = dict(case["rust"])
        observed["kind"] = "binary"
        observed["bytes"] = [0]
        comparison = runtime.compare_document_case(
            case, {"snapshot": observed, "evidenceRustPaths": []}, runner.parity
        )
        self.assertFalse(comparison["equal"])
        self.assertFalse(all(item["equal"] for item in comparison["comparisons"]))

    def test_metadata_getter_mappings_use_values_observed_in_both_snapshots(self):
        case = next(
            item for item in _fixtures()["cases"] if item["name"] == "factory-defaults"
        )
        comparison = runtime.compare_document_case(
            case,
            {
                "snapshot": case["rust"],
                "evidenceRustPaths": [FILE_FACTORY_PATH],
                "mappingValues": {"rust": {}, "python": {}},
            },
            runner.parity,
        )

        for field in case["rust"]["metadata"]:
            path = f"{FILE_METADATA_PATH}::{field}"
            values = comparison["mappingValuesByPath"][path]
            self.assertEqual(values["rust"], {field: case["rust"]["metadata"][field]})
            self.assertEqual(values["python"], {field: case["rust"]["metadata"][field]})
        filename = comparison["mappingValuesByPath"][f"{FILE_METADATA_PATH}::filename"]
        self.assertIsNone(filename["rust"]["filename"])
        self.assertIsNone(filename["python"]["filename"])

    def test_evidence_uses_the_exact_live_rust_mapping(self):
        path = f"{FILE_DOCUMENT_PATH}::Image"
        symbol_key = f"symbol:{path}"
        comparison = {
            "name": "png",
            "rustPath": path,
            "equal": True,
            "comparisons": [
                {
                    "name": "png:bytes",
                    "rustSha256": "a" * 64,
                    "pythonSha256": "a" * 64,
                    "equal": True,
                }
            ],
        }
        rust = {"items": [{"rustPath": path, "symbolKey": symbol_key}]}
        ledger = {
            "entries": [
                {
                    "rustPath": path,
                    "symbolKey": symbol_key,
                    "decision": "mapped",
                    "pythonTarget": "yosoi.ImageDocument",
                }
            ]
        }
        cases = evidence_cases([comparison], rust, ledger)
        self.assertEqual(cases[0]["rustPath"], path)
        self.assertEqual(cases[0]["pythonTarget"], "yosoi.ImageDocument")
        self.assertEqual(cases[0]["symbolKey"], symbol_key)

        with self.assertRaisesRegex(ValueError, "lacks a pinned mapping"):
            evidence_cases(
                [{**comparison, "rustPath": f"{ERROR_PATH}::TooLarge"}],
                rust,
                ledger,
            )

    def test_standalone_metadata_and_error_paths_are_tracked(self):
        self.assertEqual(FILE_METADATA_PATH, "yosoi::documents::FileMetadata")
        self.assertEqual(ERROR_PATH, "yosoi::documents::FileDocumentError")

    def test_factory_argument_and_python_default_mappings_are_digest_checked(self):
        path = FILE_FACTORY_PATH
        symbol_key = f"symbol:{path}"
        rust = {"items": [{"rustPath": path, "symbolKey": symbol_key}]}
        ledger = {
            "entries": [
                {
                    "rustPath": path,
                    "symbolKey": symbol_key,
                    "decision": "mapped",
                    "pythonTarget": "yosoi.documents.file_from_bytes",
                    "argumentMappings": [
                        {
                            "rustArgument": "bytes",
                            "pythonArgument": "content",
                            "conversion": "Vec<u8> maps to exact Python bytes",
                        }
                    ],
                    "defaults": [{"id": "python-default:metadata"}],
                }
            ]
        }
        pair = {
            "rust": {"bytes": [1, 2], "metadata": {"source": None}},
            "python": {"content": [1, 2], "metadata": {"source": None}},
        }
        comparison = {
            "name": "factory-defaults",
            "rustPath": path,
            "evidenceRustPaths": [path],
            "mappingValuesByPath": {path: pair},
            "comparisons": [
                {
                    "name": "factory-defaults:bytes",
                    "rustSha256": "a" * 64,
                    "pythonSha256": "a" * 64,
                    "equal": True,
                }
            ],
            "equal": True,
        }
        result = evidence_cases([comparison], rust, ledger)
        self.assertEqual(
            {(item["kind"], item["key"]) for item in result[0]["mappingChecks"]},
            {("argument", "bytes"), ("default", "python-default:metadata")},
        )
        self.assertTrue(all(item["equal"] for item in result[0]["mappingChecks"]))

    def test_local_file_read_is_attributed_to_read_file_with_basename(self):
        symbol_key = f"symbol:{FILE_READ_PATH}"
        rust = {"items": [{"rustPath": FILE_READ_PATH, "symbolKey": symbol_key}]}
        ledger = {
            "entries": [
                {
                    "rustPath": FILE_READ_PATH,
                    "symbolKey": symbol_key,
                    "decision": "mapped",
                    "pythonTarget": "yosoi.documents.read_file",
                    "argumentMappings": [
                        {"rustArgument": "id", "pythonArgument": "id"},
                        {"rustArgument": "path", "pythonArgument": "path"},
                        {"rustArgument": "limits", "pythonArgument": "limits"},
                    ],
                }
            ]
        }
        values = {
            "rust": {
                "id": "media-local-read",
                "path": "media-read-fixture.png",
                "limits": {"max_bytes": 8},
            },
            "python": {
                "id": "media-local-read",
                "path": "media-read-fixture.png",
                "limits": {"max_bytes": 8},
            },
        }
        comparison = {
            "name": "local-read",
            "rustPath": FILE_READ_PATH,
            "evidenceRustPaths": [FILE_READ_PATH],
            "mappingValuesByPath": {FILE_READ_PATH: values},
            "comparisons": [
                {
                    "name": "local-read:bytes",
                    "rustSha256": "b" * 64,
                    "pythonSha256": "b" * 64,
                    "equal": True,
                }
            ],
            "equal": True,
        }
        result = evidence_cases([comparison], rust, ledger)
        self.assertEqual(result[0]["rustPath"], FILE_READ_PATH)
        self.assertNotEqual(result[0]["rustPath"], FILE_FACTORY_PATH)
        self.assertTrue(all(item["equal"] for item in result[0]["mappingChecks"]))

    def test_local_read_observation_calls_read_file_with_a_bounded_temp_file(self):
        class FakeLimits:
            def __init__(self, *, max_bytes: int) -> None:
                self.max_bytes = max_bytes

            def model_dump(self) -> dict[str, int]:
                return {"max_bytes": self.max_bytes}

        class FakeMetadata:
            def __init__(self, **values: Any) -> None:
                self.values = values

            def model_dump(self) -> dict[str, Any]:
                return dict(self.values)

        class ImageDocument:
            def __init__(self, document_id: str, content: bytes) -> None:
                self.id = document_id
                self.metadata = FakeMetadata(
                    filename="media-read-fixture.png",
                    detected_media_type="image/png",
                    sha256=hashlib.sha256(content).hexdigest(),
                )
                self.bytes = content
                self.byte_len = len(content)
                self.sha256 = hashlib.sha256(content).hexdigest()

        observed_calls = []

        async def read_file(document_id, path, *, limits):
            content = path.read_bytes()
            observed_calls.append((document_id, path.name, limits.max_bytes))
            return ImageDocument(document_id, content)

        def unexpected_factory(*_args, **_kwargs):
            raise AssertionError("local-read fixture must use read_file")

        ys = SimpleNamespace(
            FileLimits=FakeLimits,
            FileMetadata=FakeMetadata,
            file_from_bytes=unexpected_factory,
            read_file=read_file,
        )
        case = next(
            case for case in _fixtures()["cases"] if case["name"] == "local-read"
        )
        observed = runtime.observe_document(case, ys)
        self.assertEqual(
            observed_calls,
            [("media-local-read", "media-read-fixture.png", 8)],
        )
        self.assertEqual(observed["snapshot"]["kind"], "image")
        self.assertEqual(observed["snapshot"]["bytes"], case["input"]["bytes"])
        self.assertEqual(
            observed["mappingValues"]["python"]["path"],
            "media-read-fixture.png",
        )

    def test_python_field_bounds_normalize_only_matching_validation_errors(self):
        from pydantic import BaseModel, Field, ValidationError

        class LimitInput(BaseModel):
            max_bytes: int = Field(le=MAX_FILE_BYTES)

        class SourceInput(BaseModel):
            source: str = Field(max_length=MAX_SOURCE_BYTES)

        with self.assertRaises(ValidationError) as limit:
            LimitInput(max_bytes=MAX_FILE_BYTES + 1)
        normalized_limit = runtime._validation_error(
            "hard-limit",
            limit.exception,
            {"configured": MAX_FILE_BYTES + 1},
        )
        self.assertEqual(normalized_limit["variant"], "LimitExceedsHardMaximum")

        with self.assertRaises(ValidationError) as source:
            SourceInput(source="s" * (MAX_SOURCE_BYTES + 1))
        normalized_source = runtime._validation_error(
            "source-over-limit",
            source.exception,
            {"source_length": MAX_SOURCE_BYTES + 1},
        )
        self.assertEqual(normalized_source["variant"], "MetadataTooLong")
        self.assertIsNone(
            runtime._validation_error(
                "source-over-limit",
                source.exception,
                {"source_length": MAX_SOURCE_BYTES},
            )
        )


if __name__ == "__main__":
    unittest.main()
