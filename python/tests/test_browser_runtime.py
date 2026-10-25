"""Opt-in native-backed browser proof using a loopback fixture only."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from yosoi import request
from yosoi.browser import (
    Assert,
    BrowserError,
    Click,
    CountAtLeast,
    EnterText,
    Evaluate,
    Exists,
    Flow,
    Navigate,
    Screenshot,
    Session,
    SessionPolicy,
    Wait,
    WaitUntil,
    action,
)
from yosoi.cancellation import CancellationToken
from yosoi.errors import RequestError
from yosoi.policy import Acquisition, Network, Page, Policy

pytestmark = pytest.mark.skipif(
    os.environ.get("YOSOI_BROWSER_TESTS") != "1",
    reason="requires an explicitly selected regular Stable browser",
)


def test_network_session_binds_ipv6_source_and_rejects_route_changes() -> None:
    async def run() -> None:
        observed = asyncio.get_running_loop().create_future()

        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                await reader.readuntil(b"\r\n\r\n")
                if not observed.done():
                    observed.set_result(writer.get_extra_info("peername")[0])
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                    b"Content-Length: 15\r\nConnection: close\r\n\r\n<h1>route</h1>\n"
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, "::1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            policy = Policy(
                network=Network(ip_family="ipv6_only", source_address="::1"),
                page=Page(acquisitions=[Acquisition.browser()]),
            )
            async with Session(policy=policy) as session:
                response = (
                    await request.new(f"http://[::1]:{port}/route")
                    .in_session(session)
                    .send()
                )
                assert response.attempts[0].state == "completed"
                document = response.attempts[0].documents[0].outcome.document
                assert document is not None
                tree = json.loads(document.data)
                assert any(
                    node.get("kind") == "text" and node.get("value") == "route"
                    for node in tree["nodes"]
                )
                assert await asyncio.wait_for(observed, 5) == "::1"
                changed = Policy.model_validate_json(policy.to_json())
                changed.network = Network(ip_family="ipv4_only")
                with pytest.raises(RequestError, match="network policy differs"):
                    await (
                        request.new("http://127.0.0.1/")
                        .bind(changed)
                        .in_session(session)
                        .send()
                    )
                with pytest.raises(BrowserError) as rejected:
                    await session.run(Flow(steps=()), policy=changed)
                assert rejected.value.rust_variant == "session"
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(asyncio.wait_for(run(), 30))


FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "spikes"
    / "browser-automation"
    / "fixtures"
    / "session-flow.html"
)


def fixture_server() -> ThreadingHTTPServer:
    body = FIXTURE_PATH.read_bytes()

    class FixtureHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)


def test_managed_and_explicit_flows_use_the_native_session_engine() -> None:
    server = fixture_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    drift_url = f"{url}?variant=drift"
    checked_flow = Flow(
        steps=(
            Click(selector="#advance"),
            EnterText(selector="#query", text="shared fixture input"),
            WaitUntil(
                condition=Exists(selector="#status.ready"),
                timeout_ms=5_000,
            ),
            Assert(condition=CountAtLeast(selector=".row", count=12)),
            Screenshot(),
        ),
        capture_on_failure="screenshot",
    )

    async def run() -> None:
        outcome = await action(url, checked_flow)
        assert outcome.terminal == "completed"
        assert any(
            step.receipt.observation and step.receipt.observation.screenshot_bytes
            for step in outcome.steps
        )

        failed = await action(drift_url, checked_flow)
        assert failed.terminal == "completed_with_issues"
        failed_assertion = next(
            step for step in failed.steps if step.receipt.kind == "assert"
        )
        assert failed_assertion.receipt.status == "rejected"
        assert failed_assertion.receipt.result == {
            "passed": False,
            "expected": {
                "kind": "count_at_least",
                "selector": ".row",
                "count": 12,
            },
            "actual": 4,
        }
        assert failed.steps[-1].receipt.kind == "screenshot"
        assert failed.steps[-1].receipt.status == "observed"
        capture = failed.failure_capture
        assert capture is not None
        assert capture.kind in {"screenshot", "failure_capture:screenshot"}
        if capture.status == "observed":
            assert capture.observation is not None
            assert capture.observation.screenshot_bytes is not None
        else:
            assert capture.status in {"unknown", "rejected"}

        default_settings = SessionPolicy()
        js_settings = SessionPolicy(
            allow_arbitrary_js=True,
            allowed_actions=(*default_settings.allowed_actions, "evaluate"),
        )
        async with Session(settings=js_settings) as session:
            async with session.work() as work:
                explicit = await work.run(
                    Flow(
                        steps=(
                            Navigate(url=url),
                            Evaluate(source="document.body.dataset.probe='yes'; 40+2"),
                        )
                    )
                )
                assert explicit.terminal == "completed"
                assert explicit.steps[-1].receipt.result == 42
                observation = explicit.steps[-1].receipt.observation
                assert observation is not None
                assert observation.html is not None
                assert "data-probe" in observation.html

                token = CancellationToken()
                flow = Flow(
                    steps=(
                        Wait(milliseconds=1_000),
                        Evaluate(source="document.body.dataset.cancelled='bad'"),
                    )
                )
                pending = asyncio.create_task(work.run(flow, cancellation=token))
                await asyncio.sleep(
                    0.05
                )  # Explicit cancellation timing, not browser readiness.
                token.cancel()
                cancelled = await pending
                assert cancelled.terminal == "cancelled"
                assert len(cancelled.steps) == 1

                # Cancelling this Flow does not revoke caller-owned Work.
                resumed = await work.run(
                    Flow(steps=(Assert(condition=Exists(selector="body")),))
                )
                assert resumed.terminal == "completed"

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
