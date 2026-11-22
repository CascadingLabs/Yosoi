"""Explicit video API mappings, with cancellation and provenance preserved.

This table creates no execution evidence, scope exceptions, or language-specific
reviews. A missing public Python target remains missing for owner investigation.
"""

from __future__ import annotations

from typing import Any

import sdk_contract
import seed_ledger

TYPE_TARGETS = {
    **{
        f"yosoi::{name}": f"yosoi.{name}"
        for name in (
            "VideoSurface",
            "DecodedFrame",
            "VideoSession",
            "VideoError",
            "VideoPolicy",
        )
    },
    **{
        f"yosoi::surface::video::{name}": f"yosoi.surface.{name}"
        for name in (
            "VideoMetadata",
            "FrameInfo",
            "VideoArchiveRef",
            "FrameArchiveRef",
        )
    },
}
METHOD_TARGETS = {
    "yosoi::VideoSurface::open_cancellable": "yosoi.VideoSurface.open",
    "yosoi::VideoSurface::from_document_cancellable": (
        "yosoi.VideoSurface.from_document"
    ),
    "yosoi::VideoSurface::frame_cancellable": "yosoi.VideoSurface.frame",
    "yosoi::VideoSurface::crop_cancellable": "yosoi.VideoSurface.crop",
    "yosoi::VideoSession::open_cancellable": "yosoi.VideoSession.open",
    "yosoi::VideoSession::execute_cancellable": "yosoi.VideoSession.execute",
    "yosoi::DecodedFrame::pixels": "yosoi.DecodedFrame.pixel_artifact",
    "yosoi::documents::FileMetadata::probe_validated_video_container": (
        "yosoi.documents.FileMetadata.probe_validated_video_container"
    ),
    "yosoi::documents::VideoDocument::copy_with_metadata": (
        "yosoi.documents.VideoDocument.copy_with_metadata"
    ),
}
ERROR_FIELDS = {
    "Cancelled": {},
    "Timeout": {},
    "Invalid": {"0": "details.message"},
    "Tool": {"0": "details.message"},
    "Limit": {"0": "details.limit"},
    "Io": {"0": "details.message"},
    "NoFrameAtOrAfter": {"requested_us": "details.requested_us"},
    "Surface": {"0": "details.surface"},
}


def _error_mapping(
    item: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any] | None:
    variant = item["rustPath"].rsplit("::", 1)[-1]
    fields = ERROR_FIELDS.get(variant)
    target = "yosoi.VideoError"
    if fields is None or target not in python["targets"]:
        return None
    return {
        "rustPath": item["rustPath"],
        "symbolKey": item["symbolKey"],
        "decision": "mapped",
        "pythonTarget": target,
        "mappingDirection": "output",
        "argumentMappings": [],
        "defaults": [],
        "units": [],
        "cardinality": [],
        "outputBinding": {
            "kind": "error-details",
            "schemaTarget": "yosoi.errors.RustErrorDetails",
            "discriminator": "variant",
            "tag": variant,
            "rustType": "yosoi::surface::video::VideoError",
            "pythonFields": [
                {
                    "rustArgument": name,
                    "pythonFieldPath": path,
                    "conversion": (
                        "The native video exception retains this Rust error "
                        "payload and available source chain."
                    ),
                }
                for name, path in fields.items()
            ],
        },
        "rationale": (
            "The native adapter raises VideoError with its exact Rust variant "
            "and structured details after owned decoder cleanup settles."
        ),
        "semanticEquivalent": (
            f"rust_error_details exposes VideoError::{variant}; cancellation "
            "and timeout remain distinct from missing-frame and invalid-evidence "
            "failures."
        ),
    }


def video_mapping(
    item: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any] | None:
    """Map a public video declaration only to a real Python API counterpart."""
    if sdk_contract._expected_classification(item) != "sdk":
        return None
    path = item["rustPath"]
    parent, _, leaf = path.rpartition("::")
    if parent == "yosoi::VideoError" and item["kind"] == "variant":
        return _error_mapping(item, python)
    target = METHOD_TARGETS.get(path) or TYPE_TARGETS.get(path)
    if target is None and parent in TYPE_TARGETS:
        target = f"{TYPE_TARGETS[parent]}.{leaf}"
    info = python["targets"].get(target) if target else None
    if info is None or target is None:
        return None
    entry = seed_ledger._entry(
        item,
        target,
        info,
        python,
        "Python exposes the same frozen video source, measured frame metadata "
        "and checked native pixel/Archive value without granting live control.",
    )
    if entry is None:
        return None
    if path.endswith("_cancellable"):
        entry["semanticEquivalent"] = (
            "Python unifies cancellable and default operations through the "
            "optional cancellation keyword. A supplied cooperative token "
            "propagates cancellation; cancelling one await signals only its "
            "child operation and waits for owned decoder cleanup."
        )
        for argument in entry["argumentMappings"]:
            if argument["rustArgument"] == "cancellation":
                argument["conversion"] = (
                    "Use the supplied CancellationToken through its native "
                    "operation child; preserve shared-parent propagation, "
                    "sibling isolation and awaited decoder reaping."
                )
    if path == "yosoi::DecodedFrame::pixels":
        entry["semanticEquivalent"] = (
            "Checked native frames expose their optional pixels through the "
            "pixel_artifact property. Legacy absence remains None; divergent "
            "PNG/provenance metadata raises VideoError instead of returning "
            "an inconsistent payload."
        )
    for argument in item.get("rustArguments", []):
        name = argument["name"]
        if name in {"position_us", "requested_us", "source_pts_us", "max_side", "rect"}:
            unit = (
                "stream-relative microseconds"
                if name.endswith("_us")
                else "decoded full-frame pixel coordinates"
            )
            entry["units"].append(
                {"id": f"video-unit:{name}", "rust": unit, "python": unit}
            )
    return entry
