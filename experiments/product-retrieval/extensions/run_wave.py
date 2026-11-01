"""Run one-case frozen campaign shards sequentially with verified checkpoints."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import time
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def wait_predecessor(pid):
    """Wait for an observed process exit via Linux pidfd, never sleep/poll files."""
    if pid is None:
        return
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
        if b"embed_campaign.py" not in command:
            raise ValueError("predecessor PID no longer identifies the embedding job")
        fd = os.pidfd_open(pid)
    except (FileNotFoundError, ProcessLookupError):
        return
    try:
        select.select([fd], [], [])
    finally:
        os.close(fd)


def ready_artifact(path):
    events_path = path.with_suffix(".batches.jsonl")
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    if not events or events[-1].get("kind") != "run_complete":
        raise ValueError(f"embedding artifact is not complete: {path}")
    value = digest(path)
    if events[-1].get("artifact_sha256") != value:
        raise ValueError("embedding completion checksum mismatch")
    return value


def verified_shard(directory, config_hash, model_hash, filters):
    certificate = directory / "shard-complete.json"
    if not certificate.exists():
        return False
    data = json.loads(certificate.read_text())
    if (
        data["configuration_sha256"] != config_hash
        or data["semantic_sha256"] != model_hash
        or data["filters"] != filters
    ):
        raise ValueError("shard checkpoint belongs to a different experiment")
    for name, expected in data["output_sha256"].items():
        if digest(directory / name) != expected:
            raise ValueError(f"completed shard changed: {directory / name}")
    return True


def clone_inputs(source, directory):
    directory.mkdir(parents=True, exist_ok=False)
    # These files are frozen inputs; engines never modify them. Hard links avoid
    # duplicating the 29 MB corpus for every case. Checksums detect external edits.
    for filename in ("frozen.json", "corpus.json", "preparation.json"):
        os.link(source / filename, directory / filename)
    shutil.copytree(source / "implementation", directory / "implementation")


def run(
    source,
    models,
    destination,
    *,
    split="fresh_cross_site",
    group="javascript_product_detail/2",
    case=None,
    wait_pid=None,
):
    wait_predecessor(wait_pid)
    config_hash = digest(source / "frozen.json")
    config = json.loads((source / "frozen.json").read_text())
    corpus = json.loads((source / "corpus.json").read_text())
    selected = [
        c
        for c in corpus["cases"]
        if c["split"] == split and (case is None or c["id"] == case)
    ]
    if not selected:
        raise ValueError("case/split selects no data")
    for c in selected:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", c["id"]):
            raise ValueError("case identity is unsafe as a shard filename")
        if (
            sum(
                split == other["split"] and c["id"] in other["id"]
                for other in corpus["cases"]
            )
            != 1
        ):
            raise ValueError(
                "substring CLI case filter would select more than one case"
            )
    destination.mkdir(parents=True, exist_ok=True)
    completed = []
    for slug, model in models.items():
        model_hash = ready_artifact(model)
        for c in selected:
            directory = destination / slug / c["id"]
            filters = {"group": group, "case": c["id"], "split": split}
            if verified_shard(directory, config_hash, model_hash, filters):
                completed.append(
                    {"model": slug, "case": c["id"], "reused_complete_shard": True}
                )
                continue
            if directory.exists():
                raise ValueError(
                    "partial shard retained; inspect its process/log before "
                    f"a new attempt: {directory}"
                )
            directory.parent.mkdir(parents=True, exist_ok=True)
            clone_inputs(source, directory)
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
                str(directory / "implementation/extensions/campaign.py"),
                "run",
                "--output",
                str(directory),
                "--semantic",
                str(model),
                "--case-filter",
                c["id"],
                "--split-filter",
                split,
            ]
            if group:
                command += ["--group-filter", group]
            environment = {
                **os.environ,
                **{
                    name: "1"
                    for name in (
                        "OMP_NUM_THREADS",
                        "OPENBLAS_NUM_THREADS",
                        "MKL_NUM_THREADS",
                        "RAYON_NUM_THREADS",
                    )
                },
            }
            started = time.perf_counter_ns()
            (directory / "command.json").write_text(
                json.dumps(
                    {
                        "argv": command,
                        "configuration_sha256": config_hash,
                        "semantic_sha256": model_hash,
                        "filters": filters,
                        "timing_profile": (
                            "one-case cold engine startup; exact feature caches "
                            "within each shard"
                        ),
                    },
                    indent=2,
                )
            )
            with (directory / "run.log").open("w") as log:
                result = subprocess.run(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    check=False,
                )
            if result.returncode != 0:
                raise RuntimeError(
                    f"shard failed ({result.returncode}); retained {directory}"
                )
            summary = json.loads((directory / "summary.json").read_text())
            if (
                summary["filters"] != filters
                or summary["frozen_checksum"]
                != hashlib.sha256(
                    json.dumps(
                        config,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
            ):
                raise ValueError("executed shard does not match its frozen filters")
            if summary["semantic"]["artifact_sha256"] != model_hash:
                raise ValueError("shard used different semantic vectors")
            with gzip.open(directory / "rows.jsonl.gz", "rb") as rows:
                count = sum(1 for _ in rows)
            if count != summary["rows"] or count == 0:
                raise ValueError("shard row count/integrity mismatch")
            certificate = {
                "kind": "completed-frozen-case-shard-v1",
                "configuration_sha256": config_hash,
                "semantic_sha256": model_hash,
                "filters": filters,
                "rows": count,
                "wall_ns": time.perf_counter_ns() - started,
                "score_events": summary["score_event_counts"],
                "output_sha256": {
                    name: digest(directory / name)
                    for name in ("summary.json", "rows.jsonl.gz", "failures.jsonl.gz")
                },
            }
            (directory / "shard-complete.json").write_text(
                json.dumps(certificate, indent=2)
            )
            completed.append(
                {
                    "model": slug,
                    "case": c["id"],
                    "rows": count,
                    "directory": str(directory),
                }
            )
            print(json.dumps(completed[-1]), flush=True)
            (destination / "progress.json").write_text(
                json.dumps({"completed": completed}, indent=2)
            )
    (destination / "wave-complete.json").write_text(
        json.dumps({"completed": completed}, indent=2)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", default="fresh_cross_site")
    parser.add_argument("--group-filter", default="javascript_product_detail/2")
    parser.add_argument("--case")
    parser.add_argument("--wait-pid", type=int)
    args = parser.parse_args()
    run(
        args.source,
        {slug: args.input_dir / f"{slug}-v1.json" for slug in ("minilm", "bge-small")},
        args.output,
        split=args.split,
        group=args.group_filter or None,
        case=args.case,
        wait_pid=args.wait_pid,
    )
