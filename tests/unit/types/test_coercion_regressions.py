"""Regression tests for hard-coded-heuristic bugs in type coercion (CAS-94 cleanup).

Each test pins a concrete input that the previous heuristic got wrong:
- rating word-map matched via ``startswith`` ("tens of reviews" -> 10.0)
- price zero-words matched as a substring ("free shipping over $50" -> 0.0)
- url tracking prefix ``ref`` over-stripped ("reference=" / "ref_id=")
- datetime label-stripping was English-only and could be mangled by a time colon
"""

from __future__ import annotations

import datetime as dt_module

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.models.contract import Contract

# --- rating: whole-word, not startswith -------------------------------------------


def test_rating_tens_is_not_ten():
    """'tens of reviews' must not match the word 'ten' -> 10.0."""

    class C(Contract):
        rating: float = ys.Rating(as_float=True, scale=10)

    with pytest.raises(ValidationError):
        C.model_validate({'rating': 'tens of reviews'})


def test_rating_word_still_coerces():
    """The legitimate word-rating path still works after the whole-word fix."""

    class C(Contract):
        rating: float = ys.Rating(as_float=True)

    assert C.model_validate({'rating': 'Three stars'}).rating == 3.0


def test_rating_word_map_is_overridable():
    """Non-English worded ratings work via an overridable word_map (not English-only SSoT)."""

    class C(Contract):
        rating: float = ys.Rating(as_float=True, word_map={'trois': 3, 'cinq': 5})

    assert C.model_validate({'rating': 'trois étoiles'}).rating == 3.0
    assert C.model_validate({'rating': 'cinq'}).rating == 5.0


# --- price: zero-words only when no number is present ------------------------------


def test_price_free_shipping_keeps_real_number():
    """'free shipping over $50' has a real price -> 50.0, not 0.0."""

    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': 'free shipping over $50'}).price == 50.0


def test_price_bare_free_still_zero():
    """A bare 'Free' (no number) still coerces to 0.0."""

    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': 'Free'}).price == 0.0


def test_price_zero_value_words_overridable():
    """Non-English zero-price words work via an overridable list (not English-only SSoT)."""

    class C(Contract):
        price: float = ys.Price(zero_value_words=('無料', 'gratuit'))

    assert C.model_validate({'price': '無料'}).price == 0.0
    assert C.model_validate({'price': 'gratuit'}).price == 0.0


# --- url: exact-key vs prefix tracking match --------------------------------------


def test_url_ref_strips_exact_key_only():
    """'ref' strips ref= but never reference= / ref_id= (was an over-broad startswith)."""

    class C(Contract):
        url: str = ys.Url()

    result = C.model_validate({'url': 'https://example.com/p?ref=twitter&reference=42&ref_id=7'})
    assert 'ref=twitter' not in result.url
    assert 'reference=42' in result.url
    assert 'ref_id=7' in result.url


def test_url_utm_prefix_still_stripped():
    """utm_ remains a prefix match (utm_source, utm_campaign, ...)."""

    class C(Contract):
        url: str = ys.Url()

    result = C.model_validate({'url': 'https://example.com/p?utm_campaign=x&keep=1'})
    assert 'utm_campaign' not in result.url
    assert 'keep=1' in result.url


# --- datetime: language-agnostic label strip, no over-strip ------------------------


def test_datetime_non_english_label_stripped():
    """A labelled date in any language parses (dateparser returns None on the raw label)."""

    class C(Contract):
        dt: str = ys.Datetime()

    result = C.model_validate({'dt': 'Veröffentlicht: 2020-01-05'})
    assert result.dt.startswith('2020-01-05')


def test_datetime_english_label_still_stripped():
    """The original English 'Label:' behaviour is preserved by the generic strip."""

    class C(Contract):
        dt: str = ys.Datetime()

    result = C.model_validate({'dt': 'Published: 2020-01-05'})
    assert result.dt.startswith('2020-01-05')


def test_datetime_time_colon_not_mangled():
    """A date containing a time must not be eaten by the leading-label strip."""

    class C(Contract):
        dt: dt_module.datetime = ys.Datetime(as_iso=False)

    result = C.model_validate({'dt': 'Jan 5 2020 10:30'})
    assert result.dt.hour == 10
    assert result.dt.minute == 30


def test_datetime_posted_on_default_still_works():
    """The no-colon 'posted on' idiom remains a working default."""

    class C(Contract):
        dt: str = ys.Datetime()

    result = C.model_validate({'dt': 'Posted on March 3, 2021'})
    assert result.dt.startswith('2021-03-03')


def test_datetime_strip_prefixes_overridable():
    """The no-colon idiom list is an overridable default, not the source of truth."""

    class C(Contract):
        dt: str = ys.Datetime(strip_prefixes=('veröffentlicht am',))

    result = C.model_validate({'dt': 'veröffentlicht am 5 January 2020'})
    assert result.dt.startswith('2020-01-05')
