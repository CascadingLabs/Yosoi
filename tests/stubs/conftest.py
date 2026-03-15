"""Shared fixtures for stub tests."""

import shutil
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest

SNIPPETS_DIR = Path(__file__).parent / 'snippets'


@pytest.fixture(scope='session')
def snippets_dir() -> Generator[Path, None, None]:
    """Ensure SNIPPETS_DIR exists for the session and clean it up on teardown."""
    SNIPPETS_DIR.mkdir(exist_ok=True)
    yield SNIPPETS_DIR
    shutil.rmtree(SNIPPETS_DIR, ignore_errors=True)


@pytest.fixture(autouse=True, scope='session')
def _warm_mypy_cache(snippets_dir: Path) -> None:
    """Pre-warm the mypy cache so individual tests don't hit cold-start timeout."""
    warmup = snippets_dir / '_warmup.py'
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
