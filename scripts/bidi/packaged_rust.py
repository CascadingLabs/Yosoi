"""Compile native/offline consumers of the extracted Cargo package, without publish."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, **kwargs)


def main(args):
    workspace = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]
    manifest = tomllib.loads((ROOT / "crates/yosoi/Cargo.toml").read_text())
    version = manifest["package"]["version"]
    if isinstance(version, dict):
        version = workspace["package"]["version"]
    command = ["cargo", "package", "--locked", "-p", "yosoi", "--no-verify"]
    if args.allow_dirty:
        command.append("--allow-dirty")
    run(command, cwd=ROOT)
    target = Path(os.environ.get("CARGO_TARGET_DIR", str(ROOT / "target")))
    package = target / "package" / f"yosoi-{version}.crate"
    digest = hashlib.file_digest(package.open("rb"), "sha256").hexdigest()
    results = {
        "package_sha256": digest,
        "package_version": version,
        "source_revision": os.environ.get("GITHUB_SHA"),
    }
    with tempfile.TemporaryDirectory(prefix="yosoi-packaged-bidi-") as scratch:
        directory = Path(scratch)
        with tarfile.open(package) as archive:
            archive.extractall(directory, filter="data")
        sdk = directory / f"yosoi-{version}"
        consumer = directory / "consumer"
        (consumer / "src").mkdir(parents=True)
        records = directory / "records"
        env = os.environ.copy()
        env["BIDI_CONSUMER_RECORDS"] = str(records)
        env.setdefault("CARGO_BUILD_JOBS", "1")
        env.setdefault("RAYON_NUM_THREADS", "1")
        deps = workspace["dependencies"]

        def dependency_version(name):
            value = deps[name]
            return value["version"] if isinstance(value, dict) else value

        for mode in ["native", "offline"]:
            toml = f"""[package]
name="yosoi-packaged-bidi-acceptance"
version="0.0.0"
edition="2024"
[workspace]
[dependencies]
[dependencies.yosoi]
path={json.dumps(str(sdk), ensure_ascii=False)}
default-features=false
{('features=["browser-bidi"]' if mode == "native" else "")}
[dependencies.tokio]
version={json.dumps(dependency_version("tokio"))}
features=["macros","rt-multi-thread"]
[dependencies.serde_json]
version={json.dumps(dependency_version("serde_json"))}
"""
            (consumer / "Cargo.toml").write_text(toml)
            (consumer / "src/main.rs").write_text(
                (ROOT / f"scripts/bidi/consumer_{mode}.rs").read_text()
            )
            completed = run(
                [
                    "cargo",
                    "run",
                    "--manifest-path",
                    str(consumer / "Cargo.toml"),
                    "--quiet",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
            )
            results[mode] = json.loads(completed.stdout.strip().splitlines()[-1])
    with Path(args.output).open("x", encoding="utf-8") as output:
        json.dump(results, output, indent=2)
        output.write("\n")
    print(json.dumps(results), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    main(parser.parse_args())
