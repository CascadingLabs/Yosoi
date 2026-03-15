"""Tests for Rating type coercion."""

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.models.contract import Contract


def test_rating_strips_whitespace():
    class C(Contract):
        rating: str = ys.Rating()

    assert C.model_validate({'rating': '  4.5/5  '}).rating == '4.5/5'


def test_rating_word_to_float():
    class C(Contract):
        rating: float = ys.Rating(as_float=True)

    assert C.model_validate({'rating': 'Three stars'}).rating == 3.0


def test_rating_fraction_to_float():
    class C(Contract):
        rating: float = ys.Rating(as_float=True)

    assert C.model_validate({'rating': '4.5 out of 5'}).rating == 4.5


def test_rating_default_str_passthrough():
    class C(Contract):
        rating: str = ys.Rating()

    assert C.model_validate({'rating': 'Four'}).rating == 'Four'


def test_rating_exceeds_scale_raises():
    class C(Contract):
        rating: float = ys.Rating(as_float=True, scale=5)

    with pytest.raises(ValidationError):
        C.model_validate({'rating': '11 stars'})
