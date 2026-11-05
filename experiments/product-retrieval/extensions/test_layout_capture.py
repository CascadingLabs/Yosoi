"""Capture boundaries and CDP routing without launching a browser."""

import asyncio
import json

import layout_capture as capture
import pytest


def test_browser_commands_omit_page_session_and_events_are_retained():
    class Socket:
        def __init__(self):
            self.sent = []
            self.messages = iter(
                [
                    {"method": "Page.loadEventFired", "sessionId": "page"},
                    {"id": 1, "result": {}},
                    {"id": 2, "result": {}},
                ]
            )

        async def send(self, value):
            self.sent.append(json.loads(value))

        async def recv(self):
            return json.dumps(next(self.messages))

    async def run():
        socket = Socket()
        client = capture.CdpClient(socket)
        client.session_id = "page"
        await client.command("Page.enable")
        await client.command("Browser.close", session_id=None)
        assert socket.sent[0]["sessionId"] == "page"
        assert "sessionId" not in socket.sent[1]
        assert (await client.event(1))["method"] == "Page.loadEventFired"

    asyncio.run(run())


def test_plan_uses_current_urls_without_reusing_old_dom_coordinates():
    plan = capture.build_capture_plan(
        {
            "pages": [
                {"id": name, "requested_url": f"https://example.com/{name}"}
                for name in capture.FRESH_IDS
            ]
        }
    )
    assert len(plan) == 4
    assert all(row["capture_mode"] == "live_navigation" for row in plan)
    assert plan[0]["saved_reference_kind"] == "archived_rendered_dom_not_raw_html"


def test_admission_expires_and_launch_keeps_sandbox(tmp_path, monkeypatch):
    binary = tmp_path / "browser"
    binary.touch()
    args = capture.build_chrome_args(binary, tmp_path, 54321)
    assert not any(arg.startswith("--no-sandbox") for arg in args)
    assert not any(arg.startswith("--load-extension") for arg in args)
    monkeypatch.setattr(capture.time, "time", lambda: capture.REVIEWED_AT + 1)
    assert capture._admitted("Chromium 155.0.8059.84")
    assert not capture._admitted("Chrome for Testing 155.0.8059.84")
    monkeypatch.setattr(
        capture.time, "time", lambda: capture.REVIEWED_AT + capture.MAX_AGE + 1
    )
    assert not capture._admitted("Chromium 155.0.8059.84")


def test_run_calls_the_real_capture_boundary_once_per_page(tmp_path, monkeypatch):
    monkeypatch.setattr(
        capture, "_browser_identity", lambda path: "Chromium 155.0.8059.84"
    )
    monkeypatch.setattr(capture, "_admitted", lambda identity: True)
    monkeypatch.setattr(capture, "_load_ws", lambda: (None, "15.0.1"))
    monkeypatch.setattr(capture, "load_capture_plan", lambda root: [{"case_id": "one"}])
    monkeypatch.setattr(capture, "_runtime_metadata", dict)
    monkeypatch.setattr(capture, "_sha256_file", lambda path: "test-hash")
    observed = []

    async def one(spec, *, chrome, output_root, timeout, connect, viewport):
        observed.append(spec["case_id"])
        assert viewport == {"width": 390, "height": 844, "device_scale_factor": 1.0}
        return {"case_id": spec["case_id"], "status": "complete"}

    monkeypatch.setattr(capture, "_launch_and_capture_one", one)
    result = capture.run_capture(
        tmp_path / "capture",
        tmp_path / "browser",
        viewport={"width": 390, "height": 844, "device_scale_factor": 1.0},
    )
    assert observed == ["one"]
    assert result["status"] == "complete"
    assert result["gold_mapping"].startswith("not loaded")


def test_invalid_viewport_is_rejected_before_launch():
    with pytest.raises(ValueError, match="dimensions"):
        capture.validated_viewport(
            {"width": -1, "height": 844, "device_scale_factor": 1}
        )
