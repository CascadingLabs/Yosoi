"""Exercise browser Actions and Sessions against the shared local fixture."""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from yosoi.browser import (
    Assert,
    Click,
    CountAtLeast,
    EnterText,
    Exists,
    Flow,
    Navigate,
    Screenshot,
    Session,
    SessionPolicy,
    WaitUntil,
    action,
)
from yosoi.policy import Policy

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


async def run(url: str, drift_url: str) -> None:
    policy = Policy()
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
    managed = await action(url, checked_flow, policy=policy)
    if managed.terminal != "completed":
        raise RuntimeError("shared fixture baseline Flow did not complete")
    print("Shared fixture baseline Action:")
    print(managed.model_dump_json(indent=2))

    drift = await action(drift_url, checked_flow, policy=policy)
    expected_failure = {
        "passed": False,
        "expected": {
            "kind": "count_at_least",
            "selector": ".row",
            "count": 12,
        },
        "actual": 4,
    }
    if (
        drift.terminal != "failed"
        or drift.steps[-1].receipt.kind != "assert"
        or drift.steps[-1].receipt.status != "rejected"
        or drift.steps[-1].receipt.result != expected_failure
    ):
        raise RuntimeError("controlled drift did not retain the typed failed assertion")
    capture = drift.failure_capture
    if capture is None or capture.kind not in {
        "screenshot",
        "failure_capture:screenshot",
    }:
        raise RuntimeError("controlled drift did not retain its screenshot receipt")
    if capture.status == "observed":
        if capture.observation is None or capture.observation.screenshot_bytes is None:
            raise RuntimeError("observed failure screenshot has no screenshot bytes")
    elif capture.status not in {"unknown", "rejected"}:
        raise RuntimeError("failure screenshot receipt has an invalid status")
    print("Shared fixture controlled drift Action:")
    print(drift.model_dump_json(indent=2))

    async with Session(policy=policy, settings=SessionPolicy()) as session:
        async with session.work() as work:
            explicit = await work.run(
                Flow(
                    steps=(
                        Navigate(url=url),
                        WaitUntil(
                            condition=Exists(selector="#status"),
                            timeout_ms=5_000,
                        ),
                        Assert(condition=Exists(selector="#status")),
                    )
                )
            )
            print("Explicit Session and Work:")
            print(explicit.model_dump_json(indent=2))


def main() -> None:
    server = fixture_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    drift_url = f"{url}?variant=drift"
    try:
        asyncio.run(run(url, drift_url))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
