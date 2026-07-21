"""Shared fixtures for stub tests."""

import shutil
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
