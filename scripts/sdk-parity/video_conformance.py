"""Fail-closed actual video fixture validation and compiler-pinned attribution."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from image_surface_conformance import EVIDENCE_KIND as EVIDENCE_KIND
from image_surface_conformance import RESULT_KIND as RESULT_KIND
from image_surface_conformance import comparison as _comparison
from image_surface_conformance import evidence_cases as _evidence
from image_surface_conformance import rgba_png

FIXTURE_KIND = "yosoi-video-conformance-fixtures"
CASE_PATHS = {
    "open": "yosoi::VideoSurface::open",
    "from-document": "yosoi::VideoSurface::from_document",
    "overview": "yosoi::VideoSurface::read",
    "expand": "yosoi::VideoSurface::read",
    **dict.fromkeys(
        ("frame-zero", "frame-next", "frame-half"), "yosoi::VideoSurface::frame"
    ),
    "crop": "yosoi::VideoSurface::crop",
    "archive-frame": "yosoi::DecodedFrame::read_from",
    "archive-video": "yosoi::VideoSurface::read_from",
}
ERROR_PATHS = {
    "cancelled-frame": ("yosoi::VideoSurface::frame_cancellable", "Cancelled"),
    "foreign-reference": ("yosoi::VideoSurface::frame", "Surface"),
    "nested-crop": ("yosoi::VideoSurface::crop", "Invalid"),
    "crop-outside": ("yosoi::VideoSurface::crop", "Invalid"),
    "tail-no-frame": ("yosoi::VideoSurface::frame", "NoFrameAtOrAfter"),
    "at-end": ("yosoi::VideoSurface::at", "Invalid"),
}


def validate_frame(value: Any) -> None:
    """Require actual PNG pixels, measured timestamps and exact pixel provenance."""
    if not isinstance(value, dict) or value.get("class") != "DecodedFrame":
        raise ValueError("video fixture lacks a DecodedFrame")
    raw = value.get("png")
    if not isinstance(raw, list) or any(
        type(byte) is not int or not 0 <= byte <= 255 for byte in raw
    ):
        raise ValueError("video fixture lacks actual PNG octets")
    width, height, rgba = rgba_png(bytes(raw))
    info, artifact = value.get("info", {}), value.get("pixel_artifact", {})
    if (
        (info.get("width"), info.get("height")) != (width, height)
        or value.get("rgba") != rgba
        or info.get("png_bytes") != len(raw)
        or info.get("png_sha256") != hashlib.sha256(bytes(raw)).hexdigest()
    ):
        raise ValueError("video fixture PNG/digest/pixels disagree with frame metadata")
    if (
        not isinstance(artifact, dict)
        or artifact.get("bytes") != raw
        or artifact.get("info") != info.get("pixel_artifact")
    ):
        raise ValueError("video frame lost its checked shared pixel provenance")
    if (
        artifact["info"].get("sha256") != info["png_sha256"]
        or artifact["info"].get("source", {}).get("kind") != "video_frame"
    ):
        raise ValueError("video frame artifact must retain the typed video source")
    if info.get("position_us") is None or info["position_us"] < info.get(
        "requested_us", 0
    ):
        raise ValueError("video fixture selected a frame before the requested time")


def validate_storage_reference(
    name: str, arguments: dict[str, Any], selected: Any
) -> None:
    """Validate opaque typed selectors and the exact value actually read back."""
    kind = "FrameArchiveRef" if name == "archive-frame" else "VideoArchiveRef"
    descriptor, raw = (
        arguments.get("reference"),
        arguments.get("observed_storage_reference"),
    )
    required = (
        {"document"} if kind == "FrameArchiveRef" else {"document", "observation"}
    )
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError(
            "video Archive selector does not have its typed reference shape"
        )
    document = raw.get("document")
    if not isinstance(document, str) or not document.startswith("document:v1:"):
        raise ValueError("video Archive selector is not a document reference")
    identifier = document.removeprefix("document:v1:")
    if str(uuid.UUID(identifier)) != identifier:
        raise ValueError("video Archive selector UUID is noncanonical")
    if descriptor != {"kind": kind, "selected_value": selected}:
        raise ValueError(
            "video Archive selector does not identify the actual selected value"
        )
    if kind == "VideoArchiveRef" and raw["observation"] != selected.get(
        "observation", {}
    ).get("id"):
        raise ValueError("video Archive selector lost its exact observation")


def validate_fixture_set(value: Any) -> dict[str, Any]:
    """Reject missing journeys, metadata-only frames, or hidden audio claims."""
    if (
        not isinstance(value, dict)
        or type(value.get("schemaVersion")) is not int
        or value.get("schemaVersion") != 1
        or value.get("kind") != FIXTURE_KIND
    ):
        raise ValueError("unsupported Rust video fixture output")
    for field, names in (("cases", CASE_PATHS), ("errorCases", ERROR_PATHS)):
        rows = value.get(field)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid video fixture cases")
        actual = [row.get("name") for row in rows]
        if len(actual) != len(set(actual)) or set(actual) != set(names):
            raise ValueError("video fixture names differ from the contract")
        for row in rows:
            expected = names[row["name"]] if field == "cases" else names[row["name"]][0]
            if (
                row.get("rustPath") != expected
                or not isinstance(row.get("input"), dict)
                or not isinstance(row.get("rust"), dict)
            ):
                raise ValueError("video fixture does not address its executed API")
            if row["name"] in {"archive-frame", "archive-video"}:
                validate_storage_reference(row["name"], row["input"], row["rust"])
            if field == "errorCases" and (
                row["rust"].get("rust_type") != "yosoi::surface::video::VideoError"
                or row["rust"].get("variant") != names[row["name"]][1]
                or not isinstance(row["rust"].get("details"), dict)
                or not isinstance(row["rust"].get("source_chain"), list)
            ):
                raise ValueError("video rejection lacks exact typed Rust error details")
    cases = {row["name"]: row["rust"] for row in value["cases"]}
    opened = cases["open"]
    if (
        opened.get("metadata", {}).get("audio_streams") != 1
        or opened.get("descriptor", {}).get("controllable") is not False
        or opened.get("observation", {}).get("coverage", {}).get("complete")
        is not False
    ):
        raise ValueError(
            "fixture must contain audio without claiming complete/control evidence"
        )
    reason = opened["observation"]["coverage"].get("reason", "")
    if "audio, OCR and transcription are not observed" not in reason or {
        cap.get("id") for cap in opened["descriptor"].get("capabilities", [])
    } != {
        f"video.{name}@1" for name in ("overview", "inspect", "expand", "frame", "crop")
    }:
        raise ValueError("video capabilities must explicitly exclude audio observation")
    if any(
        cap.get("access") != "read" or cap.get("control_domain") is not None
        for cap in opened["descriptor"]["capabilities"]
    ):
        raise ValueError("video fixture must not grant source control")
    for name in ("frame-zero", "frame-next", "frame-half", "crop", "archive-frame"):
        validate_frame(cases[name])
    for name, requested, measured in (
        ("frame-zero", 0, 0),
        ("frame-next", 125000, 250000),
        ("frame-half", 500000, 500000),
    ):
        if (
            cases[name]["info"]["requested_us"] != requested
            or cases[name]["info"]["position_us"] != measured
        ):
            raise ValueError(
                "synthetic clip must preserve requested and measured frame time"
            )
    return value


def comparison(
    case: dict[str, Any], observed: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    if case["name"] in {"archive-frame", "archive-video"}:
        validate_storage_reference(case["name"], case["input"], case["rust"])
        validate_storage_reference(case["name"], arguments, observed)
    row = _comparison(case, observed, arguments)
    for check in row["comparisons"]:
        check["name"] = check["name"].replace("image:", "video:", 1)
    return row


def evidence_cases(
    rows: list[dict[str, Any]], rust: dict[str, Any], ledger: dict[str, Any]
) -> list[dict[str, Any]]:
    result = _evidence(rows, rust, ledger)
    for row in result:
        row["testId"] = row["testId"].replace("image-surface:", "video:", 1)
    return result
