#!/usr/bin/env python3
"""Normalize generated text artifacts for stable, whitespace-clean repository diffs."""
from __future__ import annotations

import argparse
from pathlib import Path


def normalize(root: Path) -> None:
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        lines = [line.rstrip(" \t") for line in text.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()
    normalize(arguments.directory)


if __name__ == "__main__":
    main()
