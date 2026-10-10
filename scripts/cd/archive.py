"""Create a deterministic CLI archive on all native runner platforms."""

import argparse
import gzip
import tarfile
from pathlib import Path


def cli_archive(executable: Path, output: Path) -> None:
    if not executable.is_file():
        raise ValueError("CLI executable is missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                info = tarfile.TarInfo(executable.name)
                info.size = executable.stat().st_size
                info.mode = 0o755
                info.mtime = 0
                with executable.open("rb") as content:
                    archive.addfile(info, content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    cli_archive(arguments.executable, arguments.output)
