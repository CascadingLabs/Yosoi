"""Opt-in real native Session consumption over an isolated loopback fixture."""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import unittest
from typing import Any, cast

import yosoi as ys


def as_json_object(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value)


async def target(source: ys.surface.BrowserSurface, query: str) -> dict[str, Any]:
    page = as_json_object(await source.execute({"op": "find", "query": query}))
    entry = page["entries"][0]
    if entry["kind"] == "text":
        return await source.execute({"op": "parent", "reference": entry["reference"]})
    return entry["reference"]


@unittest.skipUnless(
    os.environ.get("YOSOI_BROWSER_TESTS") == "1"
    and hasattr(ys._native, "surface_browser_consume_session"),
    "requires an explicit browser test grant and the current native extension",
)
class NativeSurfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_network_windows_and_body_sources_restore_offline(self):
        slow_started = asyncio.Event()
        release_slow = asyncio.Event()

        async def serve(reader, writer):
            try:
                request_line = await reader.readline()
                request = request_line.decode("ascii", errors="replace").split()
                path = request[1].split("?", 1)[0] if len(request) > 1 else "/"
                while await reader.readline() != b"\r\n":
                    pass
                if path == "/network":
                    body = (
                        b'<!doctype html><button aria-label="Start requests">Start requests</button>'
                        b'<button aria-label="Release slow request">Release slow request</button>'
                        b'<p id="state">ready</p><script>'
                        b"const s=document.getElementById('state');"
                        b"document.querySelectorAll('button')[0].addEventListener('click',()=>{"
                        b"s.textContent='requests started';const slow=fetch('/slow').then(r=>r.json());"
                        b"Promise.all([fetch('/api?token=secret'),fetch('/redirect'),"
                        b"fetch('/fail').catch(()=>null),"
                        b"fetch('/legacy-html').then(r=>r.text()),fetch('/sniff-html').then(r=>r.text()),"
                        b"fetch('/misleading-png').then(r=>r.arrayBuffer())])"
                        b".then(()=>slow).then(()=>{s.textContent='requests complete'})});"
                        b"document.querySelectorAll('button')[1].addEventListener('click',()=>fetch('/release'))"
                        b"</script>"
                    )
                    status = b"200 OK"
                    content_type = b"text/html; charset=utf-8"
                    headers = []
                elif path in {"/api", "/redirected"}:
                    body = b'{"api":true}' if path == "/api" else b'{"redirected":true}'
                    status = b"200 OK"
                    content_type = b"application/json; charset=utf-8"
                    headers = [(b"X-Public", b"kept"), (b"Set-Cookie", b"secret=hidden")]
                elif path == "/redirect":
                    body = b""
                    status = b"302 Found"
                    content_type = b"text/plain"
                    headers = [(b"Location", b"/redirected")]
                elif path == "/slow":
                    slow_started.set()
                    await release_slow.wait()
                    body = b'{"slow":true}'
                    status = b"200 OK"
                    content_type = b"application/json; charset=utf-8"
                    headers = []
                elif path == "/release":
                    release_slow.set()
                    body = b"released"
                    status = b"200 OK"
                    content_type = b"text/plain; charset=utf-8"
                    headers = []
                elif path == "/legacy-html":
                    body = b"<!doctype html><main><p>caf\xe9</p></main>"
                    status = b"200 OK"
                    content_type = b"text/html; charset=windows-1252"
                    headers = []
                elif path == "/sniff-html":
                    body = b"<!doctype html><main><p>sniffed HTML</p></main>"
                    status = b"200 OK"
                    content_type = None
                    headers = []
                elif path == "/misleading-png":
                    body = base64.b64decode(
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
                        "x8AAwMCAO+/p3sAAAAASUVORK5CYII="
                    )
                    status = b"200 OK"
                    content_type = b"application/octet-stream"
                    headers = []
                elif path == "/fail":
                    return
                else:
                    body = b"missing"
                    status = b"404 Not Found"
                    content_type = b"text/plain; charset=utf-8"
                    headers = []
                response = b"HTTP/1.1 " + status + b"\r\n"
                if content_type is not None:
                    response += b"Content-Type: " + content_type + b"\r\n"
                response += (
                    b"Content-Length: "
                    + str(len(body)).encode()
                    + b"\r\nConnection: close\r\n"
                )
                for name, value in headers:
                    response += name + b": " + value + b"\r\n"
                writer.write(response + b"\r\n" + body)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        with tempfile.TemporaryDirectory(prefix="yosoi-network-python-") as directory:
            archive_root = os.path.join(directory, "archive")
            output = os.path.join(directory, "surface")
            server = await asyncio.start_server(serve, "127.0.0.1", 0)
            async with server:
                base = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                policy = ys.surface.SurfacePolicy(
                    archive="enabled",
                    archive_root=archive_root,
                    output=output,
                    network_observation=ys.surface.NetworkObservationPolicy(
                        retain_bodies=True,
                        retain_url_path=True,
                        header_allowlist=("x-public", "set-cookie"),
                        max_windows=8,
                    ),
                )
                async with ys.browser.session() as browser:
                    source = await ys.browser.surface.consume_session(browser, policy)
                    ready = as_json_object(await source.ready())
                    self.assertEqual(ready["source"]["backend"], "native_session")
                    await source.execute({"op": "attach"})
                    await source.execute(
                        {"op": "focus", "reference": ready["state"]["root"]}
                    )
                    await source.execute({"op": "hot"})
                    await source.subscribe_network()
                    navigated = as_json_object(
                        await source.execute(
                            {
                                "op": "navigate",
                                "reference": ready["state"]["root"],
                                "url": base + "/network",
                            }
                        )
                    )
                    self.assertEqual(navigated["receipt"]["status"], "Confirmed")
                    start = await target(source, "Start requests")
                    clicked = as_json_object(
                        await source.execute(
                            {
                                "op": "click",
                                "reference": start,
                                "expect": {
                                    "kind": "text",
                                    "text": "requests started",
                                    "present": True,
                                },
                            }
                        )
                    )
                    self.assertEqual(clicked["receipt"]["status"], "Confirmed")
                    await asyncio.wait_for(slow_started.wait(), timeout=5)
                    after_sequence = 0
                    first_window = None
                    for _ in range(16):
                        waited = await source.wait_network_event(after_sequence, 5000)
                        self.assertEqual(waited["state"], "event")
                        after_sequence = waited["sequence"]
                        _, candidate = await source.observe_network()
                        if any(request.url.endswith("/slow") for request in candidate.in_flight):
                            first_window = candidate
                            break
                    self.assertIsNotNone(first_window)
                    first_window = cast(ys.surface.NetworkWindow, first_window)
                    self.assertFalse(first_window.coverage.complete)
                    self.assertTrue(first_window.coverage.start_boundary_unknown)
                    self.assertTrue(
                        any(request.url.endswith("/slow") for request in first_window.in_flight)
                    )
                    request_urls = [
                        event.kind.url
                        for event in first_window.events
                        if isinstance(event.kind, ys.surface.NetworkRequestStarted)
                    ]
                    self.assertTrue(all("token=secret" not in url for url in request_urls))
                    self.assertEqual(first_window.retention.retained_header_names, ("x-public",))

                    release = await target(source, "Release slow request")
                    released = as_json_object(
                        await source.execute(
                            {
                                "op": "click",
                                "reference": release,
                                "expect": {
                                    "kind": "text",
                                    "text": "requests complete",
                                    "present": True,
                                },
                            }
                        )
                    )
                    self.assertEqual(released["receipt"]["status"], "Confirmed")
                    await source.wait_network_event(after_sequence, 5000)
                    _, second_window = await source.observe_network()
                    self.assertTrue(
                        any(request.url.endswith("/slow") for request in second_window.in_flight_at_start)
                    )
                    self.assertFalse(
                        any(request.url.endswith("/slow") for request in second_window.in_flight)
                    )
                    events = (*first_window.events, *second_window.events)
                    self.assertTrue(
                        any(event.kind.kind == "redirect" for event in events)
                    )
                    self.assertTrue(any(event.kind.kind == "failed" for event in events))
                    body = next(
                        payload
                        for payload in (*first_window.payloads, *second_window.payloads)
                        if payload.document_kind == "json" and payload.state == "retained"
                    )
                    live_payload = await source.network_payload(body)
                    self.assertIn(b"\"api\":true", live_payload.value.data)
                    legacy_html = next(
                        payload
                        for payload in (*first_window.payloads, *second_window.payloads)
                        if payload.browser_effective_charset == "windows-1252"
                    )
                    self.assertEqual(legacy_html.document_kind, "html")
                    self.assertEqual(legacy_html.projection_basis, "requests_declared")
                    self.assertEqual(
                        legacy_html.declared_media_type,
                        "text/html; charset=windows-1252",
                    )
                    self.assertEqual(legacy_html.browser_effective_mime, "text/html")
                    self.assertEqual(
                        legacy_html.detected_media_type,
                        "text/html",
                    )
                    self.assertFalse(legacy_html.provider_base64_encoded)
                    self.assertTrue(legacy_html.text_utf8_normalized)
                    legacy_live = await source.network_payload(legacy_html)
                    self.assertIn("café".encode(), legacy_live.value.data)
                    sniffed_html = next(
                        payload
                        for payload in (*first_window.payloads, *second_window.payloads)
                        if payload.declared_media_type is None
                        and payload.document_kind == "html"
                    )
                    self.assertEqual(sniffed_html.detected_media_type, "text/html")
                    self.assertEqual(sniffed_html.projection_basis, "requests_sniffed")
                    misleading_png = next(
                        payload
                        for payload in (*first_window.payloads, *second_window.payloads)
                        if payload.declared_media_type == "application/octet-stream"
                    )
                    self.assertIsNotNone(misleading_png.browser_effective_mime)
                    self.assertEqual(misleading_png.detected_media_type, "image/png")
                    self.assertEqual(misleading_png.document_kind, "file")
                    self.assertEqual(misleading_png.projection_basis, "typed_file_magic")
                    outcome = await source.close()
                    self.assertIsNotNone(outcome)
                    outcome = cast(ys.surface.Outcome, outcome)
                    self.assertIn(body.id, {source.key for source in outcome.sources})
                    offline = outcome.network_payload(body)
                    self.assertEqual(offline.value, live_payload.value)
    async def test_facades_and_work_transfer_use_one_retained_native_session(self):
        body = (
            b"<!doctype html><h1>Native Python</h1>"
            b'<input aria-label="Message" value="existing">'
            b"<button onclick=\"this.nextElementSibling.textContent='Clicked'\">"
            b"Click here</button><p>Ready</p>"
        )

        async def serve(reader, writer):
            try:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + body
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        async with server:
            async with ys.browser.session() as browser:
                self.assertIs(
                    ys.browser.surface.consume_session, ys.surface.consume_session
                )
                source = await ys.browser.surface.consume_session(browser)
                try:
                    ready = as_json_object(await source.ready())
                    self.assertEqual(ready["source"]["backend"], "native_session")
                    await source.execute({"op": "attach"})
                    await source.execute(
                        {"op": "focus", "reference": ready["state"]["root"]}
                    )
                    await source.execute({"op": "hot"})
                    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
                    result = as_json_object(
                        await source.execute(
                            {
                                "op": "navigate",
                                "reference": ready["state"]["root"],
                                "url": url,
                            }
                        )
                    )
                    self.assertEqual(result["receipt"]["status"], "Confirmed")
                    field = await target(source, "Message")
                    result = as_json_object(
                        await source.execute(
                            {"op": "fill", "reference": field, "text": "replacement"}
                        )
                    )
                    self.assertEqual(result["receipt"]["status"], "Confirmed")
                    self.assertEqual(result["outcome"]["value"]["characters"], 11)
                    button = await target(source, "Click here")
                    result = as_json_object(
                        await source.execute(
                            {
                                "op": "click",
                                "reference": button,
                                "expect": {
                                    "kind": "text",
                                    "text": "Clicked",
                                    "present": True,
                                },
                            }
                        )
                    )
                    self.assertEqual(result["receipt"]["status"], "Confirmed")
                finally:
                    await source.close()
                work = browser.work()
                source = await ys.surface.BrowserSurface.consume_work(work)
                try:
                    self.assertTrue(work._released)
                    self.assertEqual(
                        as_json_object(await source.ready())["source"]["backend"],
                        "native_session",
                    )
                finally:
                    await source.close()
                async with browser.work():
                    pass


if __name__ == "__main__":
    unittest.main()
