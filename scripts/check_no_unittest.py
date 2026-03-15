#!/usr/bin/env python3
"""Check that no Python files import unittest (use pytest/pytest-mock instead)."""

import re
import sys
from pathlib import Path

BANNED = re.compile(r'^\s*(import unittest|from unittest\b)', re.MULTILINE)


def check_files(paths: list[Path]) -> int:
    """Check for unittest imports and return 1 if any are found."""
    violations: list[tuple[Path, int, str]] = []
    for path in paths:
        try:
            text = path.read_text(encoding='utf-8')
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if BANNED.match(line):
                violations.append((path, lineno, line.strip()))

    for path, lineno, line in violations:
        print(f'{path}:{lineno}: {line}')

    if violations:
        print('\nUse pytest / pytest-mock instead of unittest.')
        return 1
    return 0


if __name__ == '__main__':
    files = [Path(p) for p in sys.argv[1:]] if sys.argv[1:] else list(Path('.').rglob('*.py'))
    sys.exit(check_files(files))
