import asyncio
import gc
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import yosoi as ys
from yosoi import _native
from yosoi.errors import RequestError, SearchError
from yosoi.policy import Map, Policy, ProviderSelection, Search


@pytest.fixture
def site() -> Iterator[tuple[str, threading.Event, threading.Event]]:
    seen = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/slow":
                seen.set()
                if not release.wait(10):
                    return
            if self.path == "/robots.txt":
                body, content_type = b"User-agent: *\nAllow: /\n", "text/plain"
            elif self.path == "/sitemap.xml":
                body, content_type = b"", "application/xml"
            else:
                body = b'<html><h1>SDK</h1><a href="/next">Next</a></html>'
                content_type = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(10)
        assert not worker.is_alive()


def test_request_retains_documents_and_identity_after_response_is_deleted(site) -> None:
    base, _, _ = site

    async def run() -> None:
        policy = ys.Policy()
        request = ys.request.new(base)
        response = await asyncio.wait_for(request.bind(policy).send(), 10)
        assert response.request_id == request.id
        assert response.termination == "completed"
        assert response.policy_snapshot.identity == policy.identity()
        assert response.attempts[0].state == "completed"
        assert response.attempts[0].http_status == 200
        document = response.documents[0]
        del response
        gc.collect()
        plan = ys.Plan(outputs=[ys.output("title", ys.css("h1").text())])
        assert document.locate(plan).values() == ["SDK"]
        with document.parse() as parsed:
            assert parsed.locate(plan).values() == ["SDK"]
        await asyncio.wait_for(_native.wait_for_idle(), 10)

    asyncio.run(run())


def test_python_task_cancellation_finishes_rust_cleanup(site) -> None:
    base, seen, release = site

    async def run() -> None:
        task = asyncio.create_task(ys.request.new(base + "/slow").send())
        assert await asyncio.to_thread(seen.wait, 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(_native.wait_for_idle(), 10)
        release.set()

    asyncio.run(run())


def test_sdk_cancellation_returns_typed_responses(
    site,
) -> None:
    base, _, _ = site

    async def run() -> None:
        token = ys.CancellationToken()
        response = await asyncio.wait_for(
            ys.request.new(base).send(cancellation=token), 10
        )
        assert response.termination == "completed"
        assert not token.cancelled
        token.cancel()
        cancelled = await asyncio.wait_for(
            ys.request.new(base).send(cancellation=token), 10
        )
        assert cancelled.termination == "cancelled"
        assert cancelled.attempts[0].state == "not_started"
        assert cancelled.attempts[0].not_started_reason == "cancelled"
        await asyncio.wait_for(_native.wait_for_idle(), 10)

    asyncio.run(run())


def test_map_discovery_and_retained_capture_ownership(site) -> None:
    base, _, _ = site

    async def run() -> None:
        policy = Policy(map=Map(documents="retain_within_budget"))
        policy.map.limits.max_requests = 6
        policy.map.limits.max_link_depth = 1
        outcome = await asyncio.wait_for(ys.map.new(base).bind(policy).send(), 10)
        assert any(page.url == base + "/next" for page in outcome.pages)
        assert outcome.summary.requests <= 6
        assert outcome.policy_snapshot.identity == policy.identity()
        assert outcome.captures
        document = next(
            capture.response.documents[0]
            for capture in outcome.captures
            if capture.response.documents
            and capture.response.documents[0].document_class == "source_html"
        )
        del outcome
        gc.collect()
        plan = ys.Plan(outputs=[ys.output("title", ys.css("h1").text())])
        assert document.locate(plan).values() == ["SDK"]
        await asyncio.wait_for(_native.wait_for_idle(), 10)

    asyncio.run(run())


def test_search_preserves_provider_order_when_cancelled_before_io() -> None:
    async def run() -> None:
        policy = Policy(
            search=Search(
                providers=[
                    ProviderSelection(provider="bing"),
                    ProviderSelection(provider="brave"),
                ]
            )
        )
        token = ys.CancellationToken()
        token.cancel()
        request = ys.search.new("rust sdk")
        response = await asyncio.wait_for(
            request.bind(policy).send(cancellation=token), 10
        )
        assert response.request_id == request.id
        assert [item.provider for item in response.providers] == ["bing", "brave"]
        assert response.termination == "cancelled"
        assert all(
            item.outcome.status in ("cancelled", "not_started")
            for item in response.providers
        )
        assert all(item.charge.status == "unknown" for item in response.providers)
        await asyncio.wait_for(_native.wait_for_idle(), 10)

    asyncio.run(run())


def test_invalid_request_and_search_preflight_raise_public_exceptions() -> None:
    with pytest.raises(RequestError):
        ys.request.new("ftp://example.org").check()
    with pytest.raises(SearchError):
        ys.search.new(" ")
    with pytest.raises(SearchError):
        ys.search.new("valid").bind(Policy(search=Search(providers=[]))).check()


def test_cancelling_one_task_keeps_its_shared_token_sibling_running() -> None:
    async def run() -> None:
        ready = asyncio.Event()
        release = asyncio.Event()
        connections = 0

        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            nonlocal connections
            try:
                await reader.readuntil(b"\r\n\r\n")
                connections += 1
                if connections == 2:
                    ready.set()
                await release.wait()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                    b"Content-Length: 11\r\nConnection: close\r\n\r\n<h1>OK</h1>"
                )
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        parent = ys.CancellationToken()
        first = asyncio.create_task(
            ys.request.new(f"http://127.0.0.1:{port}/one").send(cancellation=parent)
        )
        second = asyncio.create_task(
            ys.request.new(f"http://127.0.0.1:{port}/two").send(cancellation=parent)
        )
        try:
            await asyncio.wait_for(ready.wait(), 10)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert not parent.cancelled
            release.set()
            result = await asyncio.wait_for(second, 10)
            assert result.termination == "completed"
            assert result.attempts[0].http_status == 200
            assert not parent.cancelled
        finally:
            release.set()
            first.cancel()
            second.cancel()
            await asyncio.gather(first, second, return_exceptions=True)
            server.close()
            await server.wait_closed()
            await asyncio.wait_for(_native.wait_for_idle(), 10)

    asyncio.run(run())
