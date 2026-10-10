"""Make Maturin's reduced-workspace sdist buildable with Cargo --locked."""

from __future__ import annotations

import argparse
import copy
import gzip
import os
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path


def locked_packages(data: bytes) -> set[tuple]:
    return {
        (p["name"], p["version"], p.get("source"), p.get("checksum"))
        for p in tomllib.loads(data.decode())["package"]
    }


def verify_resolution(original: bytes, resolved: bytes) -> None:
    unexpected = locked_packages(resolved) - locked_packages(original)
    if unexpected:
        raise ValueError(
            f"Sdist resolution changed locked package identities: {unexpected}"
        )


def prepare(archive_path: Path) -> None:
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        with tarfile.open(archive_path, "r:gz") as archive:
            locks = [
                m
                for m in archive.getmembers()
                if m.name.count("/") == 1
                and m.name.endswith("/Cargo.lock")
                and m.isfile()
            ]
            if len(locks) != 1:
                raise ValueError("Sdist must contain exactly one workspace Cargo.lock")
            lock_member = locks[0]
            archive.extractall(temporary, filter="data")
            root = temporary / lock_member.name.split("/")[0]
            lock_path = temporary / lock_member.name
            original = lock_path.read_bytes()
            manifest = root / "crates/yosoi-python/Cargo.toml"
            command = [
                "cargo",
                "metadata",
                "--offline",
                "--format-version",
                "1",
                "--manifest-path",
                str(manifest),
            ]
            subprocess.run(command, cwd=root, check=True, stdout=subprocess.DEVNULL)
            resolved = lock_path.read_bytes()
            verify_resolution(original, resolved)
            subprocess.run(
                command + ["--locked"], cwd=root, check=True, stdout=subprocess.DEVNULL
            )
            if original == resolved:
                return
            # Only the lock changes. Preserve payload/permissions and canonicalize
            # archive ownership/timestamps so every wheel consumes identical bytes.
            with tempfile.NamedTemporaryFile(
                dir=archive_path.parent, delete=False
            ) as output:
                prepared = Path(output.name)
                try:
                    with gzip.GzipFile(
                        fileobj=output, mode="wb", filename="", mtime=0
                    ) as zipped:
                        with tarfile.open(fileobj=zipped, mode="w") as packed:
                            for member in archive.getmembers():
                                header = copy.copy(member)
                                header.uid = header.gid = header.mtime = 0
                                header.uname = header.gname = ""
                                header.pax_headers = {
                                    key: value
                                    for key, value in header.pax_headers.items()
                                    if key
                                    not in {
                                        "mtime",
                                        "atime",
                                        "ctime",
                                        "uid",
                                        "gid",
                                        "uname",
                                        "gname",
                                    }
                                }
                                if member.name == lock_member.name:
                                    header.size = len(resolved)
                                    with lock_path.open("rb") as content:
                                        packed.addfile(header, content)
                                else:
                                    packed.addfile(
                                        header,
                                        archive.extractfile(member)
                                        if member.isfile()
                                        else None,
                                    )
                    output.flush()
                    os.fsync(output.fileno())
                    prepared.chmod(archive_path.stat().st_mode)
                except BaseException:
                    prepared.unlink(missing_ok=True)
                    raise
        try:
            prepared.replace(archive_path)
        finally:
            prepared.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    prepare(parser.parse_args().archive)
