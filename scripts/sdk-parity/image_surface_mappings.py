"""Explicit image mappings; absent public counterparts remain missing.

This table creates no execution evidence, scope exceptions or trait policies.
Every callable must resolve against live Python introspection.
"""

from __future__ import annotations

from typing import Any

import sdk_contract
import seed_ledger

ROOT_TYPES = {
    "ImageSession",
    "ImageSurface",
    "PixelArtifact",
    "PixelArtifactInfo",
    "PixelCoordinateKind",
    "PixelCoordinateSpace",
    "PixelEdgeTransform",
    "PixelLimits",
    "PixelOperation",
    "PixelOrientation",
    "PixelSource",
    "PixelTransform",
}
METHOD_TARGETS = {
    "yosoi::ImageSurface::from_image_document": "yosoi.ImageSurface",
    "yosoi::PixelArtifact::decode_image_document": (
        "yosoi.PixelArtifact.decode_image_document"
    ),
    "yosoi::PixelArtifact::validate": "yosoi.PixelArtifact.validate_artifact",
    "yosoi::PixelLimits::validate": "yosoi.PixelLimits.validate_limits",
    "yosoi::Surface::crop_image": "yosoi.Surface.crop_rect",
    "yosoi::Surface::from_image_document_with_pixel_limits": (
        "yosoi.Surface.from_image_document"
    ),
    "yosoi::Surface::from_image_with_pixel_limits": "yosoi.Surface.from_image",
    "yosoi::Surface::from_pixel_artifact_with_pixel_limits": (
        "yosoi.Surface.from_pixel_artifact"
    ),
    "yosoi::surface::ArchivedSource::new_file_document": (
        "yosoi.surface.ArchivedSource.from_file_document"
    ),
    "yosoi::surface::ArchivedSource::new_image": (
        "yosoi.surface.ArchivedSource.from_image"
    ),
    "yosoi::surface::ArchivedSource::new_pixel_artifact": (
        "yosoi.surface.ArchivedSource.from_pixel_artifact"
    ),
    "yosoi::surface::pixels::resize_transform": "yosoi.surface.resize_transform",
    "yosoi::surface::pixels": "yosoi.surface",
}
ARGUMENT_ALIASES = {
    ("yosoi::Surface::from_image_with_pixel_limits", "bytes"): "content",
}


def image_mapping(
    item: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any] | None:
    """Map an explicit source declaration to its actual public Python target."""
    if sdk_contract._expected_classification(item) != "sdk":
        return None
    path = item["rustPath"]
    target = METHOD_TARGETS.get(path)
    parent, _, leaf = path.rpartition("::")
    name = parent.removeprefix("yosoi::")
    if target is None and name in ROOT_TYPES:
        target = f"yosoi.{name}.{leaf}"
    if target is None and path.removeprefix("yosoi::") in ROOT_TYPES:
        target = f"yosoi.{path.removeprefix('yosoi::')}"
    if target is None and path.startswith("yosoi::surface::"):
        target = path.replace("::", ".")
    if (
        parent
        in {
            "yosoi::PixelSource",
            "yosoi::PixelOperation",
            "yosoi::PixelCoordinateKind",
            "yosoi::PixelOrientation",
        }
        and item["kind"] == "variant"
    ):
        target = parent.replace("::", ".")
    if path == "yosoi::surface::ArchivedFileKind" or parent == (
        "yosoi::surface::ArchivedFileKind"
    ):
        target = "yosoi.surface.ArchivedSource.file_kind"
    if parent == "yosoi::surface::SourceInterpretation" and item["kind"] == "variant":
        target = "yosoi.surface.SourceInterpretation"
    target_info = python["targets"].get(target) if target else None
    if target_info is None:
        return None
    entry = seed_ledger._entry(
        item,
        target,
        target_info,
        python,
        "Python retains the same typed pixels, coordinates and bounds through "
        "its public model or checked native operation.",
        argument_aliases=ARGUMENT_ALIASES,
    )
    if entry is None:
        return None
    if parent == "yosoi::surface::SourceInterpretation" and item["kind"] == "variant":
        entry["fixedArguments"] = {"kind": seed_ledger._snake_case(leaf)}
    if (
        parent
        in {
            "yosoi::PixelCoordinateKind",
            "yosoi::PixelOrientation",
            "yosoi::surface::ArchivedFileKind",
        }
        and item["kind"] == "variant"
    ):
        tag = seed_ledger._snake_case(leaf)
        entry["defaults"] = [
            {
                "id": "variant-tag:value",
                "rust": f"{leaf} serialized as {tag}",
                "python": f"Literal {tag}",
            }
        ]
    if path.startswith("yosoi::ImageSurface::") and any(
        arg.get("receiver") for arg in item.get("rustArguments", [])
    ):
        entry["receiverMapping"] = {
            "rustArgument": "self",
            "pythonArgument": "self",
            "conversion": "Operate on the same immutable image observation; "
            "references preserve its exact capture scope.",
        }
    for arg in item.get("rustArguments", []):
        arg_name = arg["name"]
        if arg_name in {
            "width",
            "height",
            "max_side",
            "tile_side",
            "rect",
            "max_png_bytes",
        }:
            unit = (
                "encoded bytes"
                if arg_name == "max_png_bytes"
                else "pixel edges or dimensions in the declared coordinate plane"
            )
            entry["units"].append(
                {
                    "id": f"image-unit:{arg_name}",
                    "rust": unit,
                    "python": unit,
                }
            )
    return entry
