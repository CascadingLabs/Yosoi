"""Complete an immutable release after correcting only Rust descriptions."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from release import (
    json_url,
    package_version,
    plan,
    pypi_pending,
    registry_manifests,
    sha256,
    validate_registry_metadata,
    verify_wheels,
)


def command(*args: str) -> str:
    return subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout.strip()


def description_only(before: dict, after: dict) -> bool:
    original, corrected = copy.deepcopy(before), copy.deepcopy(after)
    old = original.get("package", {}).pop("description", None)
    new = corrected.get("package", {}).pop("description", None)
    return (
        old is None
        and isinstance(new, str)
        and bool(new.strip())
        and original == corrected
    )


def verify_source(root: Path, source: str) -> None:
    # Tooling may change; every SDK, interpreter, browser and compiler input is
    # identical except the missing descriptive fields in publishable manifests.
    scope = (
        "crates",
        "vendor",
        "python",
        "docker",
        ".cargo",
        "Cargo.toml",
        "Cargo.lock",
        "rust-toolchain.toml",
        "CITATION.cff",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "LICENSE",
    )
    if command("git", "status", "--porcelain", "--untracked-files=all", "--", *scope):
        raise ValueError("Release SDK working tree differs from its packaging commit")
    changed = command(
        "git", "diff", "--name-only", source, "HEAD", "--", *scope
    ).splitlines()
    manifests = registry_manifests(root)
    permitted = {path.relative_to(root).as_posix() for path, _ in manifests.values()}
    for name in changed:
        if name not in permitted:
            raise ValueError(f"Release SDK input changed: {name}")
        before = tomllib.loads(command("git", "show", f"{source}:{name}"))
        after = tomllib.loads((root / name).read_text())
        if not description_only(before, after):
            raise ValueError(f"Release manifest changed beyond its description: {name}")
    if not changed:
        raise ValueError("No missing description correction was found")


def verify_build(run: dict, jobs: list[dict], source: str, release: dict) -> None:
    if (
        run.get("head_sha") != source
        or run.get("head_branch") != "main"
        or run.get("path") != ".github/workflows/release-cd.yml"
        or run.get("status") != "completed"
        or run.get("event") not in {"push", "workflow_dispatch"}
    ):
        raise ValueError("Expected a completed exact-source main Release CD run")
    required = {"identity", "source-ci", "verify", "pypi"}
    for row in release["platforms"]["include"]:
        required.add(f"Rust artifacts ({row['platform']})")
        required.add(f"Build wheels ({row['platform']})")
    for row in release["wheel_tests"]["include"]:
        required.add(f"Installed wheel ({row['platform']}, {row['python']})")
        required.add(f"Published install ({row['platform']}, {row['python']})")
    latest = {}
    for job in jobs:
        if job.get("databaseId", 0) >= latest.get(job["name"], {}).get("databaseId", 0):
            latest[job["name"]] = job
    for name in sorted(required):
        job = latest.get(name, {})
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            raise ValueError(f"Original release gate is not successful: {name}")


def check(root: Path, tag: str, run_id: int, directory: Path) -> dict:
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Release completion requires the main workflow")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if repository != "CascadingLabs/Yosoi":
        raise ValueError("Release completion requires the Yosoi repository")
    release = plan(root, tag)
    if release["candidate"] or release["publication"]["blockers"]:
        raise ValueError(
            "Expected a final release with resolved registry prerequisites"
        )
    source = command("git", "rev-parse", f"{tag}^{{commit}}")
    verify_source(root, source)
    validate_registry_metadata(root)
    run = json.loads(command("gh", "api", f"repos/{repository}/actions/runs/{run_id}"))
    jobs = json.loads(
        command(
            "gh", "run", "view", str(run_id), "--repo", repository, "--json", "jobs"
        )
    )["jobs"]
    verify_build(run, jobs, source, release)
    original = json.loads(Path("release-plan.json").read_text())
    if original["version"] != release["version"] or original["source_commit"] != source:
        raise ValueError("Downloaded artifacts differ from the checked release source")
    verify_wheels(directory, release)
    pending = root / ".generated/registry-completion-pending"
    pending.parent.mkdir(parents=True, exist_ok=True)
    pypi_pending(directory, release["python_version"], pending)
    if any(pending.iterdir()):
        raise ValueError("Every original Python artifact must already match PyPI")
    return {
        "version": release["version"],
        "tag": tag,
        "sdk_source_commit": source,
        "rust_packaging_commit": command("git", "rev-parse", "HEAD"),
        "verified_run": run_id,
        "correction": "Missing Rust package descriptions only",
    }


def receipts(root: Path, proof: dict) -> dict:
    release = plan(root, proof["tag"])
    manifests = registry_manifests(root)
    packages = []
    for name in release["publication"]["crates"]:
        version = package_version(root, manifests[name][1])
        archive = root / "target/package" / f"{name}-{version}.crate"
        response = json_url(f"https://crates.io/api/v1/crates/{name}/{version}")
        checksum = sha256(archive)
        if not response or response["version"]["checksum"] != checksum:
            raise ValueError(f"Registry did not confirm the corrected {name}")
        if response["version"].get("yanked"):
            raise ValueError(f"Corrected {name} is yanked")
        packages.append({"name": name, "version": version, "sha256": checksum})
    return proof | {"packages": packages}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "receipts"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--directory", type=Path, default=Path("dist"))
    parser.add_argument("--proof", type=Path, default=Path("completion-proof.json"))
    args = parser.parse_args()
    if args.run <= 0:
        raise ValueError("Expected a positive verified run ID")
    root = Path.cwd()
    if args.command == "check":
        proof = check(root, args.tag, args.run, args.directory)
        args.proof.write_text(json.dumps(proof, indent=2) + "\n")
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with Path(output).open("a") as stream:
                stream.write(f"source_commit={proof['sdk_source_commit']}\n")
                stream.write(f"version={proof['version']}\n")
        print("Verified original release gates and Rust description-only correction")
    else:
        proof = json.loads(args.proof.read_text())
        if proof["tag"] != args.tag or proof["verified_run"] != args.run:
            raise ValueError("Completion proof differs from the requested release")
        result = receipts(root, proof)
        (args.directory / "RUST-PUBLICATION.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"release-completion: {error}", file=sys.stderr)
        sys.exit(1)
