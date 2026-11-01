"""Archive one completed expanded shard and replay its frozen scoring engine."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).parents[1]))
archive_run = importlib.import_module("archive_run")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def relative_path(value):
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or "\\" in value
        or path.as_posix() != value
    ):
        raise ValueError("unsafe restored artifact path")
    return Path(*path.parts)


def quality_digest(path):
    """Retain scores, statuses and all evaluation fields; exclude timing only."""
    h = hashlib.sha256()
    count = 0
    with gzip.open(path, "rt") as stream:
        for line in stream:
            row = json.loads(line)
            row.pop("scoring_ns")
            h.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
            h.update(b"\n")
            count += 1
    return {"rows": count, "sha256": h.hexdigest()}


def bundle(source, semantic, output):
    certificate = json.loads((source / "shard-complete.json").read_text())
    if certificate["configuration_sha256"] != digest(source / "frozen.json"):
        raise ValueError("completed shard configuration changed")
    if certificate["semantic_sha256"] != digest(semantic):
        raise ValueError("completed shard semantic artifact changed")
    for name, expected in certificate["output_sha256"].items():
        if digest(source / name) != expected:
            raise ValueError("completed shard output changed")
    frozen = json.loads((source / "frozen.json").read_text())
    for name, expected in frozen["code_identity"].items():
        if digest(source / "implementation" / relative_path(name)) != expected:
            raise ValueError("frozen producer implementation changed")
    ledger = semantic.with_suffix(".batches.jsonl")
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    if events[-1].get("kind") != "run_complete" or events[-1].get(
        "artifact_sha256"
    ) != digest(semantic):
        raise ValueError("semantic cost ledger does not certify completed artifact")
    if quality_digest(source / "rows.jsonl.gz")["rows"] != certificate["rows"]:
        raise ValueError("completed shard row count changed")
    output.mkdir(parents=True, exist_ok=False)
    files = [(p, "run/" + p.name) for p in source.iterdir() if p.is_file()]
    files += [
        (p, "run/" + p.relative_to(source).as_posix())
        for p in sorted((source / "implementation").rglob("*.py"))
    ]
    files += [(semantic, "model/semantic.json"), (ledger, "model/batches.jsonl")]
    files.append((Path(__file__), "adapter/archive_campaign.py"))
    entries = []
    extras = []
    for index, (path, logical) in enumerate(files):
        if path.is_symlink():
            raise ValueError("symlink is not retained evidence")
        target = output / f"artifact-{index:04d}.bin"
        shutil.copyfile(path, target)
        entries.append(
            {
                "flat": target.name,
                "logical": logical,
                "bytes": target.stat().st_size,
                "sha256": digest(target),
            }
        )
        extras.append(target)
    index = {
        "kind": "expanded-shard-archive-index-v1",
        "entries": entries,
        "filters": certificate["filters"],
        "expected_quality": quality_digest(source / "rows.jsonl.gz"),
        "archive_runtime": str(archive_run.Archive.__module__),
        "scope": "One representative shard, not all expanded wave outputs.",
    }
    (output / "artifact-index.json").write_text(json.dumps(index, indent=2))
    asyncio.run(archive_run.bundle(output, extras))


def restore(bundle_path, destination):
    if destination.exists():
        raise ValueError("restore requires a new destination")
    flat = destination / "flat"
    asyncio.run(archive_run.restore(bundle_path, flat))
    index = json.loads((flat / "artifact-index.json").read_text())
    seen = set()
    for entry in index["entries"]:
        logical = relative_path(entry["logical"])
        relative_flat = relative_path(entry["flat"])
        if len(relative_flat.parts) != 1 or logical in seen:
            raise ValueError("duplicate or non-flat archived entry")
        seen.add(logical)
        source = flat / relative_flat
        if source.stat().st_size != entry["bytes"] or digest(source) != entry["sha256"]:
            raise ValueError("restored artifact differs from archived index")
        target = destination / logical
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    shutil.copyfile(flat / "artifact-index.json", destination / "artifact-index.json")
    return index


def replay(restored, output):
    if output.exists():
        raise ValueError("replay requires a new output directory")
    index = json.loads((restored / "artifact-index.json").read_text())
    # Revalidate the materialized files immediately before running the producer.
    for entry in index["entries"]:
        path = restored / relative_path(entry["logical"])
        if path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            raise ValueError("materialized replay evidence changed")
    output.mkdir(parents=True)
    for name in ("corpus.json", "frozen.json", "preparation.json"):
        shutil.copyfile(restored / "run" / name, output / name)
    shutil.copytree(restored / "run/implementation", output / "implementation")
    command = [
        "uv",
        "run",
        "--offline",
        "--no-project",
        "--python",
        "3.12",
        "--with",
        "zss==1.2.0",
        "python",
        str(output.resolve() / "implementation/extensions/campaign.py"),
        "run",
        "--output",
        str(output.resolve()),
        "--semantic",
        str((restored / "model/semantic.json").resolve()),
    ]
    for key, value in index["filters"].items():
        if value is not None:
            command.extend([f"--{key}-filter", value])
    environment = dict(os.environ)
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "RAYON_NUM_THREADS",
    ):
        environment[name] = "1"
    with (output / "replay.log").open("w") as log:
        subprocess.run(
            command, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True
        )
    observed = quality_digest(output / "rows.jsonl.gz")
    if observed != index["expected_quality"]:
        raise ValueError("recomputed rows differ from archived quality evidence")
    certificate = {
        "kind": "expanded-shard-recomputed-replay-v1",
        "expected": index["expected_quality"],
        "observed": observed,
        "filters": index["filters"],
        "excluded_fields": ["scoring_ns"],
        "embedding_inference_calls": 0,
        "runner_network_operations": 0,
        "execution": command,
        "replay_adapter_sha256": digest(Path(__file__)),
        "scope": (
            "Frozen one-case scoring engine recomputed from restored corpus, "
            "code and vectors in an empty output directory. No persisted score "
            "cache is used. Offline UV tooling; no embedding backend is invoked. "
            "Partial tree scorer statuses remain part of exact equality."
        ),
    }
    (output / "replay-certificate.json").write_text(json.dumps(certificate, indent=2))
    print(json.dumps(certificate))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bundle", "restore", "replay"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--semantic", type=Path)
    args = parser.parse_args()
    if args.command == "bundle":
        if args.semantic is None:
            parser.error("bundle requires --semantic")
        bundle(args.source, args.semantic, args.output)
    elif args.command == "restore":
        restore(args.source, args.output)
    else:
        replay(args.source, args.output)


if __name__ == "__main__":
    main()
