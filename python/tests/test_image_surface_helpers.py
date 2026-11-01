"""Checked image authoring and lifecycle parity through the installed wheel."""

import asyncio
import struct
import zlib

import pytest

import yosoi as ys
from yosoi import surface as sf


def _png() -> bytes:
    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 4, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\x01\x02\x03\xff" * 8) * 4))
        + chunk(b"IEND", b"")
    )


def test_checked_builders_index_and_coordinate_helpers():
    document = ys.ImageDocument.from_bytes("image-helper", _png())
    decoded = sf.PixelArtifact.decode_image_document(document)
    explicit = sf.PixelArtifact.from_image_document(document, width=8, height=4)
    assert explicit.info == decoded.info
    explicit.validate_artifact()
    assert explicit.source_identity() == sf.image_source_identity(document)
    assert explicit.source_identity() == sf.pixel_source_identity(explicit.info.source)
    surface = sf.ImageSurface(document, tile_side=32)
    assert surface.source_document == document
    assert (
        surface.index.identity
        == sf.Surface.from_image_document(document, tile_side=32).identity
    )
    assert (
        sf.Surface.from_pixel_artifact(explicit, tile_side=32).identity
        == sf.ImageSurface.from_pixel_artifact(explicit, tile_side=32).index.identity
    )
    rect = sf.PixelRect(x=0, y=0, width=4, height=2)
    cropped = surface.crop_rect(rect).artifact
    rebound = sf.PixelArtifact.crop_from(explicit, cropped.document, rect)
    assert rebound.info == cropped.info
    resized = surface.resize_image(4, 2)
    rebound = sf.PixelArtifact.resize_from(
        explicit, resized.document, resized.info.transform.operation, 4, 2
    )
    assert rebound.info == resized.info
    assert (
        sf.resize_transform(explicit, resized.info.transform.operation, 4, 2)
        == resized.info.transform
    )
    assert "content" not in rebound.model_dump()
    assert rebound.content not in repr(rebound).encode()
    with pytest.raises(sf.SurfaceError):
        sf.PixelArtifact.from_image_document(document, width=7, height=4)
    with pytest.raises(sf.SurfaceError, match="nested"):
        sf.PixelArtifact.crop_from(cropped, cropped.document, rect)
    with pytest.raises(sf.SurfaceError):
        sf.ImageSurface.from_pixel_artifact(cropped)
    with pytest.raises(ValueError, match="provenance"):
        rebound.model_copy(
            update={"info": rebound.info.model_copy(update={"sha256": "0" * 64})}
        )


def test_raster_source_and_limit_helpers_preserve_native_validation():
    document = ys.ImageDocument.from_bytes("image-helper", _png())
    source = sf.BrowserScreenshotPixelSource(
        kind="browser_screenshot", identity="screenshot:helper"
    )
    space = sf.PixelCoordinateSpace(
        kind="decoded_canvas", width=8, height=4, orientation="not_applicable"
    )
    artifact = sf.PixelArtifact.from_raster_document(document, source, space)
    assert (
        sf.ImageSurface.from_pixel_artifact(artifact).source_artifact.info.source
        == source
    )
    assert artifact.source_identity() == sf.pixel_source_identity(source)
    limits = sf.PixelLimits(max_output_bytes=1024)
    assert limits.validate_limits() == limits
    assert limits.check_pixels(8, 4) == 32
    assert limits.check_output(8, 4, len(artifact.bytes)) is None
    with pytest.raises(sf.SurfaceError):
        limits.check_pixels(0, 1)
    with pytest.raises(sf.SurfaceError):
        limits.check_output(8, 4, 1025)
    with pytest.raises(sf.SurfaceError):
        sf.PixelArtifact.from_raster_document(
            document, source, space.model_copy(update={"width": 7})
        )


def test_image_connection_file_and_saved_root_lifecycle(tmp_path):
    async def run():
        source = tmp_path / "source.png"
        source.write_bytes(_png())
        policy = sf.SurfacePolicy(
            archive="enabled",
            archive_root=tmp_path / "archive",
            output=tmp_path / "file-output",
        )
        session = await sf.ImageSession.open(source, policy, tile_side=32)
        ready = await session.ready()
        assert ready["state"]["descriptor"]["controllable"] is False
        result = await session.execute({"op": "image_direct"})
        assert result["artifact"]["info"]["width"] == 8
        with pytest.raises(sf.ExecutionError):
            await session.execute({"op": "hot"})
        assert await session.outcome() is not None
        outcome = await session.close()
        assert outcome is not None and outcome.complete and outcome.sealed
        assert await session.close() == outcome
        artifact = outcome.source_pixel_artifact(
            ready["state"]["source_pixel_artifact"]["identity"]
        )
        archive = await ys.Archive.open(tmp_path / "archive")
        reference = await artifact.write_to(archive)
        reopened = await sf.ImageSession.open_pixel_artifact(
            reference,
            tmp_path / "archive",
            policy.model_copy(update={"output": tmp_path / "saved-output"}),
            tile_side=32,
        )
        async with reopened:
            await reopened.ready()
            saved = await reopened.execute({"op": "image_direct"})
            assert saved["artifact"]["info"] == artifact.info.model_dump(mode="json")
        with pytest.raises(sf.ExecutionError):
            await reopened.ready()
        retained = sf.ArchivedSource.from_image(
            "image",
            artifact.document,
            tile_side=32,
            surface=sf.Surface.from_image_document(artifact.document, tile_side=32),
        )
        assert (
            retained.restore_surface().identity
            == sf.Surface.from_image_document(artifact.document, tile_side=32).identity
        )

    asyncio.run(run())
