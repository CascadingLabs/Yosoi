"""Release identity, matrix, publication prerequisites, and artifact verification.

No registry writes are performed here. Run with the existing scripts/releases
UV project; all helpers use the standard library.
"""

from __future__ import annotations

import argparse
import email
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

PLATFORMS = (
    (
        "linux-x86_64",
        "x86_64-unknown-linux-gnu",
        "ubuntu-24.04",
        "x86_64",
        "manylinux_2_28_x86_64",
    ),
    (
        "linux-aarch64",
        "aarch64-unknown-linux-gnu",
        "ubuntu-24.04-arm",
        "aarch64",
        "manylinux_2_28_aarch64",
    ),
    ("windows-x86_64", "x86_64-pc-windows-msvc", "windows-2025", "x86_64", "win_amd64"),
    (
        "macos-aarch64",
        "aarch64-apple-darwin",
        "macos-15",
        "aarch64",
        "macosx_11_0_arm64",
    ),
    (
        "macos-x86_64",
        "x86_64-apple-darwin",
        "macos-15-intel",
        "x86_64",
        "macosx_11_0_x86_64",
    ),
)


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def release_version(tag: str) -> str:
    match = re.fullmatch(
        r"v0\.([1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-rc\.([1-9][0-9]*))?", tag
    )
    if not match or int(match[1]) > 100000 or int(match[2]) > 10000:
        raise ValueError(
            "Expected v0.MINOR.PATCH or v0.MINOR.PATCH-rc.N "
            "(MINOR 1..100000, PATCH 0..10000, N >= 1)"
        )
    return tag[1:]


def python_version(version: str) -> str:
    # Cargo SemVer and PEP 440 spell numbered release candidates differently.
    release_version("v" + version)
    return version.replace("-rc.", "rc")


def verify_workflow_source(
    source: str, workflow_source: str | None, publish: bool
) -> None:
    if publish and workflow_source != source:
        raise ValueError(
            "Publishing workflow revision must match the release tag commit"
        )


def python_abis(requirement: str) -> list[dict]:
    match = re.fullmatch(r">=3\.([0-9]+),<3\.([0-9]+)", requirement.replace(" ", ""))
    if not match:
        raise ValueError("requires-python must declare a bounded CPython minor range")
    minimum, maximum = int(match[1]), int(match[2])
    if minimum < 12 or maximum > 16 or minimum >= maximum:
        raise ValueError(
            "Review CD interpreter support before expanding requires-python"
        )
    result = []
    for minor in range(minimum, maximum):
        # The existing SDK compatibility policy does not advertise 3.13t.
        for suffix in ("", "t") if minor >= 14 else ("",):
            # Match the versions already exercised by Python CI; setup-python's
            # hosted manifest may lag UV's managed 3.15 interpreters.
            selected = {15: "3.15.0"}.get(minor, f"3.{minor}")
            interpreter = selected + suffix
            cp = f"cp3{minor}"
            result.append(
                {
                    "python": interpreter,
                    "abi": cp + suffix,
                    "python_tag": cp,
                    "linux_python": f"/opt/python/{cp}-{cp}{suffix}/bin/python",
                    "wheel_abi": (
                        "abi3.abi3t"
                        if suffix and minor >= 15
                        else cp + suffix
                        if suffix
                        else "abi3"
                    ),
                }
            )
    return result


def wheel_builds(abis: list[dict]) -> list[dict]:
    """Build stable ABIs once, retaining version-specific pre-3.15 threading."""
    minimum = next(row for row in abis if not row["abi"].endswith("t"))
    result = [
        minimum
        | {
            "abi": "abi3",
            "features": f"browser,pyo3/abi3-py{minimum['python_tag'][2:]}",
        }
    ]
    for row in abis:
        if row["abi"].endswith("t"):
            result.append(
                row
                | {
                    "abi": row["wheel_abi"],
                    "features": "browser,pyo3/abi3t-py315"
                    if row["wheel_abi"] == "abi3.abi3t"
                    else "browser",
                }
            )
    return result


# Only these reviewed browser forks may publish from vendor paths.
REGISTRY_FORKS = {
    "vendor/chromiumoxide": "yosoi-chromiumoxide",
    "vendor/chromiumoxide_cdp": "yosoi-chromiumoxide-cdp",
}


def registry_manifests(root: Path) -> dict:
    workspace = read_toml(root / "Cargo.toml")["workspace"]
    manifests = {}
    for member in workspace["members"]:
        path = root / member / "Cargo.toml"
        document = read_toml(path)
        if "package" in document:
            manifests[document["package"]["name"]] = (path, document)
    for directory, name in REGISTRY_FORKS.items():
        path = root / directory / "Cargo.toml"
        if path.is_file():
            document = read_toml(path)
            if document["package"]["name"] == name:
                manifests[name] = (path, document)
    return manifests


def package_version(root: Path, document: dict) -> str:
    version = document["package"]["version"]
    if isinstance(version, dict) and version.get("workspace") is True:
        version = read_toml(root / "Cargo.toml")["workspace"]["package"]["version"]
    if not isinstance(version, str) or not version:
        raise ValueError(
            "Package version must be explicit or inherited from the workspace"
        )
    return version


def validate_registry_metadata(root: Path) -> None:
    workspace = read_toml(root / "Cargo.toml")["workspace"]["package"]
    manifests = registry_manifests(root)
    for name in publication_plan(root)["crates"]:
        _, document = manifests[name]
        package = document["package"]
        fields = {}
        for field in ("description", "license", "license-file"):
            value = package.get(field)
            if isinstance(value, dict) and value.get("workspace"):
                value = workspace.get(field)
            fields[field] = value
        if (
            not isinstance(fields["description"], str)
            or not fields["description"].strip()
        ):
            raise ValueError(
                f"{name} is missing required crates.io description metadata"
            )
        if not fields["license"] and not fields["license-file"]:
            raise ValueError(f"{name} is missing required crates.io license metadata")


def publication_plan(root: Path) -> dict:
    workspace = read_toml(root / "Cargo.toml")["workspace"]
    manifests = registry_manifests(root)
    roots = sorted(
        name
        for name, (path, doc) in manifests.items()
        if (
            path.parent.parent == root / "crates"
            or REGISTRY_FORKS.get(path.parent.relative_to(root).as_posix()) == name
        )
        and doc["package"].get("publish") is not False
    )
    ordered, visiting, visited, blockers = [], set(), set(), set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"Cyclic crate dependencies at {name}")
        visiting.add(name)
        path, doc = manifests[name]
        groups = [doc.get("dependencies", {}), doc.get("build-dependencies", {})]
        for target in doc.get("target", {}).values():
            groups.extend(
                [target.get("dependencies", {}), target.get("build-dependencies", {})]
            )
        for group in groups:
            for alias, specification in group.items():
                if not isinstance(specification, dict):
                    continue
                if specification.get("workspace"):
                    specification = workspace["dependencies"][alias]
                if not isinstance(specification, dict) or "path" not in specification:
                    continue
                # Workspace dependency paths are relative to the workspace manifest.
                source = root if group[alias].get("workspace") else path.parent
                dependency = read_toml(
                    (source / specification["path"] / "Cargo.toml").resolve()
                )["package"]
                dep_name = dependency["name"]
                if dependency.get("publish") is False:
                    blockers.add(
                        f"{name} depends on {dep_name}, which has publish = false"
                    )
                elif dep_name not in roots:
                    blockers.add(
                        f"{name} depends on vendored {dep_name}; "
                        "approve its registry distribution first"
                    )
                else:
                    visit(dep_name)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in roots:
        visit(name)
    return {"crates": ordered, "blockers": sorted(blockers)}


def plan(root: Path, tag: str) -> dict:
    version = release_version(tag)
    workspace = read_toml(root / "Cargo.toml")["workspace"]
    if workspace["package"]["version"] != version:
        raise ValueError("Tag does not match workspace version")
    abis = python_abis(read_toml(root / "pyproject.toml")["project"]["requires-python"])
    platforms = [
        dict(
            platform=p,
            target=t,
            runner=r,
            arch=a,
            wheel_platform=w,
            build_jobs=1 if p == "macos-aarch64" else 2,
        )
        for p, t, r, a, w in PLATFORMS
    ]
    builds = wheel_builds(abis)
    batch = {"python": builds[0]["python"]}
    for kind, abi in (("abi3", "abi3"), ("cp314t", "cp314t"), ("abi3t", "abi3.abi3t")):
        row = next((row for row in builds if row["abi"] == abi), {})
        for field in ("python", "linux_python", "features"):
            batch[f"{kind}_{field}"] = row.get(field, "")
    return {
        "version": version,
        "python_version": python_version(version),
        "candidate": "-rc." in version,
        "toolchain": read_toml(root / "rust-toolchain.toml")["toolchain"]["channel"],
        "platforms": {"include": platforms},
        "wheels": {
            "include": [platform | abi for platform in platforms for abi in builds]
        },
        "wheel_platforms": {"include": [platform | batch for platform in platforms]},
        "wheel_tests": {
            "include": [platform | abi for platform in platforms for abi in abis]
        },
        "publication": publication_plan(root),
    }


def wheel_identity(file: Path, version: str) -> tuple[str, str, set[str]]:
    with zipfile.ZipFile(file) as archive:
        metadata_paths = [
            n for n in archive.namelist() if n.endswith(".dist-info/METADATA")
        ]
        wheel_paths = [n for n in archive.namelist() if n.endswith(".dist-info/WHEEL")]
        if len(metadata_paths) != 1 or len(wheel_paths) != 1:
            raise ValueError(f"Invalid wheel metadata: {file.name}")
        metadata = email.message_from_bytes(archive.read(metadata_paths[0]))
        if metadata["Name"] != "yosoi" or metadata["Version"] != version:
            raise ValueError(f"Unexpected package identity: {file.name}")
        wheel = email.message_from_bytes(archive.read(wheel_paths[0]))
        tags = wheel.get_all("Tag", [])
        if not tags:
            raise ValueError(f"Missing wheel tags: {file.name}")
        split = [tag.split("-") for tag in tags]
        python_tags = {p for p, _, _ in split}
        abi_tags = {a for _, a, _ in split}
        if len(python_tags) != 1 or (
            len(abi_tags) != 1 and abi_tags != {"abi3", "abi3t"}
        ):
            raise ValueError(f"Unexpected wheel ABI tags: {file.name}")
        return (
            next(iter(python_tags)),
            ".".join(sorted(abi_tags)),
            {p for _, _, p in split},
        )


def verify_wheels(directory: Path, release: dict) -> None:
    expected = {
        (row["python_tag"], row["abi"], row["wheel_platform"])
        for row in release["wheels"]["include"]
    }
    seen = set()
    for file in sorted(directory.glob("*.whl")):
        python, abi, platforms = wheel_identity(
            file, python_version(release["version"])
        )
        matching = {(python, abi, platform) for platform in platforms} & expected
        if len(matching) != 1 or seen & matching:
            raise ValueError(f"Unexpected or duplicate wheel: {file.name}")
        seen |= matching
    if seen != expected:
        raise ValueError(f"Missing release wheels: {sorted(expected - seen)}")
    sdists = list(directory.glob("*.tar.gz"))
    if len(sdists) != 1:
        raise ValueError("Exactly one source distribution is required")
    with tarfile.open(sdists[0]) as archive:
        entries = [
            m
            for m in archive.getmembers()
            if m.name.count("/") == 1 and m.name.endswith("/PKG-INFO")
        ]
        if len(entries) != 1:
            raise ValueError("Missing source distribution identity")
        stream = archive.extractfile(entries[0])
        if stream is None:
            raise ValueError("Source distribution metadata is not a regular file")
        metadata = email.message_from_bytes(stream.read())
        if metadata["Name"] != "yosoi" or metadata["Version"] != python_version(
            release["version"]
        ):
            raise ValueError("Source distribution version mismatch")
        licenses = metadata.get_all("License-File", [])
        if not licenses:
            raise ValueError("Source distribution is missing License-File metadata")
        root = entries[0].name.split("/")[0]
        for license_file in licenses:
            path = PurePosixPath(license_file)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(
                    f"Invalid source distribution license path: {license_file}"
                )
            try:
                member = archive.getmember(f"{root}/{license_file}")
            except KeyError as error:
                raise ValueError(
                    f"Source distribution is missing license file: {license_file}"
                ) from error
            if not member.isfile() or member.size == 0:
                raise ValueError(
                    "Source distribution license is not a nonempty regular file: "
                    f"{license_file}"
                )


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_url(url: str, *, token: str | None = None) -> dict | None:
    try:
        headers = {"User-Agent": "Yosoi-release-CD"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def pypi_pending(directory: Path, version: str, output: Path) -> None:
    import shutil

    release = json_url(f"https://pypi.org/pypi/yosoi/{version}/json")
    existing = {
        entry["filename"]: entry["digests"]["sha256"]
        for entry in (release or {}).get("urls", [])
    }
    output.mkdir()
    for file in sorted(directory.iterdir()):
        if file.suffix != ".whl" and not file.name.endswith(".tar.gz"):
            continue
        checksum = sha256(file)
        if file.name in existing:
            if existing[file.name] != checksum:
                raise ValueError(
                    f"PyPI already has different bytes for {file.name}; "
                    "use a new version"
                )
        else:
            shutil.copyfile(file, output / file.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["plan", "publication-ready", "verify", "pypi-pending", "checksums"],
    )
    parser.add_argument("--tag", required=True)
    parser.add_argument("--directory", type=Path, default=Path("dist"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workflow-source")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    release = plan(root, args.tag)
    if args.command == "plan":
        source = git("rev-parse", "HEAD")
        if git("rev-parse", "--verify", f"refs/tags/{args.tag}^{{commit}}") != source:
            raise ValueError("Checkout does not match release tag")
        verify_workflow_source(source, args.workflow_source, args.publish)
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", source, "origin/main"], check=True
        )
        release["source_commit"] = source
        encoded = json.dumps(release, indent=2) + "\n"
        if args.output:
            args.output.write_text(encoded)
        print(encoded)
        if output := os.environ.get("GITHUB_OUTPUT"):
            with open(output, "a") as stream:
                for key in (
                    "version",
                    "python_version",
                    "candidate",
                    "toolchain",
                    "source_commit",
                    "platforms",
                    "wheels",
                    "wheel_platforms",
                    "wheel_tests",
                ):
                    value = release[key]
                    encoded_value = (
                        json.dumps(value) if isinstance(value, (dict, bool)) else value
                    )
                    stream.write(f"{key}={encoded_value}\n")
    elif args.command == "publication-ready":
        if release["publication"]["blockers"]:
            raise ValueError(
                "Registry publication blocked:\n"
                + "\n".join(release["publication"]["blockers"])
            )
        validate_registry_metadata(Path.cwd())
    elif args.command == "verify":
        verify_wheels(args.directory, release)
    elif args.command == "pypi-pending":
        if args.output is None:
            parser.error("pypi-pending requires --output")
        verify_wheels(args.directory, release)
        pypi_pending(args.directory, release["python_version"], args.output)
    elif args.command == "checksums":
        for file in sorted(args.directory.iterdir()):
            if file.is_file() and file.name != "SHA256SUMS":
                print(f"{sha256(file)}  {file.name}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"release-CD: {error}", file=sys.stderr)
        sys.exit(1)
