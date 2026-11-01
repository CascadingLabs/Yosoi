"""Decode the exact shared fixture clip through public installed Python APIs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from image_surface_conformance import rgba_png
from media_documents_conformance import _plain
from video_conformance import comparison


def dump(value: Any) -> Any:
    return value.model_dump(mode="json")


def video(value: Any) -> dict[str, Any]:
    source = value.source_document
    document = (
        None
        if source is None
        else {
            "class": type(source).__name__,
            "id": str(source.id),
            "bytes": list(source.bytes),
            "metadata": {
                **dump(source.metadata),
                "probe_validated_video_container": (
                    source.metadata.probe_validated_video_container
                ),
            },
            "sha256": source.sha256,
            "byte_len": source.byte_len,
        }
    )
    return {
        "class": type(value).__name__,
        "descriptor": dump(value.descriptor),
        "observation": dump(value.observation),
        "root": dump(value.root_reference),
        "metadata": dump(value.metadata),
        "policy": dump(value.policy),
        "source_document": document,
    }


def frame(value: Any) -> dict[str, Any]:
    _, _, rgba = rgba_png(value.png)
    artifact = value.pixel_artifact
    return {
        "class": type(value).__name__,
        "info": dump(value.info),
        "png": list(value.png),
        "rgba": rgba,
        "pixel_artifact": None
        if artifact is None
        else {"info": dump(artifact.info), "bytes": list(artifact.bytes)},
    }


async def _observe(
    fixtures: dict[str, Any], ys: Any, path: Path
) -> list[dict[str, Any]]:
    sf = ys.surface
    policy = sf.VideoPolicy.model_validate(fixtures["input"]["policy"])
    surface = await sf.VideoSurface.open(path, policy)
    root = surface.root_reference
    reference = surface.at(125000)
    rect = sf.PixelRect(x=8, y=4, width=16, height=8)
    cropped = await surface.crop(reference, rect)
    rows = []
    with TemporaryDirectory(prefix="yosoi-video-parity-") as directory:
        archive = await ys.Archive.open(Path(directory) / "archive")
        for case in fixtures["cases"]:
            name = case["name"]
            if name == "open":
                observed, arguments = (
                    video(surface),
                    {"path": str(path), "policy": dump(policy)},
                )
            elif name == "from-document":
                document = surface.source_document
                if document is None:
                    raise ValueError("shared clip did not retain a VideoDocument")
                observed = video(await sf.VideoSurface.from_document(document, policy))
                arguments = {
                    "document": {"id": str(document.id), "sha256": document.sha256},
                    "policy": dump(policy),
                }
            elif name in {"overview", "expand"}:
                request = sf.ReadRequest.model_validate(case["input"]["request"])
                observed = dump(surface.read(request))
                arguments = {"self": dump(root), "request": dump(request)}
            elif name in {"frame-zero", "frame-next", "frame-half"}:
                position = {
                    "frame-zero": 0,
                    "frame-next": 125000,
                    "frame-half": 500000,
                }[name]
                selected = surface.at(position)
                observed = frame(await surface.frame(selected))
                arguments = {"self": dump(root), "reference": dump(selected)}
            elif name == "crop":
                observed, arguments = (
                    frame(cropped),
                    {
                        "self": dump(root),
                        "reference": dump(reference),
                        "rect": dump(rect),
                    },
                )
            elif name == "archive-frame":
                saved = await cropped.write_to(archive)
                observed = frame(await sf.DecodedFrame.read_from(archive, saved))
                arguments = {
                    "archive": "archive",
                    "reference": {
                        "kind": "FrameArchiveRef",
                        "selected_value": observed,
                    },
                    "observed_storage_reference": dump(saved),
                }
            elif name == "archive-video":
                saved = await surface.write_to(archive)
                observed = video(await sf.VideoSurface.read_from(archive, saved))
                arguments = {
                    "archive": "archive",
                    "reference": {
                        "kind": "VideoArchiveRef",
                        "selected_value": observed,
                    },
                    "observed_storage_reference": dump(saved),
                }
            else:
                raise ValueError(f"unimplemented video observation: {name}")
            rows.append(comparison(case, observed, arguments))
        for case in fixtures["errorCases"]:
            name = case["name"]
            arguments = {"self": dump(root)}
            try:
                if name == "cancelled-frame":
                    token = ys.CancellationToken()
                    token.cancel()
                    arguments.update(
                        reference=dump(reference),
                        cancellation={"cancelled": token.cancelled},
                    )
                    await surface.frame(reference, cancellation=token)
                elif name == "foreign-reference":
                    selected = sf.Reference(
                        observation="foreign-video", address=reference.address
                    )
                    arguments["reference"] = dump(selected)
                    await surface.frame(selected)
                elif name == "nested-crop":
                    selected = cropped.info.reference
                    arguments.update(reference=dump(selected), rect=dump(rect))
                    await surface.crop(selected, rect)
                elif name == "crop-outside":
                    outside = sf.PixelRect(x=63, y=0, width=2, height=2)
                    arguments.update(reference=dump(reference), rect=dump(outside))
                    await surface.crop(reference, outside)
                elif name == "tail-no-frame":
                    tail = surface.at(875000)
                    arguments["reference"] = dump(tail)
                    await surface.frame(tail)
                elif name == "at-end":
                    arguments["position_us"] = surface.metadata.duration_us
                    surface.at(surface.metadata.duration_us)
                else:
                    raise RuntimeError(f"unimplemented video failure: {name}")
            except sf.VideoError as error:
                from yosoi.errors import rust_error_details

                details = rust_error_details(error)
                if details is None:
                    raise ValueError(
                        f"video error lacks native details: {name}"
                    ) from error
                observed = {
                    "rust_type": details.rust_type,
                    "variant": details.variant,
                    "details": _plain(details.details),
                    "source_chain": list(details.source_chain),
                }
            else:
                observed = {"unexpected_success": True}
            rows.append(comparison(case, observed, arguments))
    return rows


def observe_fixtures(
    fixtures: dict[str, Any], ys: Any, path: Path
) -> list[dict[str, Any]]:
    """Run serial video operations; native cancellation awaits owned cleanup."""
    return asyncio.run(_observe(fixtures, ys, path))
