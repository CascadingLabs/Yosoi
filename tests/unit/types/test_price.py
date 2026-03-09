"""Tests for Price type coercion."""

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.models.contract import Contract


def test_price_strips_pound():
    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': '£12.99'}).price == 12.99


def test_price_strips_dollar_and_comma():
    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': '$1,000.00'}).price == 1000.0


def test_price_strips_euro():
    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': '€9.99'}).price == 9.99


def test_price_numeric_passthrough():
    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': 42.5}).price == 42.5


def test_price_int_passthrough():
    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': 10}).price == 10.0


def test_price_free_returns_zero():
    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': 'Free'}).price == 0.0


def test_price_eu_thousands_and_decimal():
    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': '1.200,50 €'}).price == 1200.50


def test_price_eu_comma_decimal_only():
    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': '49,99 €'}).price == 49.99


def test_price_trailing_billing_text():
    class C(Contract):
        price: float = ys.Price()

    assert C.model_validate({'price': '$49.99 / month'}).price == 49.99


def test_price_currency_symbol_enforced():
    class C(Contract):
        price: float = ys.Price(currency_symbol='£')

    with pytest.raises(ValidationError):
        C.model_validate({'price': '$19.99'})


def test_price_optional_accepts_none_input():
    class C(Contract):
        price: float | None = ys.Price()

    result = C.model_validate({'price': None})
    assert result.price is None


def test_price_require_decimals():
    class C(Contract):
        price: float = ys.Price(require_decimals=True)

    with pytest.raises(ValidationError):
        C.model_validate({'price': '$100'})

    assert C.model_validate({'price': '$100.00'}).price == 100.0
