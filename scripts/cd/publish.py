"""Publish verified crates or immutable GitHub release assets. Never runs on PRs."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from release import json_url, package_version, plan, registry_manifests, sha256


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def publish_crates(tag: str) -> None:
    root = Path.cwd()
    release = plan(root, tag)
    publication = release["publication"]
    if publication["blockers"]:
        raise ValueError("Publication prerequisites are unresolved")
    if not os.environ.get("CARGO_REGISTRY_TOKEN"):
        raise ValueError("CARGO_REGISTRY_TOKEN is required")
    manifests = registry_manifests(root)
    target = root / "target"
    for name in publication["crates"]:
        manifest, document = manifests[name]
        version = package_version(root, document)
        # Registry packages are built in dependency order, after preceding uploads
        # have become available to Cargo. Cargo publish waits for index visibility.
        run(
            "cargo",
            "package",
            "--locked",
            "--manifest-path",
            str(manifest),
            "--target-dir",
            str(target),
        )
        file = target / "package" / f"{name}-{version}.crate"
        previous = json_url(f"https://crates.io/api/v1/crates/{name}/{version}")
        if previous:
            if previous["version"]["checksum"] != sha256(file):
                raise ValueError(
                    f"{name} already has different release bytes; use a new version"
                )
            if previous["version"].get("yanked"):
                raise ValueError(f"{name} release is yanked")
            print(f"Verified existing {file.name}")
        else:
            run(
                "cargo",
                "publish",
                "--locked",
                "--manifest-path",
                str(manifest),
                "--target-dir",
                str(target),
            )
            published = json_url(f"https://crates.io/api/v1/crates/{name}/{version}")
            if not published or published["version"]["checksum"] != sha256(file):
                raise ValueError(f"Registry did not confirm {file.name}")


def publish_github(tag: str, directory: Path, finalize: bool) -> None:
    release = plan(Path.cwd(), tag)
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("GH_TOKEN is required to inspect existing draft releases")
    # Distinguish absence from authorization/network failures before creating anything.
    previous = json_url(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/releases/tags/{tag}",
        token=token,
    )
    if not previous:
        run(
            "gh",
            "release",
            "create",
            tag,
            "--verify-tag",
            "--draft",
            "--title",
            tag,
            "--notes-file",
            "release-notes.md",
        )
    with tempfile.TemporaryDirectory() as temporary:
        if previous and previous.get("assets"):
            run("gh", "release", "download", tag, "--dir", temporary)
        existing = Path(temporary)
        files = sorted(directory.iterdir())
        unexpected = sorted(
            {file.name for file in existing.iterdir()} - {file.name for file in files}
        )
        if unexpected:
            raise ValueError(
                f"Unexpected existing release assets: {', '.join(unexpected)}"
            )
        for file in files:
            if not file.is_file():
                raise ValueError(f"Unexpected release directory: {file}")
            remote = existing / file.name
            if remote.exists():
                if sha256(remote) != sha256(file):
                    raise ValueError(
                        f"GitHub already has different bytes for {file.name}"
                    )
            elif previous and not previous["draft"]:
                raise ValueError("Cannot add assets to an already published release")
            else:
                run("gh", "release", "upload", tag, str(file))
        if finalize:
            run(
                "gh",
                "release",
                "edit",
                tag,
                "--draft=false",
                "--prerelease",
                "--latest=false",
            )
    print(f"Verified immutable assets for {release['version']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["crates", "github"])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--directory", type=Path, default=Path("dist"))
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.command == "crates":
        publish_crates(args.tag)
    else:
        publish_github(args.tag, args.directory, args.finalize)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"release-CD: {error}", file=sys.stderr)
        sys.exit(1)
