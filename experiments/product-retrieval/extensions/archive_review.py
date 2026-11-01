"""Archive model-review receipts and replay their evaluation without inference."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import json
import shutil
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
archive_run = importlib.import_module("archive_run")
helpers = importlib.import_module("archive_campaign")


def bundle(frozen, responses, labels, captures, evaluation, output, catalog=None):
    plan = json.loads((frozen / "plan.json").read_text())
    complete = json.loads((responses / "run-complete.json").read_text())
    expected = {trial["id"] for trial in plan["trials"]}
    observed = {trial["id"] for trial in complete["completed"]}
    if (
        observed != expected
        or complete["partial_limit"] is not None
        or any(t["status"] != "completed" for t in complete["completed"])
    ):
        raise ValueError("archive requires all planned provider requests terminal")
    files = [
        (frozen / "plan.json", "frozen/plan.json"),
        (frozen / "producer.py", "code/review_experiment.py"),
        (frozen / "provider.py", "code/review_provider.py"),
        (labels, "labels.json"),
        (responses / "run-complete.json", "responses/run-complete.json"),
    ]
    if catalog is not None:
        if helpers.digest(catalog) != plan["catalog_sha256"]:
            raise ValueError("provider catalog differs from frozen model metadata")
        files.append((catalog, "provider-catalog.json"))
    for trial in plan["trials"]:
        name = trial["id"]
        files.append((frozen / f"{name}.request.json", f"frozen/{name}.request.json"))
        for leaf in (
            "request.json",
            "response.raw.json",
            "record.json",
            "state.json",
            "generation-stats.json",
        ):
            path = responses / name / leaf
            if path.exists():
                files.append((path, f"responses/{name}/{leaf}"))
    for name in sorted({trial["case"] for trial in plan["trials"]}):
        for leaf in (
            "rendered-dom.html",
            "element-layout.json",
            "viewport.png",
            "manifest.json",
            "current-source-response.html",
        ):
            files.append((captures / name / leaf, f"captures/{name}/{leaf}"))
    for leaf in ("summary.json", "decisions.json"):
        files.append((evaluation / leaf, "expected-evaluation/" + leaf))
    files.extend(
        [
            (Path(__file__), "code/archive_review.py"),
            (Path(archive_run.__file__), "code/archive_run.py"),
        ]
    )
    for path, logical in files:
        helpers.relative_path(logical)
        if not path.is_file() or path.is_symlink():
            raise ValueError("archive input missing or not a regular source file")
    if len({logical for _, logical in files}) != len(files):
        raise ValueError("duplicate logical archive input")
    output.mkdir(parents=True, exist_ok=False)
    index = []
    extras = []
    for number, (source, logical) in enumerate(files):
        flat = output / f"item-{number:04d}.bin"
        shutil.copyfile(source, flat)
        index.append(
            {
                "flat": flat.name,
                "logical": logical,
                "byte_len": flat.stat().st_size,
                "sha256": helpers.digest(flat),
            }
        )
        extras.append(flat)
    (output / "index.json").write_text(
        json.dumps(
            {
                "kind": "source-review-archive-v1",
                "entries": index,
                "scope": (
                    "Prompt/response/source and evaluation replay; "
                    "not new model inference or retrieval recomputation."
                ),
            },
            indent=2,
        )
    )
    asyncio.run(archive_run.bundle(output, extras))


def restore(bundle_path, output):
    if output.exists():
        raise ValueError("review restore requires a new directory")
    flat = output / "flat"
    asyncio.run(archive_run.restore(bundle_path, flat))
    index = json.loads((flat / "index.json").read_text())
    seen = set()
    for entry in index["entries"]:
        logical = helpers.relative_path(entry["logical"])
        source_name = helpers.relative_path(entry["flat"])
        if len(source_name.parts) != 1 or logical in seen:
            raise ValueError("unsafe or duplicate archive index entry")
        seen.add(logical)
        source = flat / source_name
        if (
            source.stat().st_size != entry["byte_len"]
            or helpers.digest(source) != entry["sha256"]
        ):
            raise ValueError("review restore payload mismatch")
        target = output / logical
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (output / "index.json").write_text(json.dumps(index, indent=2))


def replay(restored, output):
    if output.exists():
        raise ValueError("review evaluation replay requires a new destination")
    index = json.loads((restored / "index.json").read_text())
    for entry in index["entries"]:
        path = restored / helpers.relative_path(entry["logical"])
        if (
            path.stat().st_size != entry["byte_len"]
            or helpers.digest(path) != entry["sha256"]
        ):
            raise ValueError("restored review evidence changed")
    path = restored / "code/review_experiment.py"
    spec = importlib.util.spec_from_file_location("archived_review_evaluator", path)
    if spec is None or spec.loader is None:
        raise ValueError("archived review evaluator is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    attempted_network = []

    def blocked(*args, **kwargs):
        attempted_network.append(True)
        raise RuntimeError("network disabled during cached-response replay")

    original = socket.socket
    try:
        socket.socket = blocked
        module.evaluate(
            restored / "frozen",
            restored / "responses",
            restored / "labels.json",
            output,
        )
    finally:
        socket.socket = original
    observed = {
        name: helpers.digest(output / name)
        for name in ("summary.json", "decisions.json")
    }
    expected = {
        name: helpers.digest(restored / "expected-evaluation" / name)
        for name in observed
    }
    if observed != expected or attempted_network:
        raise ValueError(
            "cached-response review replay differed from archived evaluation"
        )
    certificate = {
        "kind": "source-review-cached-response-replay-v1",
        "expected": expected,
        "observed": observed,
        "network_attempts": len(attempted_network),
        "new_model_inference_calls": 0,
        "scope": (
            "Exact evaluation replay from archived responses. "
            "This does not reproduce stochastic provider inference."
        ),
        "replay_adapter_sha256": helpers.digest(Path(__file__)),
    }
    (output / "replay-certificate.json").write_text(json.dumps(certificate, indent=2))
    print(json.dumps(certificate))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bundle", "restore", "replay"))
    for name in (
        "frozen",
        "responses",
        "labels",
        "captures",
        "evaluation",
        "source",
        "output",
        "catalog",
    ):
        parser.add_argument("--" + name, type=Path, required=name == "output")
    args = parser.parse_args()
    if args.command == "bundle":
        bundle(
            args.frozen,
            args.responses,
            args.labels,
            args.captures,
            args.evaluation,
            args.output,
            args.catalog,
        )
    elif args.command == "restore":
        restore(args.source, args.output)
    else:
        replay(args.source, args.output)
