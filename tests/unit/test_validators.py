"""Tests for Contract validators and semantic type coercion."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.models.contract import Contract


class BookContract(Contract):
    title: ys.Title
    price: ys.Price
    author: ys.Author


# ---------------------------------------------------------------------------
# Price BeforeValidator
# ---------------------------------------------------------------------------


def test_price_strips_pound():
    class C(Contract):
        price: ys.Price

    assert C.model_validate({'price': '£12.99'}).price == 12.99


def test_price_strips_dollar_and_comma():
    class C(Contract):
        price: ys.Price

    assert C.model_validate({'price': '$1,000.00'}).price == 1000.0


def test_price_strips_euro():
    class C(Contract):
        price: ys.Price

    assert C.model_validate({'price': '€9.99'}).price == 9.99


def test_price_numeric_passthrough():
    class C(Contract):
        price: ys.Price

    assert C.model_validate({'price': 42.5}).price == 42.5


def test_price_int_passthrough():
    class C(Contract):
        price: ys.Price

    assert C.model_validate({'price': 10}).price == 10.0


# ---------------------------------------------------------------------------
# String type BeforeValidators
# ---------------------------------------------------------------------------


def test_title_strips_whitespace():
    class C(Contract):
        title: ys.Title

    assert C.model_validate({'title': '  Hello World  '}).title == 'Hello World'


def test_author_strips_whitespace():
    class C(Contract):
        author: ys.Author

    assert C.model_validate({'author': '\tJane Austen\n'}).author == 'Jane Austen'


def test_rating_strips_whitespace():
    class C(Contract):
        rating: ys.Rating

    assert C.model_validate({'rating': '  4.5/5  '}).rating == '4.5/5'


def test_url_strips_whitespace():
    class C(Contract):
        url: ys.Url

    assert C.model_validate({'url': '  https://example.com  '}).url == 'https://example.com'


def test_datetime_strips_whitespace():
    class C(Contract):
        dt: ys.Datetime

    assert C.model_validate({'dt': '  2024-01-01  '}).dt == '2024-01-01'


def test_body_text_strips_whitespace():
    class C(Contract):
        body: ys.BodyText

    assert C.model_validate({'body': '  Some text.  '}).body == 'Some text.'


# ---------------------------------------------------------------------------
# Validators inner class
# ---------------------------------------------------------------------------


def test_validators_inner_class_transforms():
    class ProductContract(Contract):
        name: str
        category: str

        class Validators:
            @staticmethod
            def name(v: str) -> str:
                return v.title()

            @staticmethod
            def category(v: str) -> str:
                return v.upper()

    result = ProductContract.model_validate({'name': 'laptop stand', 'category': 'accessories'})
    assert result.name == 'Laptop Stand'
    assert result.category == 'ACCESSORIES'


def test_validators_inner_class_value_error_propagates():
    class StrictContract(Contract):
        price: str

        class Validators:
            @staticmethod
            def price(v: str) -> str:
                if not v.startswith('$'):
                    raise ValueError('price must start with $')
                return v

    with pytest.raises(ValidationError):
        StrictContract.model_validate({'price': '12.99'})


def test_validators_only_applies_defined_fields():
    """Fields without a Validators method are passed through unchanged."""

    class PartialContract(Contract):
        name: str
        description: str

        class Validators:
            @staticmethod
            def name(v: str) -> str:
                return v.upper()

    result = PartialContract.model_validate({'name': 'item', 'description': '  some desc  '})
    assert result.name == 'ITEM'
    assert result.description == '  some desc  '


# ---------------------------------------------------------------------------
# Combined: Validators inner class + type BeforeValidator
# ---------------------------------------------------------------------------


def test_validators_and_type_coercion_combined():
    """Validators inner class runs before Price BeforeValidator."""

    class ShopContract(Contract):
        price: ys.Price

        class Validators:
            @staticmethod
            def price(v: str) -> str:
                # Strip a custom prefix before Price's BeforeValidator strips currency
                return v.removeprefix('PRICE:').strip()

    result = ShopContract.model_validate({'price': 'PRICE: £19.99'})
    assert result.price == 19.99


# ---------------------------------------------------------------------------
# Pipeline _validate_with_contract (unit test with mock contract)
# ---------------------------------------------------------------------------


def test_pipeline_validate_with_contract_success():
    """_validate_with_contract returns validated dict on success."""
    from unittest.mock import MagicMock

    from yosoi.core.pipeline import Pipeline

    class SimpleContract(Contract):
        title: ys.Title
        price: ys.Price

    pipeline = MagicMock(spec=Pipeline)
    pipeline.contract = SimpleContract
    pipeline.console = MagicMock()
    pipeline.logger = MagicMock()

    result = Pipeline._validate_with_contract(pipeline, {'title': '  Book  ', 'price': '£9.99'})

    assert result['title'] == 'Book'
    assert result['price'] == 9.99


def test_pipeline_validate_with_contract_fallback_on_error():
    """_validate_with_contract falls back to raw data on validation error."""
    from unittest.mock import MagicMock

    from yosoi.core.pipeline import Pipeline

    class StrictContract(Contract):
        price: ys.Price

    pipeline = MagicMock(spec=Pipeline)
    pipeline.contract = StrictContract
    pipeline.console = MagicMock()
    pipeline.logger = MagicMock()

    raw = {'price': 'not-a-number'}
    result = Pipeline._validate_with_contract(pipeline, raw)

    # Should fall back to original dict
    assert result is raw
    pipeline.logger.warning.assert_called_once()
