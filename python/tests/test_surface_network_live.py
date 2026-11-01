"""Opt-in public Python network capture and portable, browser-free replay."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import pytest

import yosoi as ys
from yosoi import surface as sf
from yosoi.errors import ArchiveError
from yosoi.policy import Acquisition, Page, Policy

pytestmark = pytest.mark.skipif(
    os.environ.get("YOSOI_BROWSER_TESTS") != "1",
    reason="requires an explicit grant to launch regular Stable Chrome",
)

JSON_BODY = b'{"schema":"yosoi.network.v1","native_python":true}'
FILE_BODY = b"\x00\xffnative-python-file\x00"
PAGE_BODY = b"""<!doctype html><main><h1>Native Python network</h1>
<p id="state">loading</p><script>
Promise.all([
  fetch('/json?token=private-query', {headers: {
    'X-Api-Token': 'never-store-request-token', 'X-Public': 'kept-request'
  }}).then(r => r.json()),
  fetch('/file?token=private-query').then(r => r.arrayBuffer())
]).then(() => {document.getElementById('state').textContent =
  'network payloads complete'});
</script></main>"""
SENSITIVE_HEADERS = (
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "cookie2",
    "x-api-key",
    "x-api-token",
    "x-access-token",
    "x-refresh-token",
    "x-session-token",
    "x-auth-token",
    "x-amz-security-token",
)


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return value


def _bytes(value: ys.Document | ys.FileDocument) -> bytes:
    return value.data if isinstance(value, ys.Document) else value.bytes


@dataclass
class _Fixture:
    base: str
    requests: list[tuple[str, dict[str, str]]]


@asynccontextmanager
async def _loopback() -> AsyncGenerator[_Fixture, None]:
    requests: list[tuple[str, dict[str, str]]] = []
    clients: set[asyncio.Task[None]] = set()
    errors: list[Exception] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        clients.add(task)
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            lines = head.decode("ascii").split("\r\n")
            _, target, _ = lines[0].split(" ")
            path = urlsplit(target).path
            headers = {
                name.lower(): value.strip()
                for line in lines[1:]
                if line
                for name, value in [line.split(":", 1)]
            }
            requests.append((path, headers))
            body, media_type = {
                "/capture": (PAGE_BODY, "text/html; charset=utf-8"),
                "/json": (JSON_BODY, "application/json; charset=utf-8"),
                "/file": (FILE_BODY, "application/octet-stream"),
            }.get(path, (b"missing", "text/plain; charset=utf-8"))
            response = (
                "HTTP/1.1 200 OK\r\nConnection: close\r\n"
                f"Content-Type: {media_type}\r\nContent-Length: {len(body)}\r\n"
                "X-Public: kept-response\r\nX-Custom-Token: kept-custom\r\n"
                + "".join(
                    f"{name}: never-store-{name}\r\n" for name in SENSITIVE_HEADERS
                )
                + "\r\n"
            )
            writer.write(response.encode("ascii") + body)
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        except Exception as error:
            errors.append(error)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            clients.discard(task)

    server = await asyncio.start_server(serve, "127.0.0.1", 0, limit=8192)
    try:
        address = server.sockets[0].getsockname()
        yield _Fixture(f"http://127.0.0.1:{address[1]}", requests)
    finally:
        server.close()
        await server.wait_closed()
        pending = tuple(clients)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        assert not errors, errors


async def _navigate(source: sf.BrowserSurface, url: str) -> None:
    await source.execute({"op": "refresh"})
    status = await source.execute({"op": "status"})
    result = await source.execute(
        {"op": "navigate", "reference": _object(status["root"]), "url": url}
    )
    assert _object(result["receipt"])["status"] == "Confirmed", result


async def _collect(
    source: sf.BrowserSurface, paths: set[str], *, retained: bool
) -> tuple[dict[str, sf.NetworkPayloadRef], tuple[sf.NetworkWindow, ...]]:
    requests: dict[tuple[str, int], str] = {}
    payloads: dict[str, sf.NetworkPayloadRef] = {}
    windows: list[sf.NetworkWindow] = []
    sequence = 0
    for _ in range(12):
        event = await source.wait_network_event(sequence, 5000)
        assert event["state"] == "event", event
        observed_sequence = event["sequence"]
        assert isinstance(observed_sequence, int)
        observation, window = await source.observe_network()
        assert observation.descriptor.representation == "yosoi.web.network.v1"
        assert window.session_id and window.tab_id
        assert not window.coverage.complete
        assert window.retention.retained_header_names == ("x-public", "x-custom-token")
        wire = window.model_dump_json()
        assert "private-query" not in wire
        assert "never-store-" not in wire
        for item in window.events:
            if isinstance(item.kind, sf.NetworkResponseReceived):
                path = urlsplit(item.kind.url).path
                if path in paths:
                    requests[(item.request_id, item.hop)] = path
                    headers = {
                        header.name: header.value for header in item.kind.headers
                    }
                    assert headers == {
                        "x-custom-token": "kept-custom",
                        "x-public": "kept-response",
                    }
        for payload in window.payloads:
            path = requests.get((payload.request_id, payload.hop))
            if (
                path is not None
                and path in paths
                and (
                    payload.state == "retained"
                    if retained
                    else payload.state == "not_requested"
                )
            ):
                payloads[path] = payload
        windows.append(window)
        sequence = max(observed_sequence, window.last_sequence or 0)
        if payloads.keys() >= paths:
            return payloads, tuple(windows)
    pytest.fail(
        f"missing network bodies: wanted={paths}; got={payloads}; windows={windows}"
    )


def test_native_python_network_capture_rearms_and_replays_without_browser(
    tmp_path: Path,
) -> None:
    async def run() -> tuple[Path, Path] | None:
        live_root = tmp_path / "live-archive"
        policy = sf.SurfacePolicy(
            archive="enabled" if os.name == "posix" else "off",
            archive_root=str(live_root),
            output=str(tmp_path / "surface"),
            network_observation=sf.NetworkObservationPolicy(
                retain_bodies=True,
                retain_url_path=True,
                max_windows=16,
                max_events=128,
                max_body_bytes=4096,
                max_total_body_bytes=16384,
                header_allowlist=(*SENSITIVE_HEADERS, "x-public", "x-custom-token"),
            ),
        )
        retained: list[sf.NetworkPayload] = []
        async with asyncio.timeout(60), _loopback() as fixture:
            launch = Policy(page=Page(acquisitions=[Acquisition.browser("headless")]))
            async with ys.browser.session(policy=launch) as browser:
                source = await sf.BrowserSurface.consume_session(browser, policy)
                async with source:
                    ready = await source.ready()
                    root = _object(_object(ready["state"])["root"])
                    assert _object(ready["source"])["backend"] == "native_session"
                    await source.execute({"op": "attach"})
                    await source.execute({"op": "focus", "reference": root})
                    await source.execute({"op": "hot"})
                    armed = await source.subscribe_network()
                    assert armed.active and armed.provider == "chrome_cdp"
                    await _navigate(
                        source, fixture.base + "/capture?token=private-query"
                    )
                    await source.execute(
                        {
                            "op": "wait",
                            "text": "network payloads complete",
                            "present": True,
                        }
                    )
                    references, windows = await _collect(
                        source, {"/capture", "/json", "/file"}, retained=True
                    )
                    for path, expected, kind in [
                        ("/capture", PAGE_BODY, "html"),
                        ("/json", JSON_BODY, "json"),
                        ("/file", FILE_BODY, "file"),
                    ]:
                        reference = references[path]
                        assert reference.document_kind == kind
                        payload = await source.network_payload(
                            reference, chunk_bytes=3 if kind == "file" else 17
                        )
                        assert _bytes(payload.value) == expected
                        retained.append(payload)
                    json_value = retained[1].value
                    assert isinstance(json_value, ys.Document)
                    assert json_value.profile.schema_profile == "json_rfc8259"
                    file_value = retained[2].value
                    assert isinstance(file_value, ys.BinaryDocument)
                    assert file_value.metadata.source is None
                    assert file_value.metadata.session_id == windows[0].session_id
                    assert file_value.metadata.tab_id == windows[0].tab_id
                    assert (
                        file_value.metadata.capture_id == references["/file"].request_id
                    )
                    assert any(
                        path == "/json"
                        and headers.get("x-api-token") == "never-store-request-token"
                        for path, headers in fixture.requests
                    )

                    await source.cancel_network()
                    disabled = await source.subscribe_network(retain_bodies=False)
                    assert not disabled.body_retention
                    assert disabled.session_max_total_body_bytes == 16384
                    await _navigate(source, fixture.base + "/json?phase=body-off")
                    omitted, _ = await _collect(source, {"/json"}, retained=False)
                    missing = omitted["/json"]
                    assert missing.reason == "body_retention_disabled"
                    assert missing.document_id is None and missing.sha256 is None
                    assert missing.retained_bytes == 0
                    with pytest.raises(sf.SurfaceError, match="not retained"):
                        await source.network_payload(missing)
                    await source.cancel_network()
                    assert (
                        _bytes(
                            (await source.network_payload(references["/file"])).value
                        )
                        == FILE_BODY
                    )

                    rearmed = await source.subscribe_network(retain_bodies=True)
                    assert rearmed.session_max_total_body_bytes == 16384
                    await _navigate(source, fixture.base + "/json?phase=rearmed")
                    fresh, fresh_windows = await _collect(
                        source, {"/json"}, retained=True
                    )
                    assert fresh["/json"].id != references["/json"].id
                    assert all(
                        window.coverage.network_was_previously_enabled
                        for window in fresh_windows
                    )
                    assert all(
                        not window.coverage.instrumentation_escalated
                        for window in fresh_windows
                    )
                    retained.append(await source.network_payload(fresh["/json"]))
                    outcome = await source.close()

        if os.name != "posix":
            assert outcome is None
            with pytest.raises(ArchiveError, match="not certified"):
                await ys.Archive.open(tmp_path / "unsupported-archive")
            return None
        assert outcome is not None and outcome.complete and outcome.sealed
        entries = []
        for live in retained:
            offline = outcome.network_payload(live.reference)
            assert _bytes(offline.value) == _bytes(live.value)
            metadata = None
            if isinstance(live.value, ys.BinaryDocument):
                assert isinstance(offline.value, ys.BinaryDocument)
                assert offline.value.metadata == live.value.metadata
                metadata = live.value.metadata.model_dump(mode="json")
            entries.append(
                {
                    "reference": live.reference.model_dump(mode="json"),
                    "bytes": base64.b64encode(_bytes(live.value)).decode("ascii"),
                    "metadata": metadata,
                }
            )
        archive = await ys.Archive.open(tmp_path / "portable-archive")
        reference = await archive.write(outcome)
        portable = tmp_path / "network.yosoi"
        await archive.export_file(reference, portable)
        manifest = tmp_path / "expected-network.json"
        manifest.write_text(json.dumps(entries), encoding="utf-8")
        shutil.rmtree(live_root)
        shutil.rmtree(archive.root)
        return portable, manifest

    portable = asyncio.run(run())
    if portable is None:
        return
    replay = subprocess.run(
        [
            sys.executable,
            "-c",
            r"""
import asyncio, base64, json, sys
import yosoi as ys
from yosoi import surface as sf
async def run():
    archive = await ys.Archive.open(sys.argv[3])
    reference = await archive.import_file(sys.argv[1])
    outcome = await archive.read(reference)
    entries = json.loads(open(sys.argv[2], encoding='utf-8').read())
    for entry in entries:
        reference = sf.NetworkPayloadRef.model_validate(entry['reference'])
        payload = outcome.network_payload(reference)
        value = payload.value
        data = value.data if isinstance(value, ys.Document) else value.bytes
        assert data == base64.b64decode(entry['bytes'])
        if entry['metadata'] is not None:
            assert value.metadata.model_dump(mode='json') == entry['metadata']
            assert value.metadata.source is None
    print(f'offline network payloads restored: {len(entries)}')
asyncio.run(run())
""",
            str(portable[0]),
            str(portable[1]),
            str(tmp_path / "fresh-archive"),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert replay.returncode == 0, replay.stderr
    assert "offline network payloads restored: 4" in replay.stdout
