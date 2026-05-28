"""Tests for Count type coercion."""

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.models.contract import Contract


class _CountContract(Contract):
    n: int = ys.Count()


def _coerce(raw: object) -> int:
    return _CountContract.model_validate({'n': raw}).n


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_count_from_plain_digits() -> None:
    assert _coerce('42') == 42


def test_count_from_int_passthrough() -> None:
    assert _coerce(42) == 42


def test_count_from_int_zero() -> None:
    assert _coerce(0) == 0


def test_count_from_thousands_separator() -> None:
    assert _coerce('12,345') == 12_345


def test_count_strips_surrounding_whitespace() -> None:
    assert _coerce('  9  ') == 9


def test_count_keeps_numeric_prefix_drops_trailing_label() -> None:
    """`'9 comments'` is the very common reddit/HN shape — numeric prefix wins."""
    assert _coerce('9 comments') == 9
    assert _coerce('1,234 upvotes') == 1_234


# ---------------------------------------------------------------------------
# SI suffixes (reddit, YouTube, Twitter style)
# ---------------------------------------------------------------------------


def test_count_k_suffix() -> None:
    assert _coerce('4.2K') == 4_200
    assert _coerce('4k') == 4_000


def test_count_m_suffix() -> None:
    assert _coerce('1.3M') == 1_300_000


def test_count_b_suffix() -> None:
    assert _coerce('2B') == 2_000_000_000


def test_count_g_alias_for_billion() -> None:
    assert _coerce('2G') == 2_000_000_000


def test_count_suffix_case_insensitive() -> None:
    assert _coerce('5k') == 5_000
    assert _coerce('5K') == 5_000


# ---------------------------------------------------------------------------
# "Zero" synonyms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('raw', ['none', 'No', 'no comments', 'no replies', '-'])
def test_count_zero_synonyms(raw: str) -> None:
    assert _coerce(raw) == 0


# ---------------------------------------------------------------------------
# Failures — wrong-selector output rejected
# ---------------------------------------------------------------------------


def test_count_rejects_none() -> None:
    with pytest.raises(ValidationError):
        _coerce(None)


def test_count_rejects_empty_string() -> None:
    with pytest.raises(ValidationError):
        _coerce('')


def test_count_rejects_bool() -> None:
    """bool is an int subclass — guard so True/False don't silently coerce to 1/0."""
    with pytest.raises(ValidationError):
        _coerce(True)


def test_count_rejects_negative_int() -> None:
    with pytest.raises(ValidationError):
        _coerce(-3)


def test_count_rejects_negative_string() -> None:
    with pytest.raises(ValidationError):
        _coerce('-3')


def test_count_rejects_pure_text() -> None:
    """`shreddit-post` returning full card text — exactly the wrong-selector regression
    this type is meant to catch downstream of the SemanticValidator."""
    with pytest.raises(ValidationError):
        _coerce('Facebook deleted 15m hate speech posts...')


def test_count_rejects_nan() -> None:
    with pytest.raises(ValidationError):
        _coerce(float('nan'))


# ---------------------------------------------------------------------------
# Float passthrough — only integer-shaped non-negative
# ---------------------------------------------------------------------------


def test_count_float_passthrough_truncates() -> None:
    """Sites that hand us already-parsed floats (e.g. `42.0`) coerce cleanly."""
    assert _coerce(42.0) == 42
