"""Native video cancellation, processing bounds, cache and replay contracts."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import zlib
from pathlib import Path

import pytest

from yosoi import _native
from yosoi import surface as sf
from yosoi.archive import Archive
from yosoi.cancellation import CancellationToken
from yosoi.errors import rust_error_details

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not _native.surface_video_enabled,
    reason="executable fixtures and video archive support require a Unix video wheel",
)


def _metadata() -> dict:
    return {
        "format": {"format_name": "mov,mp4", "duration": "1"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "mpeg4",
                "width": 16,
                "height": 16,
                "duration": "1",
                "start_time": "0",
                "time_base": "1/10",
            }
        ],
    }


def _png() -> bytes:
    """Encode a tiny solid PNG fixture without launching an image/video tool."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            len(payload).to_bytes(4, "big")
            + kind
            + payload
            + zlib.crc32(kind + payload).to_bytes(4, "big")
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", (16).to_bytes(4, "big") * 2 + b"\x08\x06\x00\x00\x00")
        + chunk(b"IDAT", zlib.compress((b"\x00" + b"\xff\x00\x00\xff" * 16) * 16))
        + chunk(b"IEND", b"")
    )


def _tools(
    tmp_path: Path,
    monkeypatch,
    port: int,
    *,
    block_probe: bool,
    metadata: dict | None = None,
    decode_png: bytes | None = None,
) -> Path:
    """Install event-driven stand-ins; calls still cross the real native boundary."""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x10ftypmp42")
    metadata = _metadata() if metadata is None else metadata
    for name in ("ffmpeg", "ffprobe"):
        executable = tmp_path / name
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, os, socket, sys\n"
            "if '-version' in sys.argv:\n"
            "    print('ffmpeg version cancellation-fixture')\n"
            "    sys.exit(0)\n"
            f"if {name == 'ffprobe' and not block_probe!r}:\n"
            f"    print({json.dumps(metadata)!r})\n"
            "    sys.exit(0)\n"
            f"png = {decode_png!r}\n"
            "if png is not None and '-i' in sys.argv:\n"
            "    seek = sys.argv[sys.argv.index('-ss') + 1]\n"
            "    print('showinfo pts_time:' + seek, file=sys.stderr)\n"
            "    sys.stdout.buffer.write(png)\n"
            "    sys.exit(0)\n"
            "source = (sys.argv[sys.argv.index('-i') + 1] "
            "if '-i' in sys.argv else sys.argv[-1])\n"
            f"with socket.create_connection(('127.0.0.1', {port})) as stream:\n"
            "    stream.sendall((json.dumps({'pid': os.getpid(), 'source': source}) "
            "+ '\\n').encode())\n"
            "    stream.recv(1)\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        monkeypatch.setenv(f"YOSOI_{name.upper()}", str(executable))
    return source


async def _started(queue):
    reader, writer = await asyncio.wait_for(queue.get(), 5)
    message = json.loads(await asyncio.wait_for(reader.readline(), 5))
    return reader, writer, message


def _assert_reaped(pid: int) -> None:
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize("cancel_task", [True, False])
def test_video_session_open_cancels_ffprobe_and_reaps_before_return(
    tmp_path: Path, monkeypatch, cancel_task: bool
) -> None:
    async def run() -> None:
        queue = asyncio.Queue()
        server = await asyncio.start_server(
            lambda reader, writer: queue.put_nowait((reader, writer)),
            "127.0.0.1",
            0,
        )
        async with server:
            source = _tools(
                tmp_path,
                monkeypatch,
                server.sockets[0].getsockname()[1],
                block_probe=True,
            )
            parent = CancellationToken()
            task = asyncio.create_task(
                sf.VideoSession.open(source, cancellation=parent)
            )
            reader, writer, message = await _started(queue)
            if cancel_task:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
                assert not parent.cancelled
            else:
                parent.cancel()
                with pytest.raises(sf.ExecutionError) as error:
                    await asyncio.wait_for(task, 5)
                details = rust_error_details(error.value)
                assert details is not None and details.variant == "Operation"
                assert details.details["cancelled"] is True
            _assert_reaped(message["pid"])
            assert not Path(message["source"]).parent.exists()
            assert await asyncio.wait_for(reader.read(), 5) == b""
            writer.close()
            await writer.wait_closed()

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["frame", "crop"])
def test_video_session_execute_cancels_decoder_preserves_sibling_and_evidence(
    tmp_path: Path, monkeypatch, operation: str
) -> None:
    async def run() -> None:
        queue = asyncio.Queue()
        server = await asyncio.start_server(
            lambda reader, writer: queue.put_nowait((reader, writer)),
            "127.0.0.1",
            0,
        )
        async with server:
            source = _tools(
                tmp_path,
                monkeypatch,
                server.sockets[0].getsockname()[1],
                block_probe=False,
            )
            session = await sf.VideoSession.open(
                source,
                sf.SurfacePolicy(archive="enabled", output=tmp_path / "run"),
            )
            try:
                position = await session.execute({"op": "seek", "position_us": 0})
                command = {"op": operation, "reference": position["focus"]}
                if operation == "crop":
                    command["rect"] = {"x": 0, "y": 0, "width": 8, "height": 8}
                parent = CancellationToken()
                task = asyncio.create_task(
                    session.execute(command, cancellation=parent)
                )
                reader, writer, message = await _started(queue)
                sibling = asyncio.create_task(
                    session.execute(command, cancellation=parent)
                )
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
                _assert_reaped(message["pid"])
                assert await asyncio.wait_for(reader.read(), 5) == b""
                assert not parent.cancelled
                writer.close()
                await writer.wait_closed()
                sibling_reader, sibling_writer, sibling_message = await _started(queue)
                assert not sibling.done()
                parent.cancel()
                with pytest.raises(sf.ExecutionError) as error:
                    await asyncio.wait_for(sibling, 5)
                details = rust_error_details(error.value)
                assert details is not None and details.details["cancelled"] is True
                _assert_reaped(sibling_message["pid"])
                assert await asyncio.wait_for(sibling_reader.read(), 5) == b""
                sibling_writer.close()
                await sibling_writer.wait_closed()
                assert "cursor" in await session.execute({"op": "status"})
                outcome = await session.outcome()
                assert outcome is not None
                commands = [
                    receipt
                    for receipt in outcome.record.operations
                    if receipt.kind == "surface.command"
                ]
                command_results = []
                for receipt in commands:
                    assert receipt.result is not None
                    command_results.append((receipt, receipt.result))
                assert any(
                    result["command"]["op"] == "seek" for _, result in command_results
                )
                rejected = next(
                    receipt
                    for receipt, result in command_results
                    if result["command"]["op"] == operation
                )
                assert rejected.status == "rejected"
                assert rejected.error == "video processing cancelled"
            finally:
                await session.close()

    asyncio.run(run())


def test_video_duration_falls_back_to_container_without_claiming_stream_precision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    metadata = _metadata()
    del metadata["streams"][0]["duration"]
    metadata["format"]["duration"] = "1.75"
    source = _tools(tmp_path, monkeypatch, 0, block_probe=False, metadata=metadata)

    async def run() -> None:
        video = await sf.VideoSurface.open(source)
        assert video.metadata.duration_us == 1_750_000
        assert video.metadata.duration_estimated is True

    asyncio.run(run())


@pytest.mark.parametrize("maximum,accepted", [(1_000_000, True), (999_999, False)])
def test_video_source_duration_cap_is_inclusive(
    tmp_path: Path,
    monkeypatch,
    maximum: int,
    accepted: bool,
) -> None:
    source = _tools(tmp_path, monkeypatch, 0, block_probe=False)

    async def run() -> None:
        policy = sf.VideoPolicy(max_duration_us=maximum)
        if accepted:
            video = await sf.VideoSurface.open(source, policy)
            assert video.metadata.duration_us == maximum
        else:
            with pytest.raises(sf.VideoError) as error:
                await sf.VideoSurface.open(source, policy)
            details = rust_error_details(error.value)
            assert details is not None and details.variant == "Limit"

    asyncio.run(run())


@pytest.mark.parametrize(
    "width,height,accepted",
    [
        (4096, 4096, True),
        (4097, 4096, False),
        (4_294_967_295, 2, False),
        (0, 16, False),
    ],
)
def test_video_source_dimension_cap_applies_before_requested_frame_scaling(
    tmp_path: Path,
    monkeypatch,
    width: int,
    height: int,
    accepted: bool,
) -> None:
    metadata = _metadata()
    metadata["streams"][0]["width"] = width
    metadata["streams"][0]["height"] = height
    source = _tools(tmp_path, monkeypatch, 0, block_probe=False, metadata=metadata)

    async def run() -> None:
        policy = sf.VideoPolicy(frame_max_side=32)
        if accepted:
            video = await sf.VideoSurface.open(source, policy)
            assert (video.metadata.width, video.metadata.height) == (width, height)
        else:
            with pytest.raises(sf.VideoError) as error:
                await sf.VideoSurface.open(source, policy)
            details = rust_error_details(error.value)
            assert details is not None and details.variant == "Limit"

    asyncio.run(run())


def test_video_four_frame_cache_evicts_oldest_without_invalidating_returned_pixels(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _tools(tmp_path, monkeypatch, 0, block_probe=False, decode_png=_png())

    async def run() -> None:
        video = await sf.VideoSurface.open(source)
        oldest = await video.frame(video.at(0))
        for position in (100_000, 200_000, 300_000, 400_000):
            frame = await video.frame(video.at(position))
            assert frame.info.position_us == position
        (tmp_path / "ffmpeg").unlink()
        for position in (100_000, 200_000, 300_000, 400_000):
            frame = await video.frame(video.at(position))
            assert frame.png == oldest.png
            assert frame.info.position_us == position
        with pytest.raises(sf.VideoError) as error:
            await video.frame(video.at(0))
        details = rust_error_details(error.value)
        assert details is not None and details.variant == "Io"
        assert details.details["kind"] == "NotFound"
        assert oldest.png == _png()
        assert oldest.pixel_artifact is not None

    asyncio.run(run())


def test_video_decoder_identity_change_preserves_cached_frames_and_rejects_new_decode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _tools(tmp_path, monkeypatch, 0, block_probe=False, decode_png=_png())

    async def run() -> None:
        video = await sf.VideoSurface.open(source)
        frame = await video.frame(video.at(0))
        decoder = tmp_path / "ffmpeg"
        decoder.write_text(
            decoder.read_text().replace(
                "ffmpeg version cancellation-fixture", "ffmpeg version changed-fixture"
            )
        )
        cached = await video.frame(video.at(0))
        assert cached.png == frame.png
        assert cached.info == frame.info
        with pytest.raises(sf.VideoError) as error:
            await video.frame(video.at(500_000))
        details = rust_error_details(error.value)
        assert details is not None and details.variant == "Invalid"
        assert "decoder identity changed" in str(error.value)
        assert frame.png == _png()

    asyncio.run(run())


def test_video_timeout_reaps_owned_probe_before_error_returns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run() -> None:
        queue = asyncio.Queue()
        server = await asyncio.start_server(
            lambda reader, writer: queue.put_nowait((reader, writer)),
            "127.0.0.1",
            0,
        )
        async with server:
            source = _tools(
                tmp_path,
                monkeypatch,
                server.sockets[0].getsockname()[1],
                block_probe=True,
            )
            task = asyncio.create_task(
                sf.VideoSurface.open(source, sf.VideoPolicy(tool_timeout_ms=2000))
            )
            reader, writer, message = await _started(queue)
            with pytest.raises(sf.VideoError) as error:
                await asyncio.wait_for(task, 5)
            details = rust_error_details(error.value)
            assert details is not None and details.variant == "Timeout"
            _assert_reaped(message["pid"])
            assert not Path(message["source"]).parent.exists()
            assert await asyncio.wait_for(reader.read(), 5) == b""
            writer.close()
            await writer.wait_closed()

    asyncio.run(run())


def test_reopened_video_reports_absent_decoder_while_retained_pixels_replay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _tools(tmp_path, monkeypatch, 0, block_probe=False, decode_png=_png())

    async def run() -> None:
        video = await sf.VideoSurface.open(source)
        frame = await video.frame(video.at(0))
        archive = await Archive.open(tmp_path / "archive")
        saved = await video.write_to(archive)
        saved_frame = await frame.write_to(archive)
        source.unlink()
        (tmp_path / "ffmpeg").unlink()
        (tmp_path / "ffprobe").unlink()
        restored = await sf.VideoSurface.read_from(archive, saved)
        retained = await sf.DecodedFrame.read_from(archive, saved_frame)
        assert retained.png == frame.png
        assert retained.pixel_artifact is not None
        with pytest.raises(sf.VideoError) as error:
            await restored.frame(restored.at(500_000))
        details = rust_error_details(error.value)
        assert details is not None and details.variant == "Io"
        assert details.details["kind"] == "NotFound"
        assert retained.png == frame.png

    asyncio.run(run())
