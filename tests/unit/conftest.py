"""Shared fixtures for unit tests."""

import pytest

import yosoi.core.tasks as _tasks_mod


@pytest.fixture
def clean_broker():
    """Ensure broker state is clean before and after each test."""
    _tasks_mod._pipeline_config = None
    yield
    _tasks_mod._pipeline_config = None
