"""Opt-in native-backed browser proof using a loopback fixture only."""

from __future__ import annotations

import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from yosoi.browser import (
    Assert,
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

pytestmark = pytest.mark.skipif(
    os.environ.get("YOSOI_BROWSER_TESTS") != "1",
    reason="requires an explicitly selected regular Stable browser",
)


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
