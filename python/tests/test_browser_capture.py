"""Python capture values and forwarding preserve native ownership and cleanup."""

from __future__ import annotations

import ast
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.browser import (
    _recording_outcome_from_native,
    _screenshot_capture_from_native,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"native image bytes"
MP4 = b"\x00\x00\x00\x10ftypmp42"


def test_session_observation_contract_targets_public_python_symbols_and_tests() -> None:
    contract_path = (
        Path(__file__).parents[1] / "parity" / "session-observation-contract.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["kind"] == "yosoi-python-session-observation-semantic-contract"
    scenarios = {
        node.name
        for file in (Path(__file__), Path(__file__).with_name("test_policy.py"))
        for node in ast.parse(file.read_text()).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }
    for declaration in contract["declarations"]:
        assert declaration["rustPath"].startswith("yosoi::")
        assert declaration["semanticEquivalent"]
        target = ys
        for attribute in declaration["pythonTarget"].split("."):
            target = getattr(target, attribute)
        assert target is not None
        for scenario in declaration["tests"]:
            assert scenario in scenarios


def test_screenshot_options_use_native_tagged_target_and_region_shapes() -> None:
    target = ys.browser.TargetScreenshotRegion(
        value=ys.browser.RoleScreenshotTarget(
            target=ys.browser.ScreenshotRoleValue(role="button", name="Continue", nth=0)
        )
    )
    options = ys.browser.ScreenshotOptions(region=target)

    assert json.loads(options.model_dump_json(exclude_none=True)) == {
        "region": {
            "kind": "target",
            "value": {
                "kind": "role",
                "target": {"role": "button", "name": "Continue", "nth": 0},
            },
        },
        "max_bytes": 16_000_000,
    }
    boxed = ys.browser.ScreenshotOptions(
        region=ys.browser.BoundingBoxScreenshotRegion(
            value=ys.browser.ScreenshotRectangle(x=0, y=12, width=320, height=180)
        )
    )
    assert json.loads(boxed.model_dump_json(exclude_none=True))["region"] == {
        "kind": "bounding_box",
        "value": {"x": 0, "y": 12, "width": 320, "height": 180},
    }


def test_recording_options_match_native_finite_defaults() -> None:
    assert json.loads(ys.browser.RecordingOptions().model_dump_json()) == {
        "max_bytes": 64_000_000,
        "max_buffer_bytes": 16_000_000,
        "max_duration_ms": 60_000,
        "frames_per_second": 15,
        "include_audio": False,
    }


def test_recording_outcome_bounds_payload_free_action_markers() -> None:
    action = ys.browser.RecordingAction(
        operation_id="operation-id",
        kind="click",
        status="observed",
        settled_at_unix_ms=1,
    )

    with pytest.raises(ValidationError):
        ys.browser.RecordingOutcome(
            id="recording-id",
            source=ys.browser.RecordingSource(
                id="source-id",
                scope=ys.browser.TabRecordingScope(tab_id="tab-id"),
                kind="tab_media_stream",
                started_at_unix_ms=0,
            ),
            segments=(),
            gaps=(),
            actions=(action,) * 4_097,
            stop_reason="requested",
            complete=False,
        )


def test_session_policy_round_trips_the_native_record_action() -> None:
    settings = ys.SessionPolicy()

    assert "record" in settings.allowed_actions
    assert "Record" in json.loads(settings.to_json())["allowed_actions"]


def test_capture_result_helpers_attach_typed_native_documents() -> None:
    image = ys.ImageDocument.from_bytes(
        "capture-image",
        PNG,
        metadata=ys.FileMetadata(capture_id="capture-id"),
    )
    screenshot = _screenshot_capture_from_native(
        json.dumps(
            {
                "capture_id": "capture-id",
                "source_id": "source-id",
                "tab_id": "tab-id",
                "captured_at_unix_ms": None,
                "region": {"kind": "viewport"},
                "width_pixels": 800,
                "height_pixels": 600,
                "document_epoch": 1,
                "bounds": None,
                "viewport_width": 800,
                "viewport_height": 600,
                "device_scale_factor": 1.0,
                "complete": True,
            }
        ),
        image._handle,
    )
    assert isinstance(screenshot.document, ys.ImageDocument)
    assert screenshot.document.bytes == PNG
    assert screenshot.region.kind == "viewport"

    video = ys.VideoDocument.from_bytes("video-segment", MP4)
    outcome = _recording_outcome_from_native(
        json.dumps(
            {
                "id": "recording-id",
                "source": {
                    "id": "source-id",
                    "scope": {"kind": "tab", "tab_id": "tab-id"},
                    "kind": "tab_media_stream",
                    "started_at_unix_ms": 1,
                },
                "segments": [
                    {
                        "document_id": "video-segment",
                        "sha256": video.sha256,
                        "byte_len": len(MP4),
                        "sequence": 0,
                        "start_offset_ms": 0,
                        "end_offset_ms": 250,
                        "media_start_ms": 0.0,
                        "media_end_ms": 250.0,
                        "mime_type": "video/mp4",
                        "complete": True,
                    }
                ],
                "gaps": [],
                "actions": [
                    {
                        "operation_id": "receipt-id",
                        "kind": "click",
                        "status": "observed",
                        "tab_id": "tab-id",
                        "settled_at_unix_ms": 240,
                    }
                ],
                "lost_action_events": 2,
                "stopped_at_unix_ms": 251,
                "stop_reason": "requested",
                "complete": True,
            }
        ),
        [video._handle],
    )
    assert isinstance(outcome.segments[0].document, ys.VideoDocument)
    assert outcome.segments[0].document.bytes == MP4
    assert outcome.stop_reason == "requested"
    assert outcome.actions[0].operation_id == "receipt-id"
    assert outcome.lost_action_events == 2


def test_session_evidence_exposes_linked_captures_and_explicit_gaps() -> None:
    image = ys.ImageDocument.from_bytes(
        "capture-image",
        PNG,
        metadata=ys.FileMetadata(capture_id="capture-id", tab_id="tab-id"),
    )
    video = ys.VideoDocument.from_bytes("video-segment", MP4)
    metadata = {
        "entries": [
            {
                "operation_id": "operation-id",
                "phase": "after",
                "capture": {
                    "capture_id": "capture-id",
                    "source_id": "source-id",
                    "tab_id": "tab-id",
                    "captured_at_unix_ms": None,
                    "region": {"kind": "viewport"},
                    "width_pixels": 8,
                    "height_pixels": 6,
                    "document_epoch": 1,
                    "bounds": None,
                    "viewport_width": 8,
                    "viewport_height": 6,
                    "device_scale_factor": 1.0,
                    "complete": True,
                },
                "gap": None,
            },
            {
                "operation_id": "next-operation",
                "phase": "failure",
                "capture": None,
                "gap": "capture_failed",
            },
        ],
        "retained_bytes": len(PNG),
        "maximum_bytes": 64_000_000,
        "omitted_entries": 0,
    }

    class FakeNativeSession:
        def __init__(self) -> None:
            self.is_closed = False

        @property
        def closed(self) -> bool:
            return self.is_closed

        async def close(self) -> None:
            self.is_closed = True

        def evidence(self) -> tuple[str, list[Any]]:
            return json.dumps(metadata), [image._handle]

        async def recording_outcomes(self) -> tuple[str, list[Any]]:
            return (
                json.dumps(
                    [
                        {
                            "id": "recording-id",
                            "source": {
                                "id": "source-id",
                                "scope": {"kind": "tab", "tab_id": "tab-id"},
                                "kind": "tab_media_stream",
                                "started_at_unix_ms": 10,
                            },
                            "segments": [
                                {
                                    "document_id": "video-segment",
                                    "sha256": video.sha256,
                                    "byte_len": len(MP4),
                                    "sequence": 0,
                                    "start_offset_ms": 0,
                                    "end_offset_ms": 250,
                                    "media_start_ms": 0.0,
                                    "media_end_ms": 250.0,
                                    "mime_type": "video/mp4",
                                    "complete": True,
                                }
                            ],
                            "gaps": [],
                            "actions": [],
                            "lost_action_events": 0,
                            "stopped_at_unix_ms": 261,
                            "stop_reason": "requested",
                            "complete": True,
                        }
                    ]
                ),
                [video._handle],
            )

    session = ys.Session.__new__(ys.Session)
    session._handle = FakeNativeSession()
    session._close_lock = asyncio.Lock()
    session._close_task = None

    async def run() -> None:
        await session.__aexit__(None, None, None)
        assert session.closed
        snapshot = session.evidence()
        assert snapshot.entries[0].operation_id == "operation-id"
        assert snapshot.entries[0].capture is not None
        assert snapshot.entries[0].capture.document.bytes == PNG
        assert snapshot.entries[1].gap == "capture_failed"
        assert snapshot.has_gaps
        outcomes = await session.recording_outcomes()
        assert outcomes[0].segments[0].document.bytes == MP4

    asyncio.run(run())


def test_session_new_tab_targets_lazy_work_and_closes_only_that_tab() -> None:
    class FakeNativeTab:
        def __init__(self) -> None:
            self.id = "retained-tab-id"
            self.is_closed = False
            self.close_calls = 0

        @property
        def closed(self) -> bool:
            return self.is_closed

        async def close(self) -> None:
            self.close_calls += 1
            self.is_closed = True

    class FakeNativeWork:
        def __init__(self) -> None:
            self.release_calls = 0

        async def release(self) -> None:
            self.release_calls += 1

    class FakeNativeSession:
        def __init__(self) -> None:
            self.is_closed = False
            self.tab = FakeNativeTab()
            self.work_targets: list[object | None] = []
            self.work_handles: list[FakeNativeWork] = []

        @property
        def closed(self) -> bool:
            return self.is_closed

        async def new_tab(self, cancellation: object | None) -> FakeNativeTab:
            assert cancellation is None
            return self.tab

        async def work(
            self, cancellation: object | None, tab: object | None
        ) -> FakeNativeWork:
            assert cancellation is None
            self.work_targets.append(tab)
            handle = FakeNativeWork()
            self.work_handles.append(handle)
            return handle

    async def run() -> None:
        native_session = FakeNativeSession()
        session = ys.Session.__new__(ys.Session)
        session._handle = native_session
        session._cancellation = None

        tab = await session.new_tab()
        assert isinstance(tab, ys.browser.Tab)
        assert tab.id == "retained-tab-id"

        initial_work = session.work()
        async with initial_work:
            assert native_session.work_targets == [None]

        tab_work = tab.work()
        assert native_session.work_targets == [None]
        async with tab_work:
            assert native_session.work_targets == [None, native_session.tab]
        assert tab_work.released
        assert native_session.work_handles[-1].release_calls == 1

        await tab.close()
        await tab.close()
        assert tab.closed
        assert native_session.tab.close_calls == 1
        with pytest.raises(ys.BrowserError):
            tab.work()

    asyncio.run(run())


class _FakeNativeRecording:
    def __init__(self, recording_id: str, video: ys.VideoDocument) -> None:
        self.recording_id = recording_id
        self.video = video
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.stop_calls = 0

    async def stop(self) -> tuple[str, list[Any]]:
        self.stop_calls += 1
        self.started.set()
        await self.finish.wait()
        metadata = {
            "id": self.recording_id,
            "source": {
                "id": f"source-{self.recording_id}",
                "scope": {"kind": "tab", "tab_id": "tab-id"},
                "kind": "tab_media_stream",
                "started_at_unix_ms": 10,
            },
            "segments": [
                {
                    "document_id": self.video.id,
                    "sha256": self.video.sha256,
                    "byte_len": self.video.byte_len,
                    "sequence": 0,
                    "start_offset_ms": 0,
                    "end_offset_ms": 250,
                    "media_start_ms": 0.0,
                    "media_end_ms": 250.0,
                    "mime_type": "video/mp4",
                    "complete": True,
                }
            ],
            "gaps": [],
            "actions": [
                {
                    "operation_id": "receipt-id",
                    "kind": "navigate",
                    "status": "observed",
                    "tab_id": "tab-id",
                    "settled_at_unix_ms": 250,
                }
            ],
            "lost_action_events": 3,
            "stopped_at_unix_ms": 261,
            "stop_reason": "requested",
            "complete": True,
        }
        return json.dumps(metadata), [self.video._handle]


class _FakeNativeWork:
    def __init__(self) -> None:
        self.recordings: list[_FakeNativeRecording] = []
        self.image = ys.ImageDocument.from_bytes(
            "capture-image",
            PNG,
            metadata=ys.FileMetadata(capture_id="capture-id"),
        )

    async def screenshot_with(
        self, options_json: str, cancellation: object | None
    ) -> tuple[str, Any]:
        assert json.loads(options_json)["max_bytes"] == 16_000_000
        assert cancellation is None
        metadata = {
            "capture_id": "capture-id",
            "source_id": "source-id",
            "tab_id": "tab-id",
            "captured_at_unix_ms": None,
            "region": {"kind": "viewport"},
            "width_pixels": 8,
            "height_pixels": 6,
            "document_epoch": 1,
            "bounds": None,
            "viewport_width": 8,
            "viewport_height": 6,
            "device_scale_factor": 1.0,
            "complete": True,
        }
        return json.dumps(metadata), self.image._handle

    async def start_recording(
        self, options_json: str, cancellation: object | None
    ) -> _FakeNativeRecording:
        assert json.loads(options_json)["frames_per_second"] == 15
        assert cancellation is None
        recording = _FakeNativeRecording(
            f"recording-{len(self.recordings)}",
            ys.VideoDocument.from_bytes(f"video-{len(self.recordings)}", MP4),
        )
        self.recordings.append(recording)
        return recording


class _FakeSession:
    _handle = object()
    _cancellation = None


def test_work_forwards_screenshot_and_retains_multiple_recording_handles() -> None:
    async def run() -> None:
        native = _FakeNativeWork()
        work = ys.Work(_FakeSession())
        work._handle = native

        screenshot = await work.screenshot_with()
        assert isinstance(screenshot.document, ys.ImageDocument)
        assert screenshot.document.bytes == PNG

        first, second = await asyncio.gather(
            work.start_recording(), work.start_recording()
        )
        assert len(native.recordings) == 2
        native.recordings[0].finish.set()
        native.recordings[1].finish.set()
        first_outcome, second_outcome = await asyncio.gather(
            first.stop(), second.stop()
        )
        assert first_outcome.id != second_outcome.id
        assert all(recording.stop_calls == 1 for recording in native.recordings)

    asyncio.run(run())


def test_recording_stop_is_shielded_and_context_exit_retains_outcome() -> None:
    async def run() -> None:
        native = _FakeNativeWork()
        work = ys.Work(_FakeSession())
        work._handle = native
        recording = await work.start_recording()
        native_handle = native.recordings[0]
        stop_task = asyncio.create_task(recording.stop())
        await native_handle.started.wait()
        stop_task.cancel()
        native_handle.finish.set()
        with pytest.raises(asyncio.CancelledError):
            await stop_task
        assert recording.outcome is not None
        assert native_handle.stop_calls == 1
        assert await recording.stop() is recording.outcome

        scoped = await work.start_recording()
        native.recordings[1].finish.set()
        async with scoped:
            pass
        assert scoped.outcome is not None
        assert native.recordings[1].stop_calls == 1

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="local Archive requires Unix")
def test_capture_media_documents_round_trip_through_typed_archive_refs(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        archive = await ys.Archive.open(tmp_path / "archive")
        image = ys.ImageDocument.from_bytes("archived-image", PNG)
        video = ys.VideoDocument.from_bytes("archived-video", MP4)
        image_ref = await archive.write(image)
        video_ref = await archive.write(video)

        assert isinstance(image_ref, ys.ImageDocumentArchiveRef)
        assert isinstance(video_ref, ys.VideoDocumentArchiveRef)
        restored_image = await archive.read(image_ref)
        restored_video = await archive.read(video_ref)
        assert isinstance(restored_image, ys.ImageDocument)
        assert isinstance(restored_video, ys.VideoDocument)
        assert restored_image.bytes == PNG
        assert restored_video.bytes == MP4

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="local Archive requires Unix")
def test_session_evidence_and_recording_outcomes_archive_separately(
    tmp_path: Path,
) -> None:
    image = ys.ImageDocument.from_bytes(
        "capture-image",
        PNG,
        metadata=ys.FileMetadata(capture_id="capture-id", tab_id="tab-id"),
    )
    screenshot = ys.browser.ScreenshotCapture(
        capture_id="capture-id",
        source_id="source-id",
        tab_id="tab-id",
        region=ys.browser.ViewportScreenshotRegion(),
        complete=True,
        document=image,
    )
    evidence = ys.browser.SessionEvidence(
        entries=(
            ys.browser.AutomaticEvidence(
                operation_id="operation-id", phase="after", capture=screenshot
            ),
            ys.browser.AutomaticEvidence(
                operation_id="failed-operation",
                phase="failure",
                gap="capture_failed",
            ),
        ),
        retained_bytes=len(PNG),
        maximum_bytes=64_000_000,
        omitted_entries=0,
    )
    video = ys.VideoDocument.from_bytes("video-segment", MP4)
    recording = _recording_outcome_from_native(
        json.dumps(
            {
                "id": "recording-id",
                "source": {
                    "id": "source-id",
                    "scope": {"kind": "tab", "tab_id": "tab-id"},
                    "kind": "tab_media_stream",
                    "started_at_unix_ms": 10,
                },
                "segments": [
                    {
                        "document_id": "video-segment",
                        "sha256": video.sha256,
                        "byte_len": len(MP4),
                        "sequence": 0,
                        "start_offset_ms": 0,
                        "end_offset_ms": 250,
                        "media_start_ms": 0.0,
                        "media_end_ms": 250.0,
                        "mime_type": "video/mp4",
                        "complete": True,
                    }
                ],
                "gaps": [],
                "actions": [
                    {
                        "operation_id": "receipt-id",
                        "kind": "navigate",
                        "status": "observed",
                        "tab_id": "tab-id",
                        "settled_at_unix_ms": 250,
                    }
                ],
                "lost_action_events": 3,
                "stopped_at_unix_ms": 261,
                "stop_reason": "requested",
                "complete": True,
            }
        ),
        [video._handle],
    )

    async def run() -> None:
        archive = await ys.Archive.open(tmp_path / "archive")
        evidence_ref = await evidence.write_to(archive)
        recording_ref = await recording.write_to(archive)
        restored_evidence = await ys.browser.SessionEvidence.read_from(
            archive, evidence_ref
        )
        restored_recording = await ys.browser.RecordingOutcome.read_from(
            archive, recording_ref
        )

        assert restored_evidence.entries[0].capture is not None
        assert restored_evidence.entries[0].capture.document.bytes == PNG
        assert restored_evidence.entries[1].gap == "capture_failed"
        assert restored_recording.segments[0].document.bytes == MP4
        assert restored_recording.actions[0].operation_id == "receipt-id"
        assert restored_recording.lost_action_events == 3

    asyncio.run(run())
