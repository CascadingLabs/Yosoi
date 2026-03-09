"""Tests for FieldSelectors model."""

from yosoi.models.selectors import FieldSelectors


def test_as_tuples_returns_three_entries():
    fs = FieldSelectors(primary='h1', fallback='h2', tertiary='h3')
    result = fs.as_tuples()
    assert len(result) == 3


def test_as_tuples_correct_levels_and_values():
    fs = FieldSelectors(primary='h1', fallback='h2', tertiary='h3')
    result = fs.as_tuples()
    assert result[0] == ('primary', 'h1')
    assert result[1] == ('fallback', 'h2')
    assert result[2] == ('tertiary', 'h3')


def test_as_tuples_none_fallback_preserved():
    fs = FieldSelectors(primary='h1')
    result = fs.as_tuples()
    assert result[1] == ('fallback', None)
    assert result[2] == ('tertiary', None)


def test_as_tuples_partial_none():
    fs = FieldSelectors(primary='h1', fallback='.title', tertiary=None)
    result = fs.as_tuples()
    assert result[1] == ('fallback', '.title')
    assert result[2] == ('tertiary', None)
