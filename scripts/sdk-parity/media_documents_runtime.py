"""Runtime observation and comparison helpers for media SDK parity."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from media_documents_conformance import (
    ERROR_PATH,
    ERROR_VARIANTS,
    FILE_DOCUMENT_FIELDS,
    FILE_DOCUMENT_PATH,
    FILE_FACTORY_PATH,
    FILE_LIMITS_PATH,
    FILE_METADATA_BUILDER_FIELDS,
    FILE_METADATA_FIELDS,
    FILE_METADATA_PATH,
    FILE_READ_PATH,
    KIND_VARIANTS,
    MAX_FILE_BYTES,
    MAX_SOURCE_BYTES,
    _plain,
)

import parity


def _sha(value: Any) -> str:
    return parity.digest_json(value)


def _python_snapshot(document: Any) -> dict[str, Any]:
    metadata = _plain(document.metadata.model_dump())
    metadata["probe_validated_video_container"] = (
        document.metadata.probe_validated_video_container
    )
    return {
        "kind": type(document).__name__.removesuffix("Document").lower(),
        "id": str(document.id),
        "metadata": metadata,
        "bytes": list(document.bytes),
        "byte_len": document.byte_len,
        "sha256": document.sha256,
    }


def observe_document(case: dict[str, Any], ys: Any) -> dict[str, Any]:
    input_value = case["input"]
    metadata = ys.FileMetadata(**input_value["metadata"])
    limits = (
        ys.FileLimits(**input_value["limits"])
        if input_value.get("limits") is not None
        else ys.FileLimits()
    )
    payload = bytes(input_value["bytes"])
    name = case["name"]
    python_arguments: dict[str, Any]
    if name.startswith("typed-"):
        _, kind, constructor = name.split("-", 2)
        document_type = {
            "image": ys.ImageDocument,
            "video": ys.VideoDocument,
            "audio": ys.AudioDocument,
            "binary": ys.BinaryDocument,
        }[kind]
        kwargs: dict[str, Any] = {}
        python_arguments = {"id": input_value["id"], "content": list(payload)}
        if constructor == "from_bytes_with_limits":
            kwargs["limits"] = limits
            python_arguments["limits"] = limits.model_dump()
        elif constructor == "from_bytes_with_metadata":
            kwargs["metadata"] = metadata
            kwargs["limits"] = limits
            python_arguments["metadata"] = _plain(metadata.model_dump())
            python_arguments["limits"] = limits.model_dump()
        document = document_type.from_bytes(input_value["id"], payload, **kwargs)
        evidence_path = f"yosoi::documents::{document_type.__name__}::{constructor}"
        evidence_paths = [
            evidence_path,
            f"yosoi::documents::{document_type.__name__}",
        ]
    elif name == "factory-defaults":
        document = ys.file_from_bytes(input_value["id"], payload)
        python_arguments = {
            "id": input_value["id"],
            "content": list(payload),
            "metadata": _plain(metadata.model_dump()),
            "limits": limits.model_dump(),
        }
        evidence_paths = [FILE_FACTORY_PATH]
    elif name == "local-read":
        filename = input_value["filename"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / filename
            path.write_bytes(payload)
            document = asyncio.run(
                ys.read_file(
                    input_value["id"],
                    path,
                    limits=limits,
                )
            )
        python_arguments = {
            "id": input_value["id"],
            "path": filename,
            "limits": limits.model_dump(),
        }
        evidence_paths = [FILE_READ_PATH]
    else:
        document = ys.file_from_bytes(
            input_value["id"],
            payload,
            metadata=metadata,
            limits=limits,
        )
        python_arguments = {
            "id": input_value["id"],
            "content": list(payload),
            "metadata": _plain(metadata.model_dump()),
            "limits": limits.model_dump(),
        }
        evidence_paths = [FILE_FACTORY_PATH]
    rust_arguments = input_value["rust_arguments"]
    mapping_values = {"rust": rust_arguments, "python": python_arguments}
    return {
        "snapshot": _python_snapshot(document),
        "mappingValues": mapping_values,
        "evidenceRustPaths": evidence_paths,
    }


def _native_error(error: BaseException) -> dict[str, Any] | None:
    from yosoi.errors import rust_error_details

    details = rust_error_details(error)
    if details is None:
        return None
    return {
        "rust_type": details.rust_type,
        "variant": details.variant,
        "details": _plain(details.details),
        "source_chain": list(details.source_chain),
    }


def _validation_error(
    name: str, error: BaseException, input_value: dict[str, Any]
) -> dict[str, Any] | None:
    from pydantic import ValidationError

    if not isinstance(error, ValidationError):
        return None
    entries = error.errors(include_url=False)
    if len(entries) != 1:
        return None
    entry = entries[0]
    context = entry.get("ctx") or {}
    if name == "hard-limit":
        expected = (
            entry.get("loc") == ("max_bytes",)
            and entry.get("type") == "less_than_equal"
            and context.get("le") == MAX_FILE_BYTES
        )
        details = {
            "configured": input_value["configured"],
            "maximum": MAX_FILE_BYTES,
        }
        variant = "LimitExceedsHardMaximum"
    elif name == "source-over-limit":
        source_length = input_value["source_length"]
        expected = (
            entry.get("loc") == ("source",)
            and entry.get("type") == "string_too_long"
            and context.get("max_length") == MAX_SOURCE_BYTES
            and source_length == MAX_SOURCE_BYTES + 1
        )
        details = {
            "field": "source",
            "maximum": MAX_SOURCE_BYTES,
            "observed": source_length,
        }
        variant = "MetadataTooLong"
    else:
        return None
    if not expected:
        return None
    return {
        "rust_type": "yosoi::documents::FileDocumentError",
        "variant": variant,
        "details": details,
        "source_chain": [],
    }


def observe_error(
    case: dict[str, Any], ys: Any
) -> tuple[dict[str, Any] | None, str | None]:
    from yosoi.errors import FileDocumentError

    input_value = case["input"]
    name = case["name"]
    expected_exception: type[BaseException]
    if name == "typed-mismatch":
        expected_exception = FileDocumentError

        def operation():
            return ys.ImageDocument.from_bytes(
                input_value["id"], bytes(input_value["bytes"])
            )
    elif name == "payload-too-large":
        expected_exception = FileDocumentError

        def operation():
            return ys.file_from_bytes(
                input_value["id"],
                bytes(input_value["bytes"]),
                limits=ys.FileLimits(max_bytes=input_value["max_bytes"]),
            )
    elif name == "hard-limit":
        from pydantic import ValidationError

        expected_exception = ValidationError

        def operation():
            return ys.FileLimits(max_bytes=input_value["configured"])
    elif name == "source-over-limit":
        from pydantic import ValidationError

        expected_exception = ValidationError

        def operation():
            return ys.FileMetadata(source="s" * input_value["source_length"])
    else:
        raise ValueError(f"unsupported media error fixture: {name}")

    try:
        operation()
    except Exception as error:
        normalized = _native_error(error)
        if normalized is None:
            normalized = _validation_error(name, error, input_value)
        return normalized, (
            f"{type(error).__module__}.{type(error).__qualname__}"
            if isinstance(error, expected_exception)
            else None
        )
    return None, None


def _comparisons(
    name: str, rust: dict[str, Any], python: dict[str, Any]
) -> list[dict[str, Any]]:
    fields = {
        "document": ("kind", "id", "metadata", "bytes", "byte_len", "sha256"),
        "error": ("rust_type", "variant", "details", "source_chain"),
    }.get(name, ())
    return [
        {
            "name": f"{name}:{field}",
            "rustSha256": _sha(rust[field]),
            "pythonSha256": _sha(python[field]),
            "equal": rust[field] == python[field],
        }
        for field in fields
    ]


def compare_document_case(
    case: dict[str, Any], observed: dict[str, Any], module: Any
) -> dict[str, Any]:
    rust = case["rust"]
    python = observed["snapshot"]
    comparisons = _comparisons("document", rust, python)
    kind = rust["kind"]
    concrete_type = {
        "image": "ImageDocument",
        "video": "VideoDocument",
        "audio": "AudioDocument",
        "binary": "BinaryDocument",
    }[kind]
    evidence_paths = [
        *observed["evidenceRustPaths"],
        f"{FILE_DOCUMENT_PATH}::{KIND_VARIANTS[kind]}",
        f"yosoi::documents::{concrete_type}",
        FILE_DOCUMENT_PATH,
        FILE_METADATA_PATH,
        FILE_LIMITS_PATH,
        *(f"{FILE_DOCUMENT_PATH}::{member}" for member in FILE_DOCUMENT_FIELDS),
        *(
            f"yosoi::documents::{concrete_type}::{member}"
            for member in FILE_DOCUMENT_FIELDS
        ),
        *(f"{FILE_METADATA_PATH}::{member}" for member in FILE_METADATA_FIELDS),
    ]
    mapping_values_by_path = {
        path: observed["mappingValues"]
        for path in observed["evidenceRustPaths"]
        if path in {FILE_FACTORY_PATH, FILE_READ_PATH} or "::from_bytes" in path
    }
    rust_metadata = rust["metadata"]
    python_metadata = python["metadata"]
    for field in FILE_METADATA_FIELDS:
        mapping_values_by_path[f"{FILE_METADATA_PATH}::{field}"] = {
            "rust": {field: rust_metadata[field]},
            "python": {field: python_metadata[field]},
        }
    metadata_input = case["input"]["metadata"]
    if metadata_input.get("filename") is not None:
        for builder, field in FILE_METADATA_BUILDER_FIELDS.items():
            value = metadata_input.get(field)
            if value is None:
                continue
            path = f"{FILE_METADATA_PATH}::{builder}"
            evidence_paths.append(path)
            mapping_values_by_path[path] = {
                "rust": {"value": value},
                "python": {field: value},
                "defaults": {"python-default:value": (None, None)},
            }
    return {
        "name": case["name"],
        "rustPath": f"{FILE_DOCUMENT_PATH}::{KIND_VARIANTS[kind]}",
        "evidenceRustPaths": list(dict.fromkeys(evidence_paths)),
        "mappingValuesByPath": mapping_values_by_path,
        "rust": rust,
        "python": python,
        "comparisons": comparisons,
        "equal": all(item["equal"] for item in comparisons),
        "rustSha256": module.digest_json(rust),
        "pythonSha256": module.digest_json(python),
    }


def compare_error_case(
    case: dict[str, Any], observed: dict[str, Any] | None, exception_type: str | None
) -> dict[str, Any]:
    rust = case["rust"]
    python = observed or {}
    comparisons = _comparisons("error", rust, python) if observed is not None else []
    equal = (
        observed == rust
        and exception_type is not None
        and bool(comparisons)
        and all(item["equal"] for item in comparisons)
    )
    return {
        "name": case["name"],
        "rustPath": f"{ERROR_PATH}::{ERROR_VARIANTS[case['name']]}",
        "evidenceRustPaths": [
            ERROR_PATH,
            f"{ERROR_PATH}::{ERROR_VARIANTS[case['name']]}",
        ],
        "rust": rust,
        "python": observed,
        "pythonExceptionType": exception_type,
        "comparisons": comparisons,
        "equal": equal,
        "rustSha256": parity.digest_json(rust),
        "pythonSha256": parity.digest_json(python) if observed is not None else None,
    }
