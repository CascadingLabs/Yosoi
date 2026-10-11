"""Opt-in native-backed Until proof with a deterministic loopback fixture."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal

import pytest

from yosoi.browser import (
    Flow,
    JsonMatch,
    Navigate,
    Session,
    SessionPolicy,
    all_of,
    ax,
    click,
    response,
    visible,
)
from yosoi.cancellation import CancellationToken

pytestmark = pytest.mark.skipif(
    os.environ.get("YOSOI_BROWSER_TESTS") != "1",
    reason="requires an explicitly selected regular Stable browser",
)

EXPECTED_ORDER_ID = "order-74"
ORDER_URL_PATH = "/api/orders?cart=cart-74"
PAGE = b"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Until fixture</title></head>
<body>
  <button id="place-order" type="button">Place order</button>
  <div id="confirmation" role="status" aria-label="Order placed" hidden>
    Order placed
  </div>
  <button id="start-background-job" type="button">Start background job</button>
  <script>
    document.querySelector("#place-order").addEventListener("click", async () => {
      const url = "/api/orders?cart=cart-74";
      await fetch(url, {method: "POST", body: JSON.stringify({cart_id: "cart-74"})});
      const response = await fetch(url, {
        method: "POST", body: JSON.stringify({cart_id: "cart-74"})
      });
      const order = await response.json();
      if (order.order_id === "order-74") {
        const confirmation = document.querySelector("#confirmation");
        confirmation.dataset.orderId = order.order_id;
        confirmation.hidden = false;
      }
    });
    document.querySelector("#start-background-job").addEventListener("click", () => {
      fetch("/api/background-job", {method: "POST"});
    });
  </script>
</body>
</html>"""


def _yield_mode() -> Literal["headless", "headful"]:
    mode = os.environ.get("YOSOI_YIELD_MODE", "headless")
    if mode not in {"headless", "headful"}:
        raise ValueError("YOSOI_YIELD_MODE must be headless or headful")
    return mode


class FixtureState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.order_requests: list[tuple[str, bytes]] = []
        self.background_started = threading.Event()
        self.release_background = threading.Event()
        self.background_completed = threading.Event()


def fixture_server(state: FixtureState) -> ThreadingHTTPServer:
    class FixtureHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send_json(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PAGE)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(PAGE)

        def do_POST(self) -> None:
            size = int(self.headers.get("Content-Length", "0"))
            request_body = self.rfile.read(size)
            if self.path == ORDER_URL_PATH:
                with state.lock:
                    state.order_requests.append((self.path, request_body))
                    request_number = len(state.order_requests)
                order_id = "order-73" if request_number == 1 else EXPECTED_ORDER_ID
                self._send_json(201, {"order_id": order_id})
                return

            if self.path == "/api/background-job":
                state.background_started.set()
                state.release_background.wait(timeout=20)
                try:
                    self._send_json(202, {"status": "committed"})
                finally:
                    state.background_completed.set()
                return

            self._send_json(404, {"error": "not found"})

        def log_message(self, format: str, *args: object) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)


def _until_receipt(outcome: Any) -> Any:
    assert outcome.steps
    receipt = outcome.steps[-1].receipt
    assert receipt.kind == "until"
    report = receipt.until_report()
    assert report is not None
    return receipt, report


def _save_outcome(name: str, outcome: Any) -> None:
    directory = os.environ.get("YOSOI_BROWSER_OUTPUT_DIR")
    if directory is not None:
        Path(directory, f"{name}.json").write_text(
            json.dumps(
                {
                    "source_revision": os.environ.get("YOSOI_SPIKE_SOURCE_REVISION"),
                    "browser_identity": os.environ.get("YOSOI_SPIKE_BROWSER_IDENTITY"),
                    "outcome": json.loads(outcome.model_dump_json()),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def test_until_matches_business_identity_and_preserves_trigger_on_cancel() -> None:
    state = FixtureState()
    server = fixture_server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/"

    async def run() -> None:
        async with Session(
            settings=SessionPolicy(
                mode=_yield_mode(),
                maximum_tabs=1,
                execution_concurrency=1,
            )
        ) as session:
            async with session.work() as work:
                navigated = await work.run(Flow(steps=(Navigate(url=base_url),)))
                assert navigated.terminal == "completed"

                confirmation = await work.run(
                    Flow(
                        steps=(
                            click("#place-order").until(
                                all_of(
                                    (
                                        visible("#confirmation"),
                                        response(
                                            f"{base_url.rstrip('/')}{ORDER_URL_PATH}",
                                            method="POST",
                                            status=201,
                                            json_matches=(
                                                JsonMatch(
                                                    pointer="/order_id",
                                                    value=EXPECTED_ORDER_ID,
                                                ),
                                            ),
                                        ),
                                        ax("Order placed", role="status"),
                                    )
                                )
                            ),
                        )
                    )
                )
                _save_outcome("python-order-confirmation", confirmation)
                assert confirmation.terminal == "completed"
                _, report = _until_receipt(confirmation)
                assert report.termination == "satisfied"
                assert report.trigger is not None
                assert report.trigger.status == "observed"
                assert report.trigger.error is None
                assert isinstance(report.trigger.result, dict)
                assert report.trigger.result["started_at_unix_us"] > 0
                assert len(state.order_requests) == 2

                network = next(
                    check for check in report.checks if check.source == "network"
                )
                evidence = network.evidence
                assert network.state == "satisfied"
                assert isinstance(evidence, dict)
                assert evidence["url"] == f"{base_url.rstrip('/')}{ORDER_URL_PATH}"
                assert evidence["method"] == "POST"
                assert evidence["status"] == 201
                assert evidence["top_level"] is True
                assert evidence["request_id"]
                assert evidence["body"]["order_id"] == EXPECTED_ORDER_ID
                assert (
                    evidence["started_at_unix_us"]
                    >= report.trigger.result["started_at_unix_us"]
                )
                assert evidence["frame_id"] == report.scope.frame_id
                assert evidence["loader_id"] == report.scope.loader_id

                cancellation = CancellationToken()
                pending = asyncio.create_task(
                    work.run(
                        Flow(
                            steps=(
                                click("#start-background-job").until(
                                    response(
                                        f"{base_url.rstrip('/')}/api/background-job",
                                        method="POST",
                                        status=202,
                                    )
                                ),
                            )
                        ),
                        cancellation=cancellation,
                    )
                )
                started = await asyncio.wait_for(
                    asyncio.to_thread(state.background_started.wait, 10), timeout=12
                )
                assert started, "the browser did not dispatch the background request"
                cancellation.cancel()
                cancelled_or_unknown = await asyncio.wait_for(pending, timeout=15)
                _save_outcome("python-cancellation", cancelled_or_unknown)
                assert cancelled_or_unknown.terminal in {"cancelled", "unknown"}
                until_receipt, report = _until_receipt(cancelled_or_unknown)
                assert until_receipt.status in {"rejected", "unknown"}
                assert report.termination in {"cancelled", "unavailable"}
                assert report.termination != "satisfied"
                assert report.trigger is not None
                assert report.trigger.status in {"observed", "unknown"}
                if report.trigger.status == "observed":
                    assert report.trigger.error is None
                    assert isinstance(report.trigger.result, dict)
                    assert report.trigger.result["started_at_unix_us"] > 0

                # Cancellation can race with a live browser command because the
                # Python bridge does not expose a scheduler-parked barrier. The
                # conservative result may therefore be unknown and fence the
                # tab. Either result must retain the one trigger receipt.
                # Cancellation does not roll back work accepted by the server.
                state.release_background.set()
                completed = await asyncio.wait_for(
                    asyncio.to_thread(state.background_completed.wait, 10), timeout=12
                )
                assert completed

    try:
        asyncio.run(run())
    finally:
        state.release_background.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
