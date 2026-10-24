"""Independent round trips and failure boundaries for the public Archive bridge."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

import pytest

import yosoi as ys
from yosoi.archive import AutomationRecordRef, DocumentArchiveRef
from yosoi.browser import Observation, OperationReceipt
from yosoi.errors import ArchiveError, rust_error_details


def observation() -> Observation:
    return Observation(
        id="lamp-observation",
        session_id="original-session",
        tab_id="original-tab",
        document_epoch=7,
        url="https://offline.invalid/lamp",
        html="<main><h1>Arc desk lamp</h1><p>$68.00</p></main>",
        screenshot=b"\x89PNG\x00\xff",
    )


def record() -> ys.AutomationRecord:
    captured = observation()
    return ys.AutomationRecord(
        id="lamp-run",
        observations=(captured,),
        operations=(
            OperationReceipt(
                id="uncertain-operation",
                kind="click",
                status="unknown",
                observation=captured,
                error="transport lost after dispatch",
            ),
        ),
    )


def test_archive_platform_boundary(tmp_path: Path) -> None:
    async def run() -> None:
        for invalid in (123, b"unexpected-byte-path"):
            with pytest.raises(TypeError):
                await ys.Archive.open(cast(Any, invalid))
        if os.name == "posix":
            assert (await ys.Archive.open(tmp_path / "store")).root.is_absolute()
        else:
            with pytest.raises(ArchiveError, match="not certified"):
                await ys.Archive.open(tmp_path / "store")

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="local Archive requires Unix")
def test_document_and_plan_keep_exact_bytes_profile_and_identity(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        archive = await ys.Archive.open(tmp_path / "store")
        document = ys.Document.html("lamp", b"<h1>Arc desk lamp</h1>")
        plan = ys.Plan(outputs=[ys.output("name", ys.css("h1").text())])
        saved = await archive.write(document)
        saved_plan = await archive.write(plan)
        reopened = await ys.Archive.open(archive.root)
        restored = await reopened.read(
            DocumentArchiveRef.model_validate_json(saved.model_dump_json())
        )
        restored_plan = await reopened.read(saved_plan)
        assert restored.id == document.id
        assert restored.profile == document.profile
        assert restored.data == document.data
        assert restored_plan.compiled() == plan.compiled()
        assert restored.locate(restored_plan).values() == ["Arc desk lamp"]
        with pytest.raises(TypeError):
            await archive.write(cast(Any, {"arbitrary": "model"}))
        with pytest.raises(TypeError):
            await archive.read(cast(Any, saved.value))

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="local Archive requires Unix")
def test_record_preserves_screenshots_uncertainty_and_fresh_process_reads(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        archive = await ys.Archive.open(tmp_path / "store")
        saved = await archive.write(record())
        restored = await archive.read(saved)
        assert restored == record()
        assert restored.operations[0].status == "unknown"
        assert restored.observations[0].screenshot == b"\x89PNG\x00\xff"
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import asyncio, sys
import yosoi as ys
from yosoi.archive import AutomationRecordRef
async def run():
    archive = await ys.Archive.open(sys.argv[1])
    record = await archive.read(AutomationRecordRef.model_validate_json(sys.argv[2]))
    assert record.observations[0].document_epoch == 7
    assert record.operations[0].status == 'unknown'
    assert record.observations[0].screenshot == b'\\x89PNG\\x00\\xff'
    print(ys.View.from_observation(record.observations[0], 5).rows[0].text_preview)
asyncio.run(run())
""",
                str(archive.root),
                saved.model_dump_json(),
            ],
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert child.returncode == 0, child.stderr
        assert "Arc desk lamp" in child.stdout

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="local Archive requires Unix")
@pytest.mark.parametrize("damage", ["missing", "truncated", "digest", "envelope"])
def test_corrupt_storage_is_rejected_with_error_identity(
    tmp_path: Path, damage: str
) -> None:
    async def run() -> None:
        archive = await ys.Archive.open(tmp_path / "store")
        saved = await archive.write(ys.Document.html("lamp", b"<h1>Arc desk lamp</h1>"))
        payload = next(archive.root.rglob("payload.bin"))
        if damage == "missing":
            payload.unlink()
        elif damage == "truncated":
            payload.write_bytes(b"x")
        elif damage == "digest":
            data = payload.read_bytes()
            payload.write_bytes(b"x" + data[1:])
        else:
            metadata = next(
                (archive.root / "archive/v1/records/document").rglob("*.json")
            )
            metadata.write_text("{", encoding="utf-8")
        with pytest.raises(ArchiveError) as failure:
            await archive.read(saved)
        details = rust_error_details(failure.value)
        assert details is not None
        assert details.variant in {
            "DocumentPayloadMissing",
            "DocumentPayloadLengthMismatch",
            "DocumentPayloadDigestMismatch",
            "MalformedEnvelope",
        }

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="local Archive requires Unix")
def test_reference_version_and_kind_are_not_silently_reinterpreted(
    tmp_path: Path,
) -> None:
    with pytest.raises(ArchiveError):
        DocumentArchiveRef(value="document:v1:../../outside")
    with pytest.raises(ArchiveError):
        DocumentArchiveRef(value="plan:v1:631884d9-cfbe-4e34-a474-1634b52109ac")

    async def run() -> None:
        archive = await ys.Archive.open(tmp_path / "store")
        saved = await archive.write(ys.Document.text("text", b"original"))
        future = DocumentArchiveRef(value=saved.value.replace(":v1:", ":v99:"))
        with pytest.raises(ArchiveError) as failure:
            await archive.read(future)
        details = rust_error_details(failure.value)
        assert details is not None
        assert details.variant == "UnsupportedFormat"
        with pytest.raises(ArchiveError, match="version"):
            await archive.read(AutomationRecordRef(version=99, document=saved.value))

    asyncio.run(run())


def test_view_pages_cover_capture_and_reject_foreign_and_changed_evidence() -> None:
    captured = observation()
    page = ys.View.from_observation(captured, 1)
    rows = list(page.rows)
    first_cursor = page.next_cursor
    assert first_cursor is not None
    while page.next_cursor is not None:
        page = ys.View.continue_from(captured, page.next_cursor)
        rows.extend(page.rows)
    assert [row.ordinal for row in rows] == list(range(page.total_rows))
    assert all(row.node.document_id == captured.id for row in rows)
    for update in (
        {"tab_id": "other"},
        {"document_epoch": 8},
        {"html": "<p>changed</p>"},
    ):
        with pytest.raises(ArchiveError):
            ys.View.continue_from(captured.model_copy(update=update), first_cursor)
    for invalid in (0, 101, True, 1.5):
        with pytest.raises(ValueError):
            ys.View.from_observation(captured, cast(Any, invalid))


def test_record_rejects_duplicate_identity_and_bounded_evidence() -> None:
    captured = observation()
    with pytest.raises(ArchiveError, match="duplicate"):
        ys.AutomationRecord(id="duplicate", observations=(captured, captured))
    with pytest.raises(ArchiveError, match="limit"):
        ys.AutomationRecord(
            id="too-big",
            observations=(
                captured.model_copy(update={"html": "x" * (6 * 1024 * 1024 + 1)}),
            ),
        )


@pytest.mark.skipif(os.name != "posix", reason="local Archive requires Unix")
def test_repeated_writes_are_distinct_immutable_occurrences(tmp_path: Path) -> None:
    async def run() -> None:
        archive = await ys.Archive.open(tmp_path / "store")
        references = []
        for index in range(24):
            document = ys.Document.text(
                "same-authored-id", f"iteration {index}".encode()
            )
            references.append(await archive.write(document))
        assert len({reference.value for reference in references}) == 24
        for index, reference in enumerate(references):
            assert (await archive.read(reference)).data == f"iteration {index}".encode()
        assert not list((archive.root / "archive/v1/staging").iterdir())

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="local Archive requires Unix")
def test_cancelled_python_wait_settles_native_write(tmp_path: Path) -> None:
    async def run() -> None:
        archive = await ys.Archive.open(tmp_path / "store")
        document = ys.Document.text("cancelled-write", b"x" * (2 * 1024 * 1024))
        # Native dispatch happens before cancelling the Python waiter. The
        # internal idle signal proves settlement without time-based readiness.
        native_waiter = archive._handle.write_document(document._handle)
        waiter = asyncio.ensure_future(native_waiter)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        await ys._native.wait_for_idle()
        assert not list((archive.root / "archive/v1/staging").iterdir())
        restored_reference = await archive.write(ys.Document.text("next", b"usable"))
        assert (await archive.read(restored_reference)).data == b"usable"

    asyncio.run(run())


@pytest.mark.skipif(
    os.name != "posix" or os.environ.get("YOSOI_BROWSER_TESTS") != "1",
    reason="requires Unix and explicit regular Chrome Stable browser opt-in",
)
def test_real_flow_is_inspected_in_fresh_process_after_browser_cleanup(
    tmp_path: Path,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"<main><h1>Arc desk lamp</h1></main>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:

        async def run() -> None:
            outcome = await ys.flow(
                [
                    ys.navigate(f"http://127.0.0.1:{server.server_port}/"),
                    ys.wait_until(ys.exists("h1"), timeout_ms=5000),
                ]
            ).invoke()
            outcome.require_completed()
            assert [item.kind for item in outcome.cleanup] == [
                "session.release",
                "session.close",
            ]
            archive = await ys.Archive.open(tmp_path / "store")
            record = ys.AutomationRecord.from_flow("real-lamp-run", outcome)
            assert record.observations
            saved = await archive.write(record)
            child = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    """
import asyncio, sys
import yosoi as ys
from yosoi.archive import AutomationRecordRef
async def run():
    archive = await ys.Archive.open(sys.argv[1])
    record = await archive.read(AutomationRecordRef.model_validate_json(sys.argv[2]))
    record.flow_outcome.require_completed()
    assert record.flow_outcome.cleanup[-1].kind == 'session.close'
    for observation in record.observations:
        view = ys.View.from_observation(observation, 10)
        if any('Arc desk lamp' in row.text_preview for row in view.rows):
            print(observation.session_id, observation.tab_id,
                  observation.document_epoch)
            return
    raise AssertionError('retained lamp evidence missing')
asyncio.run(run())
""",
                    str(archive.root),
                    saved.model_dump_json(),
                ],
                text=True,
                capture_output=True,
                timeout=30,
            )
            assert child.returncode == 0, child.stderr
            assert child.stdout.strip()

        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)
        assert not worker.is_alive()
