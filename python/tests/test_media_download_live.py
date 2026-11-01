"""Installed Python download ownership, cancellation and native Archive journey."""

from __future__ import annotations

import asyncio
import os
import struct
from pathlib import Path

import pytest

import yosoi as ys
from yosoi.policy import Acquisition, Page, Policy

pytestmark = pytest.mark.skipif(
    os.environ.get("YOSOI_BROWSER_TESTS") != "1",
    reason="requires an explicitly selected regular Stable browser",
)

WAV = (
    b"RIFF"
    + struct.pack("<I", 44)
    + b"WAVEfmt "
    + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 8000, 1, 8)
    + b"data"
    + struct.pack("<I", 8)
    + b"\x80" * 8
)
PAGE = b'<html><body><a id="download" href="/file">Get audio</a></body></html>'


def test_native_python_cancel_then_authenticated_audio_archive(tmp_path: Path) -> None:
    async def run() -> None:
        async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            try:
                head = await reader.readuntil(b"\r\n\r\n")
                path = head.split(b" ", 2)[1]
                if path == b"/file":
                    assert b"cookie: auth=allowed" in head.lower()
                    body = WAV
                    extra = (
                        b"Content-Type: audio/wav\r\n"
                        b"Content-Disposition: attachment; filename=tone.wav\r\n"
                    )
                else:
                    body = PAGE
                    extra = (
                        b"Content-Type: text/html\r\n"
                        b"Set-Cookie: auth=allowed; Path=/; SameSite=Lax\r\n"
                    )
                writer.write(
                    b"HTTP/1.1 200 OK\r\nConnection: close\r\n"
                    + extra
                    + f"Content-Length: {len(body)}\r\n\r\n".encode()
                    + body
                )
                await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        try:
            address = server.sockets[0].getsockname()
            url = f"http://127.0.0.1:{address[1]}/"
            policy = Policy(page=Page(acquisitions=[Acquisition.browser()]))
            async with ys.session(policy=policy) as session:
                async with session.work() as work:
                    (await work.run(ys.flow([ys.navigate(url)]))).require_completed()
                    async with work.expect_download() as canceled:
                        entered = asyncio.Event()

                        async def wait_for_file():
                            entered.set()
                            return await canceled.wait()

                        waiting = asyncio.create_task(wait_for_file())
                        await entered.wait()
                        waiting.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await waiting
                    async with work.expect_download() as capture:
                        outcome = await work.run(ys.flow([ys.click("#download")]))
                        outcome.require_completed()
                        file = await capture.wait()
            assert isinstance(file, ys.AudioDocument)
            assert file.bytes == WAV
            assert file.metadata.filename == "tone.wav"
            assert file.metadata.source is not None
            assert file.metadata.source.endswith("/file")
            archive = await ys.Archive.open(tmp_path / "archive")
            reference = await archive.write(file)
            assert isinstance(reference, ys.AudioDocumentArchiveRef)
            restored = await archive.read(reference)
            assert restored == file
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())
