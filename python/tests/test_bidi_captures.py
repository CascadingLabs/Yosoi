"""Installed-client confirmation and Archive checks for optional native engines."""

import asyncio
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal, cast

import pytest

from yosoi.archive import Archive, AutomationRecord
from yosoi.browser import (
    BrowserConfig,
    Flow,
    JsonMatch,
    Navigate,
    Session,
    SessionPolicy,
    click,
    response,
)
from yosoi.policy import Acquisition, Page, Policy


@pytest.mark.skipif(
    os.environ.get("YOSOI_BIDI_TESTS") != "1",
    reason="requires explicitly installed qualified Firefox and Moli",
)
@pytest.mark.parametrize("engine", ["firefox", "moli"])
def test_native_until_body_and_protocol_scope_survive_archive(
    engine: Literal["firefox", "moli"], tmp_path: Path
) -> None:
    nonce = uuid.uuid4().hex
    mode = cast(
        Literal["headless", "headful"], os.environ.get("YOSOI_BIDI_MODE", "headless")
    )
    if engine == "moli" and mode == "headful":
        pytest.skip("Moli is headless-only")
    api_path = f"/api?nonce={nonce}"
    body = (
        "<!doctype html><meta charset='utf-8'><button id='capture'>Capture</button>"
        "<script>document.querySelector('#capture').onclick=()=>{"
        # Controlled app latency makes request start unambiguously later than
        # trigger start despite the protocol's millisecond timestamp precision.
        f"setTimeout(()=>fetch({json.dumps(api_path)},{{method:'POST'}}),20)"
        "};</script>"
    ).encode()
    payload = json.dumps({"status": "loaded", "nonce": nonce}).encode()
    calls: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            calls.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    policy = Policy(
        browser=BrowserConfig(
            engine=engine,
            moli_profile="layout" if engine == "moli" else "dom",
            moli_allow_private_networks=engine == "moli",
        ),
        page=Page(
            acquisitions=[Acquisition.browser(mode).with_documents(["rendered_dom"])]
        ),
        default_action_timeout_ms=5_000,
    )

    async def run() -> None:
        async with asyncio.timeout(30):
            async with Session(
                policy=policy,
                settings=SessionPolicy(mode=mode, operation_timeout_ms=5_000),
            ) as session:
                async with session.work() as work:
                    initial = await work.run(Flow(steps=(Navigate(url=origin),)))
                    assert initial.terminal == "completed"
                    outcome = await work.run(
                        Flow(
                            steps=(
                                click("#capture").until(
                                    response(
                                        origin + api_path,
                                        method="POST",
                                        status=200,
                                        json_matches=(
                                            JsonMatch(
                                                pointer="/status", value="loaded"
                                            ),
                                            JsonMatch(pointer="/nonce", value=nonce),
                                        ),
                                    )
                                ),
                            )
                        )
                    )
                    receipt = outcome.steps[-1].receipt
                    assert outcome.terminal == "completed", receipt.model_dump()
                    report = receipt.until_report()
                    assert report is not None
                    assert report.termination == "satisfied"
                    assert report.scope.protocol == "bidi"
                    assert report.scope.loader_id is None
                    assert report.scope.frame_id
                    assert receipt.browser is not None
                    assert receipt.browser.engine == engine
                    assert receipt.observation is not None
                    assert receipt.observation.browser == receipt.browser
                    assert calls == [api_path]
                    record = AutomationRecord.from_flow(
                        f"bidi-capture-{engine}", outcome
                    )
            archive = await Archive.open(tmp_path / "capture-archive")
            reference = await archive.write(record)
            restored = await archive.read(reference)
            assert isinstance(restored, AutomationRecord)
            assert restored.operations == record.operations
            assert restored.observations == record.observations

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
