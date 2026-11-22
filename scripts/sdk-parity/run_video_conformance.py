"""Compare real Rust/Python video frames; audio remains explicitly unobserved."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from video_conformance import (
    EVIDENCE_KIND,
    RESULT_KIND,
    evidence_cases,
    validate_fixture_set,
)
from video_runtime import observe_fixtures

import parity


def require_tools(which=shutil.which) -> dict[str, str]:
    """Require real FFmpeg/FFprobe prerequisites instead of skipping video proof."""
    tools = {name: which(name) for name in ("ffmpeg", "ffprobe")}
    missing = [name for name, path in tools.items() if path is None]
    if missing:
        raise RuntimeError(
            "video SDK parity requires installed tools: " + ", ".join(missing)
        )
    return {
        name: str(Path(path).resolve())
        for name, path in tools.items()
        if path is not None
    }


def fixture_command(ffmpeg: str, path: Path) -> list[str]:
    """Create four deterministic video frames plus one short synthetic AAC stream."""
    return [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-filter_threads",
        "1",
        "-filter_complex_threads",
        "1",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=64x32:rate=4",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=8000",
        "-t",
        "1",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "mpeg4",
        "-q:v",
        "2",
        "-bf",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "32k",
        "-threads:v",
        "1",
        "-threads:a",
        "1",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-map_metadata",
        "-1",
        "-movflags",
        "+faststart",
        str(path),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-executable", type=Path, required=True)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    parser.add_argument("--python-root", type=Path, default=Path("python"))
    args = parser.parse_args()
    rust = parity.load_rust_inventory(args.rust_reference)
    python_inventory = parity.introspect_python_package(python_root=args.python_root)
    python_root = str(args.python_root.resolve())
    if python_root not in sys.path:
        sys.path.insert(0, python_root)
    ys = importlib.import_module("yosoi")
    tools = require_tools()
    # This runner is a child process; these explicit tool selections cannot
    # mutate the calling shell or another SDK operation's environment.
    os.environ.update(YOSOI_FFMPEG=tools["ffmpeg"], YOSOI_FFPROBE=tools["ffprobe"])
    with TemporaryDirectory(prefix="yosoi-shared-video-") as directory:
        clip = Path(directory) / "fixture.mp4"
        generator = fixture_command(tools["ffmpeg"], clip)
        try:
            subprocess.run(
                generator, capture_output=True, text=True, timeout=30, check=True
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                "FFmpeg parity fixture failed: " + error.stderr[-3000:]
            ) from error
        clip_sha256 = parity.digest_bytes(clip.read_bytes())
        process = subprocess.run(
            [str(args.rust_executable.resolve()), str(clip)],
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        fixtures = validate_fixture_set(json.loads(process.stdout))
        opened = next(
            case["rust"] for case in fixtures["cases"] if case["name"] == "open"
        )
        if opened["metadata"]["source_sha256"] != clip_sha256:
            raise ValueError("Rust video fixture did not read the actual shared clip")
        comparisons = observe_fixtures(fixtures, ys, clip)
    cases = evidence_cases(comparisons, rust, parity.load_ledger(args.ledger))
    passed = all(row["equal"] for row in comparisons) and all(
        row["outcome"] == "passed" for row in cases
    )
    result = {
        "schemaVersion": 1,
        "kind": RESULT_KIND,
        "runId": str(uuid.uuid4()),
        "outcome": "passed" if passed else "failed",
        "source": {
            key: rust[key]
            for key in ("sourceRevision", "inventorySignature", "featureProfileDigest")
        },
        "python": {
            key: python_inventory[key]
            for key in ("surfaceDigest", "implementationDigest", "runtime")
        },
        "cases": cases,
        "comparisons": comparisons,
        "fixtureSourceSha256": clip_sha256,
        "fixtureGeneratorCommand": generator,
        "tools": tools,
        "fixtureExecutableSha256": parity.digest_bytes(
            args.rust_executable.read_bytes()
        ),
        "fixtureOutputSha256": parity.digest_bytes(process.stdout.encode("utf-8")),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = args.output.with_name(args.output.stem + "-results.json")
    raw.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    evidence = {
        key: result[key]
        for key in ("schemaVersion", "runId", "outcome", "source", "python", "cases")
    }
    evidence.update(
        kind=EVIDENCE_KIND,
        executedAt=datetime.now(UTC).isoformat(),
        runner={"command": [sys.executable, *sys.argv]},
        resultArtifact={
            "path": raw.name,
            "sha256": parity.digest_bytes(raw.read_bytes()),
        },
    )
    args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "fixtures": len(comparisons),
                "matched": sum(row["equal"] for row in comparisons),
                "attributions": len(cases),
                "outcome": result["outcome"],
                "evidence": str(args.output),
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
