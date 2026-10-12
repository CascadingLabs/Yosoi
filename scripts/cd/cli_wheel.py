"""Package the already-built CLI as a dependency-free Python tool wheel.

The wheel scripts scheme installs the native executable directly. No Python
wrapper, SDK dependency, network bootstrapper, or second Rust build is needed.
"""

import argparse
import base64
import csv
import email
import hashlib
import io
import stat
import zipfile
from pathlib import Path

from release import python_version


def build_cli_wheel(
    executable: Path, directory: Path, version: str, platform: str, license_file: Path
) -> Path:
    version = python_version(version)
    if platform not in {
        "linux_x86_64",
        "linux_aarch64",
        "manylinux_2_39_x86_64",
        "manylinux_2_39_aarch64",
        "win_amd64",
        "macosx_11_0_arm64",
        "macosx_11_0_x86_64",
    }:
        raise ValueError("Unsupported CLI wheel platform")
    if executable.name not in {"yosoi", "yosoi.exe"} or not executable.is_file():
        raise ValueError("Expected the built yosoi executable")
    if executable.name.endswith(".exe") != (platform == "win_amd64"):
        raise ValueError("Executable does not match wheel platform")
    prefix = f"yosoi_cli-{version}"
    info = f"{prefix}.dist-info"
    tag = f"py3-none-{platform}"
    description = (
        "Yosoi command-line tool\n\n"
        "Install with `uv tool install yosoi-cli`, then run `yosoi --help`.\n"
        "For one-off use: `uvx --from yosoi-cli yosoi --help`.\n\n"
        "This package contains the prebuilt Rust CLI, without the Python SDK.\n"
        "Linux requires glibc 2.39 or newer; macOS requires 11.0 or newer.\n"
        "Chrome/Chromium for browser operations must be installed separately.\n"
    )
    files = {
        f"{prefix}.data/scripts/{executable.name}": executable.read_bytes(),
        f"{info}/METADATA": (
            "Metadata-Version: 2.4\nName: yosoi-cli\n"
            f"Version: {version}\nSummary: Prebuilt Yosoi command-line tool\n"
            "Requires-Python: >=3.10\nLicense-Expression: Apache-2.0\n"
            "License-File: LICENSE\nDescription-Content-Type: text/markdown\n"
            "Project-URL: Source, https://github.com/CascadingLabs/Yosoi\n"
            f"\n{description}"
        ).encode(),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: yosoi-release-cli\n"
            f"Root-Is-Purelib: false\nTag: {tag}\n"
        ).encode(),
        f"{info}/licenses/LICENSE": license_file.read_bytes(),
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=")
        writer.writerow((name, "sha256=" + digest.decode(), len(content)))
    writer.writerow((f"{info}/RECORD", "", ""))
    files[f"{info}/RECORD"] = record.getvalue().encode()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{prefix}-{tag}.whl"
    with (
        output.open("xb") as stream,
        zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive,
    ):
        for name, content in files.items():
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            mode = 0o755 if ".data/scripts/" in name else 0o644
            member.external_attr = (stat.S_IFREG | mode) << 16
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, content)
    return output


def verify_cli_wheels(directory: Path, release: dict) -> None:
    version = python_version(release["version"])
    expected = {row["cli_wheel_platform"] for row in release["platforms"]["include"]}
    seen = set()
    for file in directory.glob("yosoi_cli-*.whl"):
        with zipfile.ZipFile(file) as archive:
            prefix = f"yosoi_cli-{version}"
            info = f"{prefix}.dist-info"
            metadata = email.message_from_bytes(archive.read(f"{info}/METADATA"))
            wheel = email.message_from_bytes(archive.read(f"{info}/WHEEL"))
            tags = wheel.get_all("Tag", [])
            if (
                metadata["Name"] != "yosoi-cli"
                or metadata["Version"] != version
                or metadata.get_all("Requires-Dist")
                or len(tags) != 1
                or not tags[0].startswith("py3-none-")
            ):
                raise ValueError(f"Invalid CLI wheel identity: {file.name}")
            platform = tags[0].removeprefix("py3-none-")
            if platform not in expected or platform in seen:
                raise ValueError(f"Unexpected or duplicate CLI wheel: {file.name}")
            if file.name != f"{prefix}-py3-none-{platform}.whl":
                raise ValueError(
                    f"CLI wheel filename does not match metadata: {file.name}"
                )
            executable = "yosoi.exe" if platform == "win_amd64" else "yosoi"
            if not archive.read(f"{prefix}.data/scripts/{executable}"):
                raise ValueError("Empty CLI executable")
            if not archive.read(f"{info}/licenses/LICENSE"):
                raise ValueError("Missing CLI license")
            seen.add(platform)
    if seen != expected:
        raise ValueError(f"Missing CLI wheels: {sorted(expected - seen)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--output", default=Path("dist"), type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--license", default=Path("LICENSE"), type=Path)
    args = parser.parse_args()
    print(
        build_cli_wheel(
            args.executable, args.output, args.version, args.platform, args.license
        )
    )
