"""Media and opaque file documents retain exact bytes and typed Archive evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import cast

import pytest
from pydantic import TypeAdapter, ValidationError

import yosoi as ys
from yosoi.archive import (
    BinaryDocumentArchiveRef,
    FileDocumentArchiveRef,
    ImageDocumentArchiveRef,
)
from yosoi.downloads import DownloadOptions
from yosoi.errors import FileDocumentError, rust_error_details

PNG = b"\x89PNG\r\n\x1a\n" + b"native payload bytes"
MP4 = b"\x00\x00\x00\x10ftypmp42"
AUDIO = b"ID3\x04\x00\x00\x00\x00\x00\x00"
OPAQUE = b"unknown application payload"


@pytest.fixture
def media_site():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(404 if self.path == "/missing" else 200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG)))
            self.end_headers()
            self.wfile.write(PNG)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(10)
        assert not thread.is_alive()


def test_media_semantic_contract_targets_public_python_symbols_and_scenarios() -> None:
    contract_path = (
        Path(__file__).parents[1] / "parity" / "media-documents-contract.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["kind"] == "yosoi-python-media-documents-semantic-contract"
    for declaration in contract["declarations"]:
        assert declaration["rustPath"].startswith("yosoi::")
        assert declaration["semanticEquivalent"]
        target = ys
        for attribute in declaration["pythonTarget"].removeprefix("yosoi.").split("."):
            target = getattr(target, attribute)
        assert target is not None
        for scenario in declaration["tests"]:
            assert scenario in globals()


def test_download_context_cancellation_awaits_cleanup_and_retains_work_owner() -> None:
    class FakeNativeCapture:
        def __init__(self, wait_variant: str = "Cancelled") -> None:
            self.wait_started = asyncio.Event()
            self.release_wait = asyncio.Event()
            self.cleanup_finished = asyncio.Event()
            self.wait_variant = wait_variant
            self.loop = asyncio.get_running_loop()
            self.wait_future = self.loop.create_future()

        def wait(self) -> asyncio.Future[object]:
            self.wait_started.set()
            return self.wait_future

        def cancel(self) -> asyncio.Future[None]:
            self.release_wait.set()
            self.cleanup_finished.set()
            if self.wait_started.is_set() and not self.wait_future.done():
                error = ys._native.DownloadError("native wait ended during cleanup")
                error.rust_type = "yosoi::session::DownloadError"
                error.variant = self.wait_variant
                error.details = {}
                error.source_chain = []
                self.wait_future.set_exception(error)
            cancel_future: asyncio.Future[None] = self.loop.create_future()
            cancel_future.set_result(None)
            return cancel_future

    class FakeWork:
        def __init__(self, capture: FakeNativeCapture) -> None:
            self.capture = capture

        async def _expect_download(self, options: DownloadOptions) -> FakeNativeCapture:
            assert options.max_bytes == 64 * 1024 * 1024
            return self.capture

    async def run() -> None:
        native = FakeNativeCapture()
        work = FakeWork(native)
        capture = ys.Work.expect_download(cast(ys.Work, work))
        assert await capture.__aenter__() is capture
        waiter = asyncio.create_task(capture.wait())
        await native.wait_started.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert native.cleanup_finished.is_set()
        assert capture._work is work
        assert capture._handle is None

        failing_native = FakeNativeCapture("UnrelatedDownload")
        failing_capture = ys.Work.expect_download(
            cast(ys.Work, FakeWork(failing_native))
        )
        await failing_capture.__aenter__()
        failing_waiter = asyncio.create_task(failing_capture.wait())
        await failing_native.wait_started.wait()
        failing_waiter.cancel()
        with pytest.raises(ys.BrowserCleanupError) as cleanup_failure:
            await failing_waiter
        cleanup_error = cleanup_failure.value.cleanup_errors[0]
        assert isinstance(cleanup_error, ys.DownloadError)
        assert cleanup_error.variant == "UnrelatedDownload"
        assert failing_native.cleanup_finished.is_set()

        unconsumed_native = FakeNativeCapture()
        unconsumed = ys.Work.expect_download(cast(ys.Work, FakeWork(unconsumed_native)))
        async with unconsumed:
            pass
        assert unconsumed_native.cleanup_finished.is_set()

    asyncio.run(run())


def test_media_factory_classifies_and_redacts_payload() -> None:
    image = ys.file_from_bytes(
        "image-one",
        PNG,
        metadata=ys.FileMetadata(
            filename="cover.png",
            declared_media_type="application/octet-stream",
            source="fixture",
        ),
    )
    binary = ys.file_from_bytes("opaque-one", OPAQUE)
    video = ys.file_from_bytes("video-one", MP4)
    audio = ys.file_from_bytes("audio-one", AUDIO)

    assert isinstance(image, ys.ImageDocument)
    assert image.id == "image-one"
    assert image.bytes == PNG
    assert image.byte_len == len(PNG)
    assert image.sha256 == hashlib.sha256(PNG).hexdigest()
    assert image.metadata.filename == "cover.png"
    assert image.metadata.declared_media_type == "application/octet-stream"
    assert image.metadata.detected_media_type == "image/png"
    assert image.metadata.sha256 == image.sha256
    assert "native payload bytes" not in repr(image)
    assert "data" not in image.model_dump()
    assert "native payload bytes" not in image.model_dump_json()
    assert isinstance(binary, ys.BinaryDocument)
    assert binary.bytes == OPAQUE
    assert binary.metadata.detected_media_type is None
    assert isinstance(video, ys.VideoDocument)
    assert video.bytes == MP4
    assert isinstance(audio, ys.AudioDocument)
    assert audio.bytes == AUDIO


def test_concrete_media_constructor_checks_family_without_decoding() -> None:
    image = ys.ImageDocument.from_bytes("typed-image", PNG)
    binary = ys.BinaryDocument.from_bytes("typed-binary", OPAQUE)
    assert isinstance(image, ys.ImageDocument)
    assert image.bytes == PNG
    assert isinstance(binary, ys.BinaryDocument)
    assert binary.bytes == OPAQUE

    with pytest.raises(FileDocumentError) as failure:
        ys.ImageDocument.from_bytes("wrong-image", OPAQUE)
    details = rust_error_details(failure.value)
    assert details is not None
    assert details.variant == "TypeMismatch"
    assert details.details["expected"] == "image"


def test_file_limits_enforce_default_hard_cap_and_payload_size() -> None:
    assert ys.FileLimits().max_bytes == 64 * 1024 * 1024
    with pytest.raises(ValidationError):
        ys.FileLimits(max_bytes=256 * 1024 * 1024 + 1)
    with pytest.raises(FileDocumentError) as failure:
        ys.file_from_bytes("small-limit", OPAQUE, limits=ys.FileLimits(max_bytes=4))
    details = rust_error_details(failure.value)
    assert details is not None
    assert details.variant == "TooLarge"
    assert details.details["maximum"] == 4


def test_file_metadata_keeps_long_source_urls_with_a_one_mebibyte_bound() -> None:
    source = "https://example.invalid/" + "x" * 5_000
    document = ys.file_from_bytes(
        "long-source", OPAQUE, metadata=ys.FileMetadata(source=source)
    )
    assert document.metadata.source == source
    with pytest.raises(ValidationError):
        ys.FileMetadata(source="x" * (1024 * 1024 + 1))


def test_read_file_uses_basename_and_returns_detected_concrete_type(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cover.png"
    path.write_bytes(PNG)

    async def run() -> None:
        document = await ys.read_file("local-image", path)
        assert isinstance(document, ys.ImageDocument)
        assert document.id == "local-image"
        assert document.metadata.filename == "cover.png"
        assert document.bytes == PNG

    asyncio.run(run())


def test_attempt_conversion_reuses_complete_http_error_body_and_keeps_status(
    media_site: str,
) -> None:
    async def run() -> None:
        response = await ys.request.new(media_site + "/missing").send()
        attempt = response.attempts[0]
        image = attempt.file_document()
        assert isinstance(image, ys.ImageDocument)
        assert attempt.http_status == 404
        assert attempt.body == image.bytes == PNG
        assert image.id == attempt.capture_id
        assert image.metadata.declared_media_type == "image/png"
        assert image.metadata.detected_media_type == "image/png"
        assert image.metadata.source == media_site + "/missing"
        assert image.metadata.capture_id == attempt.capture_id
        cloned_attempt = attempt.clone()
        assert cloned_attempt._handle is attempt._handle
        del response
        assert cloned_attempt.file_document() == image

        bounded = ys.Policy()
        bounded.request.source.representation_bytes = 4
        incomplete = await ys.request.new(media_site).bind(bounded).send()
        with pytest.raises(FileDocumentError) as failure:
            incomplete.attempts[0].file_document()
        details = rust_error_details(failure.value)
        assert details is not None
        assert details.variant == "BodyUnavailable"

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="local Archive requires Unix")
def test_archive_round_trip_preserves_concrete_file_types_and_rejects_wrong_ref(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        archive = await ys.Archive.open(tmp_path / "archive")
        image = ys.file_from_bytes(
            "archived-image",
            PNG,
            metadata=ys.FileMetadata(
                filename="logo.png",
                declared_media_type="application/x-declared",
                source="offline-test",
            ),
        )
        binary = ys.file_from_bytes("archived-binary", OPAQUE)
        video = ys.file_from_bytes("archived-video", MP4)
        audio = ys.file_from_bytes("archived-audio", AUDIO)
        image_ref = await archive.write(image)
        binary_ref = await archive.write(binary)
        video_ref = await archive.write(video)
        audio_ref = await archive.write(audio)
        assert isinstance(image_ref, ImageDocumentArchiveRef)
        assert isinstance(binary_ref, BinaryDocumentArchiveRef)
        assert isinstance(video_ref, ys.VideoDocumentArchiveRef)
        assert isinstance(audio_ref, ys.AudioDocumentArchiveRef)

        reopened = await ys.Archive.open(archive.root)
        for reference in (image_ref, binary_ref, video_ref, audio_ref):
            recovered = TypeAdapter(FileDocumentArchiveRef).validate_json(
                reference.model_dump_json()
            )
            assert type(recovered) is type(reference)
            assert recovered == reference

        restored_image = await reopened.read(
            ImageDocumentArchiveRef.model_validate_json(image_ref.model_dump_json())
        )
        restored_binary = await reopened.read(binary_ref)
        restored_video = await reopened.read(video_ref)
        restored_audio = await reopened.read(audio_ref)
        assert isinstance(restored_image, ys.ImageDocument)
        assert isinstance(restored_binary, ys.BinaryDocument)
        assert isinstance(restored_video, ys.VideoDocument)
        assert isinstance(restored_audio, ys.AudioDocument)
        assert restored_image.id == image.id
        assert restored_image.metadata == image.metadata
        assert restored_image == image
        assert restored_image.bytes == image.bytes
        assert restored_binary.id == binary.id
        assert restored_binary.metadata == binary.metadata
        assert restored_binary.bytes == binary.bytes
        assert restored_video.metadata == video.metadata
        assert restored_video.bytes == video.bytes
        assert restored_audio.metadata == audio.metadata
        assert restored_audio.bytes == audio.bytes

        copied = image.model_copy(update={"id": "copied-image"})
        copied_ref = await archive.write(copied)
        assert (await archive.read(copied_ref)).id == "copied-image"
        forged = image.model_copy()
        object.__setattr__(forged, "id", "different-public-id")
        with pytest.raises(FileDocumentError):
            await archive.write(forged)

        with pytest.raises(ValidationError):
            ImageDocumentArchiveRef(value=binary_ref.value)
        with pytest.raises(TypeError):
            await reopened.read(binary_ref.value)  # ty: ignore[no-matching-overload] -- verify runtime rejection of untyped references

    asyncio.run(run())


def test_media_equality_uses_retained_values_not_handles_or_read_limits() -> None:
    first = ys.ImageDocument.from_bytes("same", PNG)
    second = ys.ImageDocument.from_bytes(
        "same", PNG, limits=ys.FileLimits(max_bytes=len(PNG))
    )
    assert first == second
    assert first.clone() == first
    assert first != ys.ImageDocument.from_bytes("different", PNG)
    assert first != ys.BinaryDocument.from_bytes("same", PNG)
