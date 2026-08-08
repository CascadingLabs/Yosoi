"""Shared paths for deterministic observation boss fights."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope='session')
def boss_fights_root() -> Path:
    """Return the root containing modality workloads and frozen artifacts."""
    return Path(__file__).parent
