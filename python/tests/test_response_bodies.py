"""Complete binary body retention is independent of searchable documents."""

import asyncio
import gc
import gzip
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import yosoi as ys

ICON = (
    Path(__file__).parents[2] / "crates/yosoi/tests/fixtures/favicon.ico"
).read_bytes()


@pytest.fixture
def icon_site():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = ICON
            self.send_response(404 if self.path == "/missing" else 200)
            if self.path == "/empty":
                body = b""
            elif self.path == "/gzip":
                body = gzip.compress(ICON)
                self.send_header("Content-Encoding", "gzip")
            elif self.path == "/latin1":
                body = b"<h1>caf\xe9</h1>"
            self.send_header(
                "Content-Type",
                "text/html; charset=windows-1252"
                if self.path == "/latin1"
                else "image/x-icon",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
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


@pytest.mark.parametrize(
    "path,status", [("/icon", 200), ("/gzip", 200), ("/missing", 404)]
)
def test_complete_ico_body_survives_response_lifetime(icon_site, path, status):
    async def run():
        response = await ys.request.new(icon_site + path).send()
        attempt = response.attempts[0]
        assert attempt.http_status == status
        assert attempt.content_type == "image/x-icon"
        assert not response.documents
        assert "body" not in attempt.model_dump()
        assert "body" not in repr(attempt)
        assert attempt.clone().body == ICON
        del response
        gc.collect()
        assert attempt.body == ICON

    asyncio.run(run())


def test_original_body_and_normalized_document_are_distinct(icon_site):
    async def run():
        response = await ys.request.new(icon_site + "/latin1").send()
        assert response.attempts[0].body == b"<h1>caf\xe9</h1>"
        assert response.documents[0].data == "<h1>café</h1>".encode()
        empty = await ys.request.new(icon_site + "/empty").send()
        assert empty.attempts[0].body == b""
        token = ys.CancellationToken()
        token.cancel()
        cancelled = await ys.request.new(icon_site).send(cancellation=token)
        assert cancelled.attempts[0].body is None

    asyncio.run(run())


def test_truncated_body_is_not_returned_as_complete(icon_site):
    async def run():
        policy = ys.Policy()
        policy.request.source.representation_bytes = 3
        response = await ys.request.new(icon_site + "/icon").bind(policy).send()
        assert all(attempt.body is None for attempt in response.attempts)

    asyncio.run(run())
