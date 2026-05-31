"""Shared fixtures for browser integration tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope='session')
def no_sandbox() -> bool:
    """Whether Chrome should launch with --no-sandbox.

    CI runners (GitHub Actions) disable unprivileged user namespaces, so the
    Chromium zygote aborts with "No usable sandbox!" (exit 134) unless the
    sandbox is turned off. Locally the sandbox stays on. Driven by
    ``YOSOI_NO_SANDBOX`` (set in the CI workflow), falling back to the standard
    ``CI`` marker so the tests also pass on stock CI environments.
    """
    return os.environ.get('YOSOI_NO_SANDBOX', os.environ.get('CI', '')).lower() in ('1', 'true', 'yes')
