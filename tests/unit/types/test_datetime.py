"""Tests for Datetime type coercion."""

from __future__ import annotations

import datetime as dt_module

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.models.contract import Contract


def test_datetime_strips_whitespace():
    class C(Contract):
        dt: str = ys.Datetime()

    result = C.model_validate({'dt': '  2024-01-01  '})
    assert isinstance(result.dt, str)
    assert result.dt.startswith('2024-01-01')


def test_datetime_editorial_prefix_stripped():
    class C(Contract):
        dt: str = ys.Datetime()

    result = C.model_validate({'dt': 'Updated: 2026-03-08T14:30:24Z'})
    assert isinstance(result.dt, str)
    assert '2026-03-08' in result.dt


def test_datetime_ordinal_suffix():
    class C(Contract):
        dt: str = ys.Datetime()

    result = C.model_validate({'dt': 'March 8th, 2026'})
    assert isinstance(result.dt, str)
    assert '2026-03-08' in result.dt


def test_datetime_relative_time():
    class C(Contract):
        dt: str = ys.Datetime()

    result = C.model_validate({'dt': '2 days ago'})
    assert isinstance(result.dt, str)
    parsed = dt_module.datetime.fromisoformat(result.dt)
    assert parsed < dt_module.datetime.now(dt_module.timezone.utc)


def test_datetime_unparseable_raises():
    class C(Contract):
        dt: str = ys.Datetime()

    with pytest.raises(ValidationError):
        C.model_validate({'dt': 'not a date xyz'})


def test_datetime_as_object():
    class C(Contract):
        dt: dt_module.datetime = ys.Datetime(as_iso=False)

    result = C.model_validate({'dt': '2024-06-15T12:00:00Z'})
    assert isinstance(result.dt, dt_module.datetime)
