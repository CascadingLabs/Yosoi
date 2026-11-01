"""VideoSession cancellation reaches native tools and settles their owned cleanup."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from yosoi import _native
from yosoi import surface as sf
from yosoi.cancellation import CancellationToken
from yosoi.errors import rust_error_details

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not _native.surface_video_enabled,
    reason="executable fixtures and video archive support require a Unix video wheel",
)


def _tools(tmp_path: Path, monkeypatch, port: int, *, block_probe: bool) -> Path:
    """Install event-driven stand-ins; calls still cross the real native boundary."""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x10ftypmp42")
    metadata = {
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
                assert any(
                    receipt.result["command"]["op"] == "seek" for receipt in commands
                )
                rejected = next(
                    receipt
                    for receipt in commands
                    if receipt.result["command"]["op"] == operation
                )
                assert rejected.status == "Rejected"
                assert rejected.error == "video processing cancelled"
            finally:
                await session.close()

    asyncio.run(run())
