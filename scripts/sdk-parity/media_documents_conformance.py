"""Shared media-document fixture contract for the parity runner and tests."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import parity

FIXTURE_KIND = "yosoi-media-documents-conformance-fixtures"
RESULT_KIND = "yosoi-python-rust-conformance-results"
EVIDENCE_KIND = "yosoi-python-rust-conformance"
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_SOURCE_BYTES = 1_048_576
EXPECTED_CASES = {
    "png": ("image", "image/"),
    "jpeg": ("image", "image/"),
    "mp4": ("video", "video/"),
    "mp3": ("audio", "audio/"),
    "wav": ("audio", "audio/"),
    "opaque": ("binary", None),
    "empty": ("binary", None),
    "source-over-4k": ("binary", None),
    "factory-defaults": ("binary", None),
    "local-read": ("image", "image/"),
}
for _kind, _media_prefix in (
    ("image", "image/"),
    ("video", "video/"),
    ("audio", "audio/"),
    ("binary", None),
):
    for _constructor in (
        "from_bytes",
        "from_bytes_with_limits",
        "from_bytes_with_metadata",
    ):
        EXPECTED_CASES[f"typed-{_kind}-{_constructor}"] = (_kind, _media_prefix)
EXPECTED_ERRORS = {
    "typed-mismatch": "TypeMismatch",
    "payload-too-large": "TooLarge",
    "hard-limit": "LimitExceedsHardMaximum",
    "source-over-limit": "MetadataTooLong",
}
KIND_VARIANTS = {
    "image": "Image",
    "video": "Video",
    "audio": "Audio",
    "binary": "Binary",
}
ERROR_VARIANTS = dict(EXPECTED_ERRORS)
FILE_DOCUMENT_PATH = "yosoi::documents::FileDocument"
FILE_METADATA_PATH = "yosoi::documents::FileMetadata"
FILE_FACTORY_PATH = "yosoi::documents::file_from_bytes"
FILE_READ_PATH = "yosoi::documents::read_file"
FILE_LIMITS_PATH = "yosoi::documents::FileLimits"
ERROR_PATH = "yosoi::documents::FileDocumentError"
DEFAULT_FILE_MAX_BYTES = 64 * 1024 * 1024
FILE_METADATA_BUILDER_FIELDS = {
    "with_filename": "filename",
    "with_declared_media_type": "declared_media_type",
    "with_source": "source",
    "with_capture_id": "capture_id",
    "with_session_id": "session_id",
    "with_tab_id": "tab_id",
    "with_download_id": "download_id",
}
FILE_METADATA_FIELDS = (
    "filename",
    "declared_media_type",
    "detected_media_type",
    "source",
    "capture_id",
    "session_id",
    "tab_id",
    "download_id",
    "sha256",
)
FILE_DOCUMENT_FIELDS = ("id", "metadata", "bytes", "byte_len", "sha256")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def validate_fixture_set(
    value: Any,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or value.get("kind") != FIXTURE_KIND
        or not isinstance(value.get("cases"), list)
        or not isinstance(value.get("errorCases"), list)
    ):
        raise ValueError("unsupported Rust media-document fixture output")

    cases = value["cases"]
    names = [item.get("name") for item in cases if isinstance(item, dict)]
    if len(names) != len(cases) or len(names) != len(set(names)):
        raise ValueError("Rust media fixtures have missing or duplicate names")
    if set(names) != set(EXPECTED_CASES):
        raise ValueError("Rust media fixture names differ from the contract")
    required_snapshot = {"kind", "id", "metadata", "bytes", "byte_len", "sha256"}
    for item in cases:
        if not {"name", "input", "rust"}.issubset(item):
            raise ValueError(f"incomplete Rust media fixture: {item.get('name')}")
        input_value = item["input"]
        rust = item["rust"]
        if (
            not isinstance(input_value, dict)
            or not isinstance(input_value.get("bytes"), list)
            or any(
                isinstance(byte, bool)
                or not isinstance(byte, int)
                or not 0 <= byte <= 255
                for byte in input_value["bytes"]
            )
            or not isinstance(input_value.get("metadata"), dict)
            or not isinstance(input_value.get("rust_arguments"), dict)
            or not isinstance(rust, dict)
            or not required_snapshot.issubset(rust)
        ):
            raise ValueError(f"invalid Rust media fixture values: {item['name']}")
        kind, media_prefix = EXPECTED_CASES[item["name"]]
        digest = hashlib.sha256(bytes(input_value["bytes"])).hexdigest()
        metadata = rust["metadata"]
        if (
            rust["kind"] != kind
            or rust["id"] != input_value.get("id")
            or rust["bytes"] != input_value["bytes"]
            or rust["byte_len"] != len(input_value["bytes"])
            or rust["sha256"] != digest
            or not isinstance(metadata, dict)
            or metadata.get("sha256") != digest
            or any(
                metadata.get(key) != field
                for key, field in input_value["metadata"].items()
                if key not in {"detected_media_type", "sha256"}
            )
        ):
            raise ValueError(
                f"Rust media fixture failed its value contract: {item['name']}"
            )
        detected = metadata.get("detected_media_type")
        if media_prefix is None:
            if detected is not None:
                raise ValueError(
                    f"opaque fixture unexpectedly detected as media: {item['name']}"
                )
        elif not isinstance(detected, str) or not detected.startswith(media_prefix):
            raise ValueError(
                f"signature fixture detected the wrong media family: {item['name']}"
            )
        if (
            item["name"] == "source-over-4k"
            and len(input_value["metadata"].get("source", "").encode("utf-8")) <= 4_096
        ):
            raise ValueError("long-source fixture does not exceed 4 KiB")

    error_cases = value["errorCases"]
    error_names = [item.get("name") for item in error_cases if isinstance(item, dict)]
    if (
        len(error_names) != len(error_cases)
        or len(error_names) != len(set(error_names))
        or set(error_names) != set(EXPECTED_ERRORS)
    ):
        raise ValueError("Rust media error fixtures differ from the contract")
    for item in error_cases:
        if not {"name", "operation", "input", "rust"}.issubset(item):
            raise ValueError(f"incomplete Rust media error fixture: {item.get('name')}")
        error = item["rust"]
        if (
            not isinstance(error, dict)
            or error.get("rust_type") != "yosoi::documents::FileDocumentError"
            or error.get("variant") != EXPECTED_ERRORS[item["name"]]
            or not isinstance(error.get("details"), dict)
            or not isinstance(error.get("source_chain"), list)
        ):
            raise ValueError(f"Rust media error fixture failed: {item['name']}")
        details = error["details"]
        input_value = item["input"]
        if item["name"] == "typed-mismatch" and details != {
            "expected": "image",
            "detected": None,
        }:
            raise ValueError("typed mismatch fixture differs from the error contract")
        if item["name"] == "payload-too-large" and details != {
            "maximum": input_value.get("max_bytes"),
            "observed": len(input_value.get("bytes", [])),
        }:
            raise ValueError("payload limit fixture differs from the error contract")
        if item["name"] == "hard-limit" and details != {
            "configured": input_value.get("configured"),
            "maximum": MAX_FILE_BYTES,
        }:
            raise ValueError("hard limit fixture differs from the error contract")
        if item["name"] == "source-over-limit" and details != {
            "field": "source",
            "maximum": MAX_SOURCE_BYTES,
            "observed": input_value.get("source_length"),
        }:
            raise ValueError("source limit fixture differs from the error contract")

    standalone = value.get("standaloneMetadata")
    equality = value.get("equality")
    if not isinstance(standalone, dict) or set(standalone) != set(FILE_METADATA_FIELDS):
        raise ValueError("standalone Rust metadata fields differ from the contract")
    if any(value is not None for value in standalone.values()):
        raise ValueError("standalone Rust metadata must contain only empty fields")
    if equality != {
        "same_value_different_handles_and_limits": True,
        "different_identity": False,
    }:
        raise ValueError("Rust media equality fixtures differ from the contract")
    file_limits = value.get("fileLimits")
    if file_limits != {
        "defaultMaxBytes": DEFAULT_FILE_MAX_BYTES,
        "hardMaxBytes": MAX_FILE_BYTES,
        "sourceMaxBytes": MAX_SOURCE_BYTES,
    }:
        raise ValueError("Rust file-size constants differ from the contract")
    return cases, error_cases, standalone, equality, file_limits


def evidence_cases(
    comparisons: list[dict[str, Any]], rust: dict[str, Any], ledger: dict[str, Any]
) -> list[dict[str, Any]]:
    items = {item["rustPath"]: item for item in rust.get("items", [])}
    entries = {
        entry.get("symbolKey"): entry
        for entry in ledger.get("entries", [])
        if entry.get("decision") == "mapped" and entry.get("symbolKey")
    }
    cases = []
    for comparison in comparisons:
        path = comparison["rustPath"]
        item = items.get(path)
        entry = entries.get(item.get("symbolKey")) if item else None
        if item is None or entry is None or entry.get("rustPath") != path:
            raise ValueError(f"media conformance lacks a pinned mapping for {path}")
        if not comparison["comparisons"]:
            raise ValueError(f"media conformance case has no comparisons: {path}")
        evidence_paths = comparison.get("evidenceRustPaths", [path])
        for evidence_path in evidence_paths:
            evidence_item = items.get(evidence_path)
            evidence_entry = (
                entries.get(evidence_item.get("symbolKey")) if evidence_item else None
            )
            if (
                evidence_item is None
                or evidence_entry is None
                or evidence_entry.get("rustPath") != evidence_path
            ):
                raise ValueError(
                    f"media conformance lacks a pinned mapping for {evidence_path}"
                )
            mapping_values = comparison.get("mappingValuesByPath", {}).get(
                evidence_path
            )
            mapping_checks = _mapping_checks(evidence_entry, mapping_values)
            cases.append(
                {
                    "testId": (
                        f"media-documents:{comparison['name']}:"
                        f"{evidence_item['symbolKey']}"
                    ),
                    "rustPath": evidence_path,
                    "symbolKey": evidence_item["symbolKey"],
                    "pythonTarget": evidence_entry["pythonTarget"],
                    "outcome": "passed" if comparison["equal"] else "failed",
                    "comparisons": comparison["comparisons"],
                    "mappingChecks": mapping_checks,
                }
            )
    return cases


def _mapping_checks(
    entry: dict[str, Any], values: dict[str, Any] | None
) -> list[dict[str, Any]]:
    expected = [
        ("argument", item["rustArgument"], item["pythonArgument"])
        for item in entry.get("argumentMappings", [])
    ]
    if entry.get("receiverMapping"):
        receiver = entry["receiverMapping"]
        expected.append(
            ("receiver", receiver["rustArgument"], receiver["pythonArgument"])
        )
    expected.extend(("fixed", name, name) for name in entry.get("fixedArguments", {}))
    expected.extend(
        (kind, item["id"], item["id"])
        for kind, field in (
            ("default", "defaults"),
            ("unit", "units"),
            ("cardinality", "cardinality"),
        )
        for item in entry.get(field, [])
    )
    if not expected:
        return []
    if not isinstance(values, dict):
        raise ValueError(
            f"mapped media operation has no observed arguments: {entry['rustPath']}"
        )
    rust_values = values.get("rust") or {}
    python_values = values.get("python") or {}
    checks = []
    explicit_defaults = values.get("defaults") or {}
    for kind, rust_name, python_name in expected:
        if kind in {"default", "unit", "cardinality"}:
            check_key = rust_name
            if check_key in explicit_defaults:
                rust_value, python_value = explicit_defaults[check_key]
            else:
                rust_name = rust_name.rsplit(":", 1)[-1]
                python_name = rust_name
                if rust_name not in rust_values or python_name not in python_values:
                    raise ValueError(
                        f"media mapping check lacks {rust_name}/{python_name}: "
                        f"{entry['rustPath']}"
                    )
                rust_value = rust_values[rust_name]
                python_value = python_values[python_name]
        else:
            check_key = rust_name
            if rust_name not in rust_values or python_name not in python_values:
                raise ValueError(
                    f"media mapping check lacks {rust_name}/{python_name}: "
                    f"{entry['rustPath']}"
                )
            rust_value = rust_values[rust_name]
            python_value = python_values[python_name]
        checks.append(
            {
                "kind": kind,
                "key": check_key,
                "rustSha256": parity.digest_json(rust_value),
                "pythonSha256": parity.digest_json(python_value),
                "equal": rust_value == python_value,
            }
        )
    return checks
