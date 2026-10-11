"""Publish verified crates or immutable GitHub release assets. Never runs on PRs."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

from release import json_url, package_version, plan, registry_manifests, sha256


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def download_registry_crate(name: str, version: str) -> bytes:
    url = f"https://static.crates.io/crates/{name}/{name}-{version}.crate"
    request = urllib.request.Request(url, headers={"User-Agent": "Yosoi-release-CD"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def crate_archive_contents(archive_bytes: bytes) -> dict[str, tuple[str, bytes | str]]:
    contents = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError(f"unsafe path in crate archive: {member.name}")
                if len(path.parts) == 2 and path.name == ".cargo_vcs_info.json":
                    continue
                name = path.as_posix()
                if name in contents:
                    raise ValueError(f"duplicate path in crate archive: {name}")
                if member.isfile():
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ValueError(
                            f"missing file contents in crate archive: {name}"
                        )
                    with stream:
                        contents[name] = ("file", stream.read())
                elif member.isdir():
                    contents[name] = ("directory", "")
                elif member.issym():
                    contents[name] = ("symlink", member.linkname)
                elif member.islnk():
                    contents[name] = ("hardlink", member.linkname)
                else:
                    raise ValueError(f"unsupported entry in crate archive: {name}")
    except (OSError, tarfile.TarError, EOFError) as error:
        raise ValueError(f"invalid crate archive: {error}") from error
    return contents


def verify_existing_crate(
    name: str, version: str, local_archive: Path, registry_version: dict
) -> str:
    checksum = registry_version.get("checksum")
    if (
        not isinstance(checksum, str)
        or len(checksum) != 64
        or any(character not in "0123456789abcdef" for character in checksum.lower())
    ):
        raise ValueError(f"crates.io omitted the checksum for {name} {version}")
    checksum = checksum.lower()
    local_bytes = local_archive.read_bytes()
    if hashlib.sha256(local_bytes).hexdigest() == checksum:
        return checksum

    published_bytes = download_registry_crate(name, version)
    published_checksum = hashlib.sha256(published_bytes).hexdigest()
    if published_checksum != checksum:
        raise ValueError(f"crates.io archive checksum mismatch for {name} {version}")
    if crate_archive_contents(local_bytes) != crate_archive_contents(published_bytes):
        raise ValueError(
            f"{name} {version} source contents differ from its published crate; "
            "use a new version"
        )
    return published_checksum


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
            registry_version = previous.get("version", {})
            if registry_version.get("yanked"):
                raise ValueError(f"{name} release is yanked")
            checksum = verify_existing_crate(name, version, file, registry_version)
            print(f"Verified existing {file.name} sha256={checksum}")
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
            print(f"Published {file.name} sha256={published['version']['checksum']}")


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
            candidate = "-rc." in release["version"]
            run(
                "gh",
                "release",
                "edit",
                tag,
                "--draft=false",
                f"--prerelease={'true' if candidate else 'false'}",
                f"--latest={'false' if candidate else 'true'}",
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
