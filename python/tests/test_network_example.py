"""Exercise the documented Python entry point through real local sockets."""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).parents[1] / "examples" / "networking.py"
RESPONSE = (
    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 15\r\n"
    b"Connection: close\r\n\r\n<h1>route</h1>\n"
)


@pytest.mark.parametrize(
    "source,family", [("127.0.0.1", "ipv4_only"), ("::1", "ipv6_only")]
)
def test_python_network_example_binds_the_requested_source(
    source: str, family: str
) -> None:
    async def run() -> None:
        observed = asyncio.get_running_loop().create_future()

        async def serve(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                await reader.readuntil(b"\r\n\r\n")
                observed.set_result(writer.get_extra_info("peername")[0])
                writer.write(RESPONSE)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(serve, source, 0)
        try:
            port = server.sockets[0].getsockname()[1]
            host = f"[{source}]" if ":" in source else source
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(EXAMPLE),
                f"http://{host}:{port}/route",
                "--ip-family",
                family,
                "--source-address",
                source,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            assert process.returncode == 0, stderr.decode()
            result = json.loads(stdout)
            assert result["ip_family"] == family
            assert result["proxy_configured"] is False
            assert result["attempts"][0]["http_status"] == 200
            assert await asyncio.wait_for(observed, 2) == source
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_python_network_example_uses_authenticated_proxy_environment() -> None:
    async def run() -> None:
        observed = asyncio.get_running_loop().create_future()

        async def proxy(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                connect = await reader.readuntil(b"\r\n\r\n")
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                request = await reader.readuntil(b"\r\n\r\n")
                observed.set_result((connect, request))
                writer.write(RESPONSE)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(EXAMPLE),
                "http://no-dns.invalid/route",
                "--ip-family",
                "ipv4_only",
                "--proxy-env",
                env=dict(
                    os.environ,
                    YOSOI_PROXY_URL=f"http://user:fixture-secret@127.0.0.1:{port}",
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            assert process.returncode == 0, stderr.decode()
            result = json.loads(stdout)
            assert result["proxy_configured"] is True
            assert result["attempts"][0]["http_status"] == 200
            connect, request = await asyncio.wait_for(observed, 2)
            assert connect.startswith(b"CONNECT no-dns.invalid:80 HTTP/1.1")
            assert (
                b"Proxy-Authorization: Basic "
                + base64.b64encode(b"user:fixture-secret")
            ) in connect
            assert b"proxy-authorization" not in request.lower()
            assert b"fixture-secret" not in stdout + stderr
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())
