"""Execute image fixtures through the installed SDK's public Python objects."""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from image_surface_conformance import comparison, rgba_png
from media_documents_conformance import _plain


def dump(value: Any) -> Any:
    return value.model_dump(mode="json")


def artifact(value: Any) -> dict[str, Any]:
    payload = value.bytes
    if value.info.media_type == "image/jpeg":
        from yosoi import surface as sf

        decoded = sf.ImageSurface.from_pixel_artifact(value)
        png = decoded.crop(decoded.root_reference).png
        width, height, pixels = rgba_png(png)
    else:
        width, height, pixels = rgba_png(payload)
    document = value.document
    return {
        "class": type(value).__name__,
        "info": dump(value.info),
        "bytes": list(payload),
        "document_id": str(document.id),
        "metadata": dump(document.metadata),
        "rgba": pixels,
        "width": width,
        "height": height,
    }


def reader(value: Any) -> dict[str, Any]:
    return {
        "class": type(value).__name__,
        "descriptor": dump(value.descriptor),
        "observation": dump(value.observation),
        "root": dump(value.root_reference),
        "source_artifact": artifact(value.source_artifact),
    }


def crop(value: Any) -> dict[str, Any]:
    return {
        "reference": dump(value.reference),
        "rect": dump(value.rect),
        "artifact": artifact(value.artifact),
        "png": list(value.png),
    }


async def archive_observation(
    ys: Any, sf: Any, surface: Any, direct: Any, cropped: Any, tile_side: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Restore typed pixels and an exported Outcome in an empty second Archive."""
    with TemporaryDirectory(prefix="yosoi-image-parity-") as directory:
        root = Path(directory)
        archive = await ys.Archive.open(root / "original")
        reference = await cropped.write_to(archive)
        restored = await sf.PixelArtifact.read_from(archive, reference)
        # Exercise generic dispatch in addition to the typed convenience calls.
        generic_reference = await archive.write(cropped)
        generic_restored = await archive.read(generic_reference)
        if type(generic_restored) is not type(restored) or artifact(
            generic_restored
        ) != artifact(restored):
            raise ValueError("generic Archive dispatch changed the pixel artifact")
        source = sf.ArchivedSource.from_pixel_artifact(
            "root", direct, tile_side=tile_side, surface=surface
        )
        derived = sf.ArchivedSource.from_pixel_artifact(
            "crop", cropped, tile_side=tile_side
        )
        outcome = (
            sf.Outcome.new("image-parity-outcome")
            .with_source(source)
            .with_source(derived)
        )
        outcome.validate_outcome()
        outcome_ref = await archive.write(outcome)
        portable = root / "image.yosoi"
        await archive.export_file(outcome_ref, portable)
        fresh = await ys.Archive.open(root / "fresh")
        imported = await fresh.import_file(portable)
        loaded = await fresh.read(imported)
        loaded.validate_outcome()
        observed = {
            "artifact_class": type(restored).__name__,
            "restored": artifact(restored),
            "outcome_class": type(loaded).__name__,
            "record_id": str(loaded.record.id),
            "root": artifact(loaded.source_pixel_artifact("root", 8 * 1024 * 1024)),
            "crop": artifact(loaded.source_pixel_artifact("crop", 8 * 1024 * 1024)),
            "restored_surface_identity": loaded.surface("root").identity,
            "source_count": len(loaded.sources),
            "complete": loaded.complete,
            "sealed": loaded.sealed,
        }
        arguments = {
            "archive": (root / "original").name,
            "reference": dump(reference),
            "artifact": dump(cropped.info),
            "tile_side": tile_side,
        }
        return observed, arguments


def observe_fixtures(fixtures: dict[str, Any], ys: Any) -> list[dict[str, Any]]:
    """Invoke every operation explicitly; unknown fixture names fail closed."""
    sf = ys.surface
    inputs = fixtures["input"]
    document = ys.ImageDocument.from_bytes(inputs["id"], bytes(inputs["bytes"]))
    limits = sf.Limits.model_validate(inputs["limits"])
    pixel_limits = sf.PixelLimits.model_validate(inputs["pixel_limits"])
    tile_side = inputs["tile_side"]
    surface = sf.ImageSurface(
        document, tile_side=tile_side, limits=limits, pixel_limits=pixel_limits
    )
    root = surface.root_reference
    direct = sf.PixelArtifact.from_image_document(document, limits=pixel_limits)
    rect = sf.PixelRect(x=0, y=0, width=4, height=2)
    overview = surface.overview_image(4)
    cropped = surface.crop_rect(rect)
    native = surface.native_reference(root)
    other = sf.ImageSurface(
        ys.ImageDocument.from_bytes("other-image", document.bytes),
        tile_side=tile_side,
        limits=limits,
        pixel_limits=pixel_limits,
    )
    jpeg_input = inputs["jpeg"]
    jpeg = ys.ImageDocument.from_bytes(jpeg_input["id"], bytes(jpeg_input["bytes"]))
    jpeg_surface = sf.ImageSurface(
        jpeg, tile_side=tile_side, limits=limits, pixel_limits=pixel_limits
    )
    comparisons = []
    for case in fixtures["cases"]:
        name, args = case["name"], case["input"]
        receiver = {"self": dump(root)}
        if name == "jpeg-decode-direct":
            observed = artifact(
                sf.PixelArtifact.from_image_document(jpeg, limits=pixel_limits)
            )
            arguments = {"document": str(jpeg.id), "limits": dump(pixel_limits)}
        elif name == "jpeg-reader":
            observed = reader(jpeg_surface)
            arguments = {
                "document": str(jpeg.id),
                "tile_side": tile_side,
                "limits": dump(limits),
                "pixel_limits": dump(pixel_limits),
            }
        elif name == "jpeg-direct":
            observed = artifact(jpeg_surface.direct_image())
            arguments = {"self": dump(jpeg_surface.root_reference)}
        elif name == "jpeg-overview":
            observed = artifact(jpeg_surface.overview_image(args["max_side"]))
            arguments = {
                "self": dump(jpeg_surface.root_reference),
                "max_side": args["max_side"],
            }
        elif name == "jpeg-crop":
            selected = sf.PixelRect.model_validate(args["rect"])
            observed = crop(jpeg_surface.crop_rect(selected))
            arguments = {
                "self": dump(jpeg_surface.root_reference),
                "rect": dump(selected),
                "max_png_bytes": jpeg_surface.crop_rect.__defaults__[0],
            }
        elif name == "decode-direct":
            observed = artifact(direct)
            arguments = {"document": str(document.id), "limits": dump(pixel_limits)}
        elif name == "image-reader":
            observed = reader(surface)
            arguments = {
                "document": str(document.id),
                "tile_side": tile_side,
                "limits": dump(limits),
                "pixel_limits": dump(pixel_limits),
            }
        elif name == "direct":
            observed, arguments = artifact(surface.direct_image()), receiver
        elif name in {"overview", "overview-fits"}:
            max_side = args["max_side"]
            observed = artifact(surface.overview_image(max_side))
            arguments = {**receiver, "max_side": max_side}
        elif name == "resize":
            width, height = args["width"], args["height"]
            observed = artifact(surface.resize_image(width, height))
            arguments = {**receiver, "width": width, "height": height}
        elif name == "crop-rect":
            selected = sf.PixelRect.model_validate(args["rect"])
            # Omit the keyword to observe the installed public default.
            observed = crop(surface.crop_rect(selected))
            arguments = {
                **receiver,
                "rect": dump(selected),
                "max_png_bytes": surface.crop_rect.__defaults__[0],
            }
        elif name == "crop-reference":
            observed = crop(surface.crop(root))
            arguments = {
                **receiver,
                "reference": dump(root),
                "max_png_bytes": surface.crop.__defaults__[0],
            }
        elif name == "coordinate-map":
            selected = sf.PixelRect.model_validate(args["rect"])
            observed = dump(overview.map_rect_to_source(selected))
            arguments = {"self": dump(overview.info), "rect": dump(selected)}
        elif name == "native-reference":
            observed = dump(surface.native_reference(root))
            arguments = {**receiver, "reference": dump(root)}
        elif name == "shared-reference":
            observed = dump(surface.reference(native))
            arguments = {**receiver, "reference": dump(native)}
        elif name == "root-artifact":
            opened = sf.ImageSurface.from_pixel_artifact(
                direct, tile_side=tile_side, limits=limits, pixel_limits=pixel_limits
            )
            observed = reader(opened)
            arguments = {
                "artifact": dump(direct.info),
                "tile_side": tile_side,
                "limits": dump(limits),
                "pixel_limits": dump(pixel_limits),
            }
        elif name.startswith("read-"):
            request = sf.ReadRequest.model_validate(args["request"])
            observed = dump(surface.read(request))
            arguments = {**receiver, "request": dump(request)}
        elif name in {"screenshot-root", "video-frame-root"}:
            envelope = sf.ArchivedSource.model_validate(args["source_envelope"])
            restored = envelope.restore_pixel_artifact()
            opened = sf.ImageSurface.from_pixel_artifact(
                restored, tile_side=tile_side, limits=limits, pixel_limits=pixel_limits
            )
            observed = {
                "reader": reader(opened),
                "direct": artifact(opened.direct_image()),
                "crop": artifact(opened.crop_rect(rect).artifact),
            }
            arguments = {
                "source_envelope": dump(envelope),
                "artifact": dump(restored.info),
                "tile_side": tile_side,
                "limits": dump(limits),
                "pixel_limits": dump(pixel_limits),
            }
        elif name == "archive-portable":
            observed, arguments = asyncio.run(
                archive_observation(
                    ys, sf, surface, direct, cropped.artifact, tile_side
                )
            )
        else:
            raise ValueError(f"unimplemented image observation: {name}")
        comparisons.append(comparison(case, observed, arguments))
    for case in fixtures["errorCases"]:
        args, name = case["input"], case["name"]
        # Each call is captured after selecting its concrete public receiver and inputs.
        if name == "foreign-reference":
            operation = partial(other.crop, root)
            arguments = {"reference": dump(root)}
        elif name in {"crop-outside", "crop-zero-budget", "crop-byte-bound"}:
            selected = sf.PixelRect.model_validate(args["rect"])
            arguments = {"rect": dump(selected)}
            if "max_png_bytes" in args:
                bound = args["max_png_bytes"]
                arguments["max_png_bytes"] = bound
                operation = partial(surface.crop_rect, selected, max_png_bytes=bound)
            else:
                operation = partial(surface.crop_rect, selected)
        elif name == "overview-zero":
            arguments = {"max_side": args["max_side"]}
            operation = partial(surface.overview_image, arguments["max_side"])
        elif name == "resize-zero":
            arguments = {"width": args["width"], "height": args["height"]}
            operation = partial(
                surface.resize_image, arguments["width"], arguments["height"]
            )
        elif name == "nested-root":
            arguments = {"artifact": dump(cropped.artifact.info)}
            operation = partial(
                sf.ImageSurface.from_pixel_artifact,
                cropped.artifact,
                tile_side=tile_side,
                limits=limits,
                pixel_limits=pixel_limits,
            )
        elif name == "map-outside":
            selected = sf.PixelRect.model_validate(args["rect"])
            arguments = {"rect": dump(selected)}
            operation = partial(overview.map_rect_to_source, selected)
        elif name == "search-unavailable":
            request = sf.ReadRequest.model_validate(args["request"])
            arguments = {"request": dump(request)}
            operation = partial(surface.read, request)
        elif name == "decode-byte-bound":
            bound = sf.PixelLimits.model_validate(args["limits"])
            arguments = {"limits": dump(bound)}
            operation = partial(
                sf.PixelArtifact.from_image_document, document, limits=bound
            )
        else:
            raise ValueError(f"unimplemented image failure: {name}")
        if name == "decode-byte-bound":
            arguments["document"] = str(document.id)
        elif name == "nested-root":
            arguments.update(
                tile_side=tile_side,
                limits=dump(limits),
                pixel_limits=dump(pixel_limits),
            )
        elif name == "map-outside":
            arguments["self"] = dump(overview.info)
        else:
            arguments["self"] = dump(
                other.root_reference if name == "foreign-reference" else root
            )
            if name in {"foreign-reference", "crop-outside"}:
                arguments["max_png_bytes"] = surface.crop.__defaults__[0]
        try:
            operation()
        except sf.SurfaceError as error:
            from yosoi.errors import rust_error_details

            details = rust_error_details(error)
            if details is None:
                raise ValueError(
                    f"image error has no structured Rust details: {name}"
                ) from error
            observed = {
                "rust_type": details.rust_type,
                "variant": details.variant,
                "details": _plain(details.details),
                "source_chain": list(details.source_chain),
            }
        else:
            observed = {"unexpected_success": True}
        comparisons.append(comparison(case, observed, arguments))
    return comparisons
