"""Public Python Surface behavior, through the compiled Rust binding."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

import yosoi as ys
from yosoi import surface as sf
from yosoi.errors import rust_error_details


def _rgba_png(width: int, height: int, pixel) -> bytes:
    def chunk(kind: bytes, content: bytes) -> bytes:
        checksum = zlib.crc32(kind + content) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(content))
            + kind
            + content
            + struct.pack(">I", checksum)
        )

    rows = b"".join(
        b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width))
        for y in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    "identity",
    [
        sf.SourceId,
        sf.SurfaceId,
        sf.ObservationId,
        sf.AddressToken,
        sf.ContinuationToken,
    ],
)
def test_shared_identifiers_use_rust_validation(identity) -> None:
    assert identity("producer:value").as_str() == "producer:value"
    for invalid in ("", "control\ncharacter", "x" * 1025):
        with pytest.raises(sf.SurfaceError) as caught:
            identity(invalid)
        details = rust_error_details(caught.value)
        assert details is not None
        assert details.variant == "Invalid"
        assert details.details["message"] == "invalid evidence identifier or token"


@pytest.mark.parametrize(
    "document",
    [
        lambda: ys.Document.html("fixture", "<main><h1>Needle λ🙂</h1></main>"),
        lambda: ys.Document.xml("fixture", "<r><name>Needle λ🙂</name></r>"),
        lambda: ys.Document.from_json("fixture", '{"name":"Needle λ🙂"}'),
        lambda: ys.Document.text("fixture", "Needle λ🙂"),
    ],
)
def test_document_reads_use_exact_evidence(document) -> None:
    index = sf.Surface(document())
    page = index.find("Needle")
    reference = page.entries[0].reference
    assert "Needle λ🙂" in index.inspect(reference).content
    assert index.metadata.coverage.complete
    index.validate(reference)
    other = sf.Surface(ys.Document.text("other", "unrelated"))
    with pytest.raises(sf.SurfaceError) as caught:
        other.validate(reference)
    details = rust_error_details(caught.value)
    assert details is not None and details.variant == "WrongCapture"


def test_typed_image_direct_overview_crop_and_archive(tmp_path) -> None:
    async def run() -> None:
        encoded = _rgba_png(
            256,
            128,
            lambda x, y: (255, 0, 0, 255) if x < 128 and y < 64 else (0, 0, 255, 255),
        )
        image = ys.ImageDocument.from_bytes(
            "typed-dashboard",
            encoded,
            metadata=ys.FileMetadata(source="fixture:dashboard"),
        )
        direct_without_index = ys.PixelArtifact.from_image_document(image)
        assert direct_without_index.content == encoded
        surface = sf.ImageSurface(image, tile_side=64)
        page = surface.read(
            sf.ReadRequest(
                operation=sf.Overview(), budget=sf.Budget(bytes=2048, items=5)
            )
        )
        assert isinstance(page, sf.PageResult)
        assert not surface.descriptor.controllable
        assert any(
            capability.id == "image.direct@1"
            for capability in surface.descriptor.capabilities
        )

        direct = surface.direct_image()
        assert direct.content == encoded
        assert direct.info.identity == direct_without_index.info.identity
        assert direct.info.coordinate_space.kind == "original_raster"
        assert direct.info.coordinate_space.orientation == "exif_unapplied"
        direct_surface = sf.ImageSurface.from_pixel_artifact(direct, tile_side=64)
        assert direct_surface.source_artifact.info == direct.info
        overview = surface.overview_image(64)
        assert (overview.info.width, overview.info.height) == (64, 32)
        source_rect = overview.map_rect_to_source(
            sf.PixelRect(x=0, y=0, width=32, height=16)
        )
        assert source_rect == sf.PixelRect(x=0, y=0, width=128, height=64)
        crop = surface.crop_rect(source_rect)
        assert (crop.artifact.info.width, crop.artifact.info.height) == (128, 64)
        assert crop.artifact.info.transform.parent_identity == direct.info.identity
        assert crop.artifact.content not in repr(crop.artifact).encode()
        assert "content" not in crop.artifact.model_dump()
        changed_info = crop.artifact.info.model_copy(update={"sha256": "0" * 64})
        with pytest.raises(ValueError, match="provenance cannot be forged"):
            crop.artifact.model_copy(update={"info": changed_info})
        with pytest.raises(ValueError, match="bytes cannot be changed"):
            crop.artifact.model_copy(update={"content": b"forged pixels"})

        other = sf.ImageSurface(
            ys.ImageDocument.from_bytes("other-dashboard", encoded), tile_side=64
        )
        with pytest.raises(sf.SurfaceError) as caught:
            other.crop(surface.root_reference)
        details = rust_error_details(caught.value)
        assert details is not None and details.variant == "WrongCapture"
        with pytest.raises(sf.SurfaceError):
            surface.crop_rect(sf.PixelRect(x=255, y=0, width=2, height=2))

        archive = await ys.Archive.open(tmp_path / "archive")
        reference = await archive.write(crop.artifact)
        restored = await archive.read(reference)
        assert isinstance(restored, sf.PixelArtifact)
        assert restored.content == crop.png
        assert restored.info == crop.artifact.info
        with pytest.raises(sf.SurfaceError, match="derived pixel artifacts"):
            sf.ImageSurface.from_pixel_artifact(restored, tile_side=64)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("document", "representation"),
    [
        (
            lambda: ys.Document.html("html", "<main><h1>Arc lamp λ🙂</h1></main>"),
            "yosoi.web.document.v1",
        ),
        (
            lambda: ys.Document.xml(
                "xml", '<r xmlns:x="urn:fixture"><x:name>Arc lamp λ🙂</x:name></r>'
            ),
            "yosoi.web.xml.v1",
        ),
        (
            lambda: ys.Document.from_json("json", '{"a/b":{"~name":"Arc lamp λ🙂"}}'),
            "yosoi.web.json.v1",
        ),
        (
            lambda: ys.Document.text("text", "Arc lamp λ🙂\n"),
            "yosoi.web.text.v1",
        ),
        (
            lambda: ys.Document.rendered_dom(
                "dom",
                7,
                json.dumps(
                    {
                        "schema": "yosoi.rendered-dom.v1",
                        "document_epoch": 7,
                        "tree_model": "document_light_dom",
                        "root": 1,
                        "nodes": [
                            {
                                "kind": "document",
                                "id": 1,
                                "parent": None,
                                "children": [2],
                            },
                            {
                                "kind": "element",
                                "id": 2,
                                "parent": 1,
                                "children": [3],
                                "namespace_uri": "http://www.w3.org/1999/xhtml",
                                "tag_name": "button",
                                "attributes": [],
                            },
                            {
                                "kind": "text",
                                "id": 3,
                                "parent": 2,
                                "children": [],
                                "value": "Arc lamp λ🙂",
                            },
                        ],
                    }
                ),
            ),
            "yosoi.web.document.v1",
        ),
        (
            lambda: ys.Document.accessibility_tree(
                "ax",
                7,
                json.dumps(
                    {
                        "schema": "yosoi.accessibility-tree.v1",
                        "document_epoch": 7,
                        "root": "root",
                        "completeness": {
                            "status": "unknown",
                            "reason_code": "provider_gap",
                        },
                        "nodes": [
                            {
                                "id": "root",
                                "parent": None,
                                "children": ["button"],
                                "ignored": False,
                                "role": "RootWebArea",
                                "accessible_name": None,
                                "text": None,
                                "states": {},
                            },
                            {
                                "id": "button",
                                "parent": "root",
                                "children": [],
                                "ignored": False,
                                "role": "button",
                                "accessible_name": "Arc lamp λ🙂",
                                "text": None,
                                "states": {},
                            },
                        ],
                    }
                ),
            ),
            "yosoi.web.ax.v1",
        ),
    ],
)
def test_websurface_uses_shared_reads_for_all_document_classes(
    document, representation: str
) -> None:
    index = sf.Surface(document())
    reader = sf.WebSurface(index, f"fixture:{representation}")
    assert reader.descriptor.representation == representation
    assert not reader.descriptor.controllable
    assert {capability.id for capability in reader.descriptor.capabilities} == {
        "web.overview@1",
        "web.expand@1",
        "web.inspect@1",
        "web.search@1",
        "web.parent@1",
    }
    assert all(
        capability.access == "read" for capability in reader.descriptor.capabilities
    )

    overview = reader.read(sf.ReadRequest(operation=sf.Overview()))
    assert isinstance(overview, sf.PageResult)
    expanded = reader.read(
        sf.ReadRequest(operation=sf.Expand(reference=reader.root_reference))
    )
    assert isinstance(expanded, sf.PageResult)
    found = reader.read(sf.ReadRequest(operation=sf.Search(query="lamp")))
    assert isinstance(found, sf.PageResult) and found.data.entries
    reference = found.data.entries[0].reference
    inspected = reader.read(sf.ReadRequest(operation=sf.Inspect(reference=reference)))
    assert isinstance(inspected, sf.InspectionResult)
    assert "lamp" in inspected.data.content.lower()
    parent = reader.read(sf.ReadRequest(operation=sf.Parent(reference=reference)))
    assert isinstance(parent, sf.ParentResult)
def test_shared_read_continuations_are_scoped_and_bounded() -> None:
    index = sf.Surface(
        ys.Document.html(
            "list",
            "<ul>" + "".join(f"<li>Needle {n}</li>" for n in range(30)) + "</ul>",
        )
    )
    reader = sf.WebSurface(index, "fixture:products")
    other = sf.WebSurface(index, "fixture:other-source")
    request = sf.ReadRequest(
        operation=sf.Search(query="Needle"), budget=sf.Budget(bytes=1400, items=2)
    )
    seen = set()
    first_token = None
    while True:
        result = reader.read(request)
        assert isinstance(result, sf.PageResult)
        # Rust owns the result bound; check Python's typed projection too.
        assert len(result.model_dump_json().encode()) <= 1400
        seen.update(entry.reference.address for entry in result.data.entries)
        token = result.data.next
        if first_token is None:
            first_token = token
        if token is None:
            break
        request = request.model_copy(update={"continuation": token})
    assert len(seen) == 30
    assert first_token is not None
    with pytest.raises(sf.SurfaceError):
        other.read(
            sf.ReadRequest(
                operation=sf.Search(query="Needle"), continuation=first_token
            )
        )
    with pytest.raises(sf.SurfaceError):
        reader.read(sf.ReadRequest(operation=sf.Overview(), continuation=first_token))
    assert not reader.descriptor.controllable
    assert reader.native_reference(reader.reference(index.root)) == index.root


def test_websurface_inspection_continuations_preserve_unicode_and_policy_caps() -> None:
    content = "λ🙂 paragraph\n" * 400
    index = sf.Surface(ys.Document.text("unicode", content))
    reader = sf.WebSurface(
        index,
        "fixture:unicode",
        sf.DocumentPolicy(response_bytes=1024),
    )
    request = sf.ReadRequest(
        operation=sf.Inspect(reference=reader.root_reference),
        budget=sf.Budget(bytes=4096, items=5),
    )
    chunks: list[str] = []
    first_token = None
    last_offset = -1
    while True:
        result = reader.read(request)
        assert isinstance(result, sf.InspectionResult)
        assert len(result.model_dump_json().encode("utf-8")) <= 1024
        assert result.data.offset > last_offset
        last_offset = result.data.offset
        chunks.append(result.data.content)
        if first_token is None:
            first_token = result.data.next
        token = result.data.next
        if token is None:
            break
        request = request.model_copy(update={"continuation": token})
    assert "".join(chunks) == content
    assert first_token is not None
    with pytest.raises(sf.SurfaceError):
        reader.read(
            sf.ReadRequest(
                operation=sf.Search(query="paragraph"),
                continuation=first_token,
            )
        )


def test_websurface_continuations_reject_a_different_expand_scope() -> None:
    content = "λ🙂 source range\n" * 600
    reader = sf.WebSurface(
        sf.Surface(ys.Document.text("scopes", content)), "fixture:scopes"
    )
    first = reader.read(
        sf.ReadRequest(
            operation=sf.Expand(reference=reader.root_reference),
            budget=sf.Budget(bytes=1200, items=1),
        )
    )
    assert isinstance(first, sf.PageResult) and first.data.next is not None
    assert first.data.entries
    with pytest.raises(sf.SurfaceError):
        reader.read(
            sf.ReadRequest(
                operation=sf.Expand(reference=first.data.entries[0].reference),
                budget=sf.Budget(bytes=1200, items=1),
                continuation=first.data.next,
            )
        )


@pytest.mark.parametrize("epoch", [7, 8])
def test_rendered_dom_epoch_and_native_coordinates(epoch: int) -> None:
    def prepare(generation: int) -> sf.Surface:
        payload = {
            "schema": "yosoi.rendered-dom.v1",
            "document_epoch": generation,
            "tree_model": "document_light_dom",
            "root": 1,
            "nodes": [
                {"kind": "document", "id": 1, "parent": None, "children": [2]},
                {
                    "kind": "element",
                    "id": 2,
                    "parent": 1,
                    "children": [3],
                    "namespace_uri": "http://www.w3.org/1999/xhtml",
                    "tag_name": "button",
                    "attributes": [],
                },
                {
                    "kind": "text",
                    "id": 3,
                    "parent": 2,
                    "children": [],
                    "value": "Submit",
                },
            ],
        }
        return sf.Surface(
            ys.Document.rendered_dom("dom", generation, json.dumps(payload))
        )

    index = prepare(epoch)
    reference = index.find("Submit").entries[0].reference
    assert index.coordinate(reference) == sf.Coordinate(kind="dom_node", value="3")
    with pytest.raises(sf.SurfaceError):
        prepare(epoch + 1).validate(reference)


def test_accessibility_partial_coverage_cannot_grant_action() -> None:
    payload = {
        "schema": "yosoi.accessibility-tree.v1",
        "document_epoch": 7,
        "root": "root",
        "completeness": {"status": "unknown", "reason_code": "provider_gap"},
        "nodes": [
            {
                "id": "root",
                "parent": None,
                "children": ["button"],
                "ignored": False,
                "role": "RootWebArea",
                "accessible_name": None,
                "text": None,
                "states": {},
            },
            {
                "id": "button",
                "parent": "root",
                "children": [],
                "ignored": False,
                "role": "button",
                "accessible_name": "Submit",
                "text": None,
                "states": {},
            },
        ],
    }
    index = sf.Surface(ys.Document.accessibility_tree("ax", 7, json.dumps(payload)))
    assert not index.metadata.coverage.complete
    session = sf.Session(index)
    session.attach()
    with session.cursor() as cursor:
        cursor.focus(index.find("Submit").entries[0].reference)
        cursor.promote()
        with pytest.raises(sf.SurfaceError) as caught:
            cursor.begin_action()
        details = rust_error_details(caught.value)
        assert details is not None and details.variant == "Uncertain"


def test_detail_chunks_reconstruct_unicode_source() -> None:
    source = "<main>" + "λ🙂" * 4000 + "</main>"
    index = sf.Surface(ys.Document.html("unicode", source))
    chunks = []
    token = None
    while True:
        part = index.inspect(
            index.root, continuation=token, budget=sf.Budget(bytes=1200)
        )
        assert len(part.model_dump_json().encode()) <= 1200
        chunks.append(part.content)
        token = part.next
        if token is None:
            break
    detail = "".join(chunks)
    assert detail.count("λ🙂") == 4000
    with pytest.raises(sf.SurfaceError):
        index.inspect(index.root, budget=sf.Budget(bytes=16))


def test_combined_views_keep_original_evidence() -> None:
    original = sf.Surface(ys.Document.text("notes", "Needle lamp"))
    combined = sf.Surface.combine("product", {"notes": original})
    projected = combined.project("notes", original.root)
    assert combined.source_reference(projected) == sf.SourceReference(
        view="notes", reference=original.root
    )
    assert (
        combined.inspect(projected).content == original.inspect(original.root).content
    )
    assert combined.view("missing") is None
    assert "atomic=false" in combined.metadata.representation


def test_detached_reader_hot_lease_and_stale_capture() -> None:
    before = sf.Surface(ys.Document.html("before", "<button>Add lamp</button>"))
    session = sf.Session(before, sf.SessionPolicy(cursors=2))
    with session.cursor() as actor, session.cursor() as reader:
        actor.focus(before.find("Add lamp").entries[0].reference)
        assert not actor.status.live and not actor.status.hot
        with pytest.raises(sf.SurfaceError):
            actor.promote()
        session.attach()
        actor.promote()
        with pytest.raises(sf.SurfaceError):
            reader.promote()
        watch = reader.subscribe(before.root)
        with actor.begin_action() as lease:
            assert lease.revalidate() == actor.position.focus
            lease.mark_dispatched()
            after = sf.Surface(ys.Document.html("after", "<button>Lamp added</button>"))
            session.publish(after)
            with pytest.raises(sf.SurfaceError):
                lease.revalidate()
            receipt = lease.finish("Unconfirmed", "adapter lost postcondition")
            assert receipt.dispatched and receipt.status == "Unconfirmed"
        assert actor.status.focus_freshness == "Stale"
        assert reader.reconcile(watch, after.root) == "Changed"
        assert reader.events().events
        reader.unsubscribe(watch)
        session.detach()
        assert session.hot_owner is None


def test_cursor_context_preserves_caller_error_after_explicit_close() -> None:
    session = sf.Session(sf.Surface(ys.Document.text("fixture", "stock")))
    with pytest.raises(ValueError, match="caller failure"):
        with session.cursor() as cursor:
            cursor.close()
            raise ValueError("caller failure")


@pytest.mark.skipif(os.name != "posix", reason="Archive local backend requires Unix")
def test_video_pixels_and_archive_restore_without_decoder(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if (
        not ffmpeg
        or not shutil.which("ffprobe")
        or not ys._native.surface_video_enabled
    ):
        pytest.skip("native video tools/feature unavailable")
    source = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=10:duration=1",
            "-c:v",
            "mpeg4",
            "-threads",
            "1",
            str(source),
        ],
        check=True,
        timeout=30,
    )

    async def run() -> None:
        video = await sf.VideoSurface.open(source)
        source.unlink()
        assert video.metadata.width == 320
        assert video.metadata.duration_us == 1000000
        assert not video.descriptor.controllable
        assert not video.observation.coverage.complete
        timeline = video.read(sf.ReadRequest(operation=sf.Overview()))
        assert isinstance(timeline, sf.PageResult) and timeline.data.entries
        foreign = sf.WebSurface(
            sf.Surface(ys.Document.html("web", "<h1>Other</h1>")), "web:other"
        )
        with pytest.raises(sf.VideoError) as caught:
            await video.frame(foreign.root_reference)
        details = rust_error_details(caught.value)
        assert details is not None and details.variant == "Surface"
        assert details.details["surface"]["variant"] == "WrongCapture"
        with pytest.raises(sf.SurfaceError):
            video.read(sf.ReadRequest(operation=sf.Search(query="text")))
        frame = await video.frame(video.at(350000))
        assert frame.info.requested_us == 350000
        assert frame.info.position_us == 400000
        assert hashlib.sha256(frame.png).hexdigest() == frame.info.png_sha256
        crop = await video.crop(
            video.at(350000), sf.PixelRect(x=10, y=20, width=60, height=50)
        )
        assert crop.info.width == 60 and crop.info.height == 50
        image = sf.Surface.from_image(frame.png)
        image_crop = image.crop(image.root)
        assert image_crop.png.startswith(b"\x89PNG\r\n\x1a\n")
        assert image_crop.rect.width == 320 and image_crop.rect.height == 180
        archive = await ys.Archive.open(tmp_path / "archive")
        video_ref = await video.write_to(archive)
        frame_ref = await crop.write_to(archive)
        (tmp_path / "refs.json").write_text(
            json.dumps(
                {"video": video_ref.model_dump(), "frame": frame_ref.model_dump()}
            )
        )
        return None

    asyncio.run(run())
    # Fresh interpreter without source/decoder: saved timeline and pixels survive.
    script = """
import asyncio, json, hashlib, sys
import yosoi as ys
from yosoi import surface as sf
async def main():
    values = json.load(open(sys.argv[2]))
    archive = await ys.Archive.open(sys.argv[1])
    saved_video = sf.VideoArchiveRef.model_validate(values["video"])
    video = await sf.VideoSurface.read_from(archive, saved_video)
    assert video.read(sf.ReadRequest(operation=sf.Overview())).kind == "page"
    saved_frame = sf.FrameArchiveRef.model_validate(values["frame"])
    frame = await sf.DecodedFrame.read_from(archive, saved_frame)
    assert len(frame.png) == frame.info.png_bytes
    assert hashlib.sha256(frame.png).hexdigest() == frame.info.png_sha256
    assert frame.info.width == 60
asyncio.run(main())
"""
    subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path / "archive"),
            str(tmp_path / "refs.json"),
        ],
        env={**os.environ, "YOSOI_FFMPEG": "/no-decoder", "YOSOI_FFPROBE": "/no-probe"},
        check=True,
        timeout=30,
    )
