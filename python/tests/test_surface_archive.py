"""Policy outcome and portable file acceptance through the installed Rust binding."""

import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from yosoi import Archive, Document, _native
from yosoi import surface as sf
from yosoi.errors import ArchiveError, rust_error_details


@pytest.mark.skipif(sys.platform == "win32", reason="Local Archive is Unix-only")
def test_portable_outcome_restores_in_a_fresh_process(tmp_path):
    async def capture():
        surface = sf.Surface(Document.html("article", "<h1>Portable λ🙂</h1>"))
        identity = surface.identity
        session = sf.Session(surface, sf.SessionPolicy(archive="enabled"))
        with session.cursor() as cursor:
            found = cursor.find("Portable")
            reference = found.entries[0].reference
            expected = cursor.inspect(reference).content
        outcome = session.close()
        assert outcome is not None and outcome.sealed and outcome.complete
        assert [receipt.kind for receipt in outcome.record.operations][:2] == [
            "surface.read",
            "surface.read",
        ]
        archive = await Archive.open(tmp_path / "original")
        saved = await archive.write(outcome)
        assert isinstance(saved, sf.OutcomeRef)
        restored = await archive.read(saved)
        assert restored.record == outcome.record
        await archive.export_file(saved, tmp_path / "workflow.yosoi")
        with pytest.raises(ArchiveError):
            await archive.export_file(saved, tmp_path / "workflow.yosoi")
        return identity, reference.model_dump(mode="json"), expected

    identity, reference, expected = asyncio.run(capture())
    shutil.rmtree(tmp_path / "original")
    (tmp_path / "workflow.yosoi").rename(tmp_path / "moved.yosoi")
    program = """
import asyncio, json, sys
from yosoi import Archive
from yosoi import surface as sf
async def main():
    archive = await Archive.open(sys.argv[1])
    reference = await archive.import_file(sys.argv[2])
    saved = await archive.read(reference)
    replay = await sf.replay(sys.argv[2], query="Portable")
    assert replay["browser_started"] is False and replay["matches"]["total"] > 0
    restored = saved.surface(sys.argv[3])
    target = sf.NativeReference.model_validate_json(sys.argv[4])
    assert sf.Session(restored).hot_owner is None
    content = restored.inspect(target).content
    result = {"identity": restored.identity, "content": content}
    print(json.dumps(result))
asyncio.run(main())
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(tmp_path / "fresh"),
            str(tmp_path / "moved.yosoi"),
            identity,
            json.dumps(reference),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {"identity": identity, "content": expected}


def test_policy_off_and_incomplete_outcomes_are_explicit():
    surface = sf.Surface(Document.text("fixture", "Evidence"))
    assert sf.Session(surface).close() is None
    session = sf.Session(
        surface,
        sf.SessionPolicy(
            archive="enabled", archive_limits=sf.ArchiveLimits(operations=1)
        ),
    )
    with session.cursor() as cursor:
        cursor.overview()
        cursor.find("Evidence")
    outcome = session.close()
    assert outcome is not None and not outcome.complete
    assert len(outcome.record.operations) == 1
    assert session.close() == outcome
    with pytest.raises(sf.SurfaceError):
        session.attach()


@pytest.mark.skipif(sys.platform == "win32", reason="Local Archive is Unix-only")
def test_shared_video_runtime_portable_pixels_need_no_original_or_decoder(
    tmp_path, monkeypatch
):
    ffmpeg = shutil.which("ffmpeg")
    if not (
        ffmpeg
        and shutil.which("ffprobe")
        and _native.surface_browser_enabled
        and _native.surface_video_enabled
    ):
        pytest.skip("native runtime/video tools unavailable")
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=10:duration=1",
            "-c:v",
            "mpeg4",
            "-threads",
            "1",
            str(source),
        ],
        check=True,
        timeout=30,
    )

    async def capture():
        runtime = await sf.VideoSession.open(
            source,
            sf.SurfacePolicy(archive="enabled", output=tmp_path / "run"),
            max_side=320,
        )
        source.unlink()
        try:
            ready = await runtime.ready()
            state = ready["state"]
            assert isinstance(state, dict)
            descriptor = state["descriptor"]
            assert isinstance(descriptor, dict)
            assert descriptor["controllable"] is False
            await runtime.execute({"op": "attach"})
            with pytest.raises(sf.ExecutionError, match="read-only video"):
                await runtime.execute({"op": "hot"})
            position = await runtime.execute({"op": "seek", "position_us": 300_000})
            pixels = await runtime.execute(
                {"op": "frame", "reference": position["focus"]}
            )
            artifact = pixels["artifact"]
            assert isinstance(artifact, dict)
            path = artifact["path"]
            expected = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        finally:
            outcome = await runtime.close()
        assert outcome is not None and outcome.complete and outcome.sealed
        archive = await Archive.open(tmp_path / "original")
        reference = await archive.write(outcome)
        await archive.export_file(reference, tmp_path / "video.yosoi")
        return expected

    expected = asyncio.run(capture())
    shutil.rmtree(tmp_path / "original")
    shutil.rmtree(tmp_path / "run")
    monkeypatch.setenv("YOSOI_FFMPEG", "/missing-decoder")
    monkeypatch.setenv("YOSOI_FFPROBE", "/missing-probe")

    async def reload():
        archive = await Archive.open(tmp_path / "fresh")
        reference = await archive.import_file(tmp_path / "video.yosoi")
        saved = await archive.read(reference)
        source = next(
            item.result
            for item in saved.record.operations
            if item.kind == "surface.video.source"
        )
        frame = next(
            item.result
            for item in saved.record.operations
            if item.kind == "surface.video.frame"
        )
        video = await sf.VideoSurface.read_from(
            archive, sf.VideoArchiveRef.model_validate(source)
        )
        pixels = await sf.DecodedFrame.read_from(
            archive, sf.FrameArchiveRef.model_validate(frame)
        )
        assert not video.descriptor.controllable
        assert hashlib.sha256(pixels.png).hexdigest() == expected

    asyncio.run(reload())


@pytest.mark.skipif(sys.platform == "win32", reason="Local Archive is Unix-only")
def test_failed_runtime_open_carries_an_archivable_partial_outcome(
    tmp_path, monkeypatch
):
    if not _native.surface_browser_enabled:
        pytest.skip("browser runtime unavailable")
    monkeypatch.setenv("CHROME", "/missing-browser")
    monkeypatch.setenv("CHROMEDRIVER", "/missing-driver")

    async def run():
        with pytest.raises(sf.ExecutionError) as caught:
            await sf.BrowserSurface.open(
                "https://example.invalid/", sf.SurfacePolicy(archive="enabled")
            )
        details = rust_error_details(caught.value)
        assert details is not None and details.variant == "Execution"
        outcomes = tuple(
            sf.Outcome.model_validate(value) for value in details.details["outcomes"]
        )
        assert len(outcomes) == 1
        assert not outcomes[0].complete and outcomes[0].sealed
        archive = await Archive.open(tmp_path / "store")
        reference = await archive.write(outcomes[0])
        await archive.export_file(reference, tmp_path / "failed.yosoi")
        await sf.export(
            tmp_path / "failed.yosoi", tmp_path / "failed-copy.yosoi"
        )
        copied = await archive.read(
            await archive.import_file(tmp_path / "failed-copy.yosoi")
        )
        assert not copied.complete
        with pytest.raises(sf.ExecutionError, match="incomplete"):
            await sf.replay(tmp_path / "failed-copy.yosoi")
        restored = await archive.read(
            await archive.import_file(tmp_path / "failed.yosoi")
        )
        assert any(item.status == "unknown" for item in restored.record.operations)

    asyncio.run(run())
