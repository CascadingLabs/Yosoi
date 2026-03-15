"""Shared fixtures for stub tests."""

import subprocess
import sys
from pathlib import Path

import pytest

SNIPPETS_DIR = Path(__file__).parent / 'snippets'


@pytest.fixture(autouse=True, scope='session')
def _warm_mypy_cache() -> None:
    """Pre-warm the mypy cache so individual tests don't hit cold-start timeout."""
    SNIPPETS_DIR.mkdir(exist_ok=True)
    warmup = SNIPPETS_DIR / '_warmup.py'
    warmup.write_text('import yosoi\n')
    try:
        subprocess.run(
            [sys.executable, '-m', 'mypy', '--strict', '--no-error-summary', str(warmup)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        warmup.unlink(missing_ok=True)
