"""Opt-in native observation acceptance through the public Python Session API."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from contextlib import AsyncExitStack
from pathlib import Path

import yosoi as ys
from yosoi.browser import RecordingOutcome, SessionEvidence, SessionPolicy
from yosoi.policy import (
    Acquisition,
    ObservePolicy,
    Page,
    Policy,
    RecordingRule,
    ScreenshotPolicy,
)


@unittest.skipUnless(
    os.environ.get("YOSOI_BROWSER_TESTS") == "1",
    "requires an explicit regular-Chrome/Xvfb/FFmpeg browser test grant",
)
class NativeObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_records_four_tabs_and_preserves_closed_evidence(self):
        fixture = (
            Path(__file__).resolve().parents[2]
            / "crates/yosoi/tests/fixtures/session-observation.html"
        ).read_bytes()

        async def serve(reader, writer):
            try:
                request = await reader.readuntil(b"\r\n\r\n")
                path = request.split(b" ", 2)[1]
                body = (
                    b"ok"
                    if path.startswith((b"/paint", b"/wait", b"/release"))
                    else fixture
                )
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
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        address = server.sockets[0].getsockname()
        base = f"http://127.0.0.1:{address[1]}"
        policy = Policy(
            page=Page(acquisitions=[Acquisition.browser("headful")]),
            observe=ObservePolicy(
                enabled=True,
                native_tab_capture=True,
                screenshots=ScreenshotPolicy(after="viewport"),
                recordings=[
                    RecordingRule(mode="browser_visible", max_duration_ms=15_000),
                    RecordingRule(mode="each_tab", max_duration_ms=15_000),
                ],
            ),
        )
        browser = ys.browser.session(
            policy=policy,
            settings=SessionPolicy(
                mode="headful", maximum_tabs=4, execution_concurrency=1
            ),
        )
        async with browser:
            tabs = [await browser.new_tab() for _ in range(3)]
            self.assertEqual(len({tab.id for tab in tabs}), 3)
            async with AsyncExitStack() as stack:
                workers = [await stack.enter_async_context(browser.work())]
                workers.extend(
                    [await stack.enter_async_context(tab.work()) for tab in tabs]
                )
                for index, work in enumerate(workers):
                    outcome = await work.run(
                        ys.flow([ys.navigate(f"{base}/?id={index}")])
                    )
                    outcome.require_completed()
                # This defines a recording interval, not a readiness delay.
                (await workers[0].run(ys.flow([ys.wait(1500)]))).require_completed()
        self.assertTrue(browser.closed)
        outcomes = await browser.recording_outcomes()
        self.assertEqual(len(outcomes), 5)
        self.assertEqual(
            sum(item.source.scope.kind == "browser_visible" for item in outcomes), 1
        )
        self.assertEqual(sum(item.source.scope.kind == "tab" for item in outcomes), 4)
        self.assertTrue(all(item.segments for item in outcomes))
        self.assertTrue(all(item.stop_reason == "session_closed" for item in outcomes))
        evidence = browser.evidence()
        self.assertGreaterEqual(
            sum(item.capture is not None for item in evidence.entries), 4
        )
        self.assertGreater(evidence.retained_bytes, 0)
        with tempfile.TemporaryDirectory() as directory:
            archive = await ys.Archive.open(directory)
            reference = await evidence.write_to(archive)
            restored = await SessionEvidence.read_from(archive, reference)
            self.assertEqual(restored.retained_bytes, evidence.retained_bytes)
            for outcome in outcomes:
                reference = await outcome.write_to(archive)
                restored = await RecordingOutcome.read_from(archive, reference)
                self.assertEqual(restored.id, outcome.id)
                self.assertEqual(len(restored.actions), len(outcome.actions))
