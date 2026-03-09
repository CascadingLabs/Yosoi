"""Tests for Contract validators and semantic type coercion."""

from __future__ import annotations

import datetime as dt_module

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.models.contract import Contract


class BookContract(Contract):
    title: str = ys.Title()
    price: float = ys.Price()
    author: str = ys.Author()


# ---------------------------------------------------------------------------
# Price — default
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Price — parameterized
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# String type coercion (Title, Author, BodyText)
# ---------------------------------------------------------------------------


def test_title_strips_whitespace():
    class C(Contract):
        title: str = ys.Title()

    assert C.model_validate({'title': '  Hello World  '}).title == 'Hello World'


def test_author_strips_whitespace():
    class C(Contract):
        author: str = ys.Author()

    assert C.model_validate({'author': '\tJane Austen\n'}).author == 'Jane Austen'


def test_rating_strips_whitespace():
    class C(Contract):
        rating: str = ys.Rating()

    assert C.model_validate({'rating': '  4.5/5  '}).rating == '4.5/5'


def test_url_strips_whitespace():
    class C(Contract):
        url: str = ys.Url()

    assert C.model_validate({'url': '  https://example.com  '}).url == 'https://example.com'


def test_datetime_strips_whitespace():
    class C(Contract):
        dt: str = ys.Datetime()

    result = C.model_validate({'dt': '  2024-01-01  '})
    assert isinstance(result.dt, str)
    assert result.dt.startswith('2024-01-01')


def test_body_text_strips_whitespace():
    class C(Contract):
        body: str = ys.BodyText()

    assert C.model_validate({'body': '  Some text.  '}).body == 'Some text.'


# ---------------------------------------------------------------------------
# Datetime — default + parameterized
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Url — default + parameterized
# ---------------------------------------------------------------------------


def test_url_javascript_raises():
    class C(Contract):
        url: str = ys.Url()

    with pytest.raises(ValidationError):
        C.model_validate({'url': 'javascript:void(0)'})


def test_url_protocol_relative_prefixed():
    class C(Contract):
        url: str = ys.Url()

    result = C.model_validate({'url': '//cdn.example.com/img.png'})
    assert result.url == 'https://cdn.example.com/img.png'


def test_url_tracking_stripped():
    class C(Contract):
        url: str = ys.Url()

    result = C.model_validate({'url': 'https://example.com/page?utm_source=newsletter&id=42'})
    assert 'utm_source' not in result.url
    assert 'id=42' in result.url


def test_url_relative_resolved_via_context():
    class C(Contract):
        url: str = ys.Url()

    result = C.model_validate({'url': '/blog/post'}, context={'source_url': 'https://example.com'})
    assert result.url == 'https://example.com/blog/post'


def test_url_no_strip_tracking():
    class C(Contract):
        url: str = ys.Url(strip_tracking=False)

    result = C.model_validate({'url': 'https://example.com/page?utm_source=newsletter&id=42'})
    assert 'utm_source' in result.url


# ---------------------------------------------------------------------------
# Rating — default + parameterized
# ---------------------------------------------------------------------------


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
# Combined: Validators inner class + type coercion
# ---------------------------------------------------------------------------


def test_validators_and_type_coercion_combined():
    """Validators inner class runs before Price coercion."""

    class ShopContract(Contract):
        price: float = ys.Price()

        class Validators:
            @staticmethod
            def price(v: str) -> str:
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
        title: str = ys.Title()
        price: float = ys.Price()

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
        price: float = ys.Price()

    pipeline = MagicMock(spec=Pipeline)
    pipeline.contract = StrictContract
    pipeline.console = MagicMock()
    pipeline.logger = MagicMock()

    raw = {'price': 'not-a-number'}
    result = Pipeline._validate_with_contract(pipeline, raw)

    assert result is raw
    pipeline.logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Contract.generate_manifest
# ---------------------------------------------------------------------------


def test_contract_generate_manifest():
    manifest = BookContract.generate_manifest()
    assert '# BookContract' in manifest
    assert '| `price`' in manifest
    assert '`price`' in manifest


# ---------------------------------------------------------------------------
# @ys.validator("field") — Atomic Field Validators
# ---------------------------------------------------------------------------


def test_field_validator_transforms_value():
    class C(Contract):
        sku: str

        @ys.validator('sku')
        @classmethod
        def validate_sku(cls, v: str) -> str:
            return v.upper()

    result = C.model_validate({'sku': 'abc-123'})
    assert result.sku == 'ABC-123'


def test_field_validator_raises_on_invalid():
    class C(Contract):
        sku: str

        @ys.validator('sku')
        @classmethod
        def validate_sku(cls, v: str) -> str:
            if not v.startswith('ABC-'):
                raise ValueError('Invalid SKU format')
            return v

    with pytest.raises(ValidationError):
        C.model_validate({'sku': 'XYZ-999'})

    result = C.model_validate({'sku': 'ABC-001'})
    assert result.sku == 'ABC-001'


def test_field_validator_runs_after_coercion():
    """Field validators see the coerced value, not the raw string."""

    class C(Contract):
        price: float = ys.Price()

        @ys.validator('price')
        @classmethod
        def validate_min_price(cls, v: float) -> float:
            if v < 1.0:
                raise ValueError('Price too low')
            return v

    # Price coercion runs first (£ → float), then field validator checks
    result = C.model_validate({'price': '£5.00'})
    assert result.price == 5.0

    with pytest.raises(ValidationError):
        C.model_validate({'price': '£0.50'})


def test_field_validator_multiple_fields():
    """A single validator can target multiple fields."""

    class C(Contract):
        name: str
        category: str

        @ys.validator('name', 'category')
        @classmethod
        def strip_and_upper(cls, v: str) -> str:
            return v.strip().upper()

    result = C.model_validate({'name': '  laptop  ', 'category': '  tech  '})
    assert result.name == 'LAPTOP'
    assert result.category == 'TECH'


def test_field_validator_skips_missing_fields():
    """Validators don't run for fields absent from the input data."""

    class C(Contract):
        name: str
        tag: str = 'default'

        @ys.validator('tag')
        @classmethod
        def validate_tag(cls, v: str) -> str:
            if v == 'bad':
                raise ValueError('bad tag')
            return v

    result = C.model_validate({'name': 'item'})
    assert result.tag == 'default'


# ---------------------------------------------------------------------------
# @ys.validator() — Holistic Model Validators
# ---------------------------------------------------------------------------


def test_model_validator_checks_cross_field_logic():
    class C(Contract):
        price: float = ys.Price()
        sale_price: float = ys.Price(description='Sale Price', default=0.0)

        @ys.validator()
        def validate_sale_logic(self) -> C:
            if self.sale_price > self.price:
                raise ValueError(f'Sale price ({self.sale_price}) cannot exceed list price ({self.price})')
            return self

    # Valid: sale < price
    result = C.model_validate({'price': '$100.00', 'sale_price': '$79.99'})
    assert result.price == 100.0
    assert result.sale_price == 79.99

    # Invalid: sale > price
    with pytest.raises(ValidationError):
        C.model_validate({'price': '$50.00', 'sale_price': '$75.00'})


def test_model_validator_can_mutate_instance():
    class C(Contract):
        name: str
        slug: str = ''

        @ys.validator()
        def generate_slug(self) -> C:
            if not self.slug:
                self.slug = self.name.lower().replace(' ', '-')
            return self

    result = C.model_validate({'name': 'Hello World'})
    assert result.slug == 'hello-world'


# ---------------------------------------------------------------------------
# Combined: @ys.validator field + model + inner Validators + coercion
# ---------------------------------------------------------------------------


def test_full_validator_pipeline():
    """Inner Validators → coercion → @ys.validator(field) → pydantic → @ys.validator() model."""

    class ProductContract(Contract):
        name: str = ys.Title(description='Product Title')
        price: float = ys.Price(description='Original Price')
        sale_price: float = ys.Price(description='Sale Price', default=0.0)
        sku: str

        class Validators:
            @staticmethod
            def name(v: str) -> str:
                # Step 1: inner Validators pre-coercion transform
                return v.strip()

        @ys.validator('sku')
        @classmethod
        def validate_sku_format(cls, v: str) -> str:
            # Step 3: field validator post-coercion
            if not v.startswith('ABC-'):
                raise ValueError('Invalid SKU format for this site')
            return v

        @ys.validator()
        def validate_sale_logic(self) -> ProductContract:
            # Step 5: model validator post-construction
            if self.sale_price > self.price:
                raise ValueError(f'Sale price ({self.sale_price}) cannot exceed list price ({self.price})')
            return self

    # Everything passes
    result = ProductContract.model_validate(
        {'name': '  Widget  ', 'price': '$99.99', 'sale_price': '$49.99', 'sku': 'ABC-001'}
    )
    assert result.name == 'Widget'
    assert result.price == 99.99
    assert result.sale_price == 49.99
    assert result.sku == 'ABC-001'

    # SKU field validator rejects
    with pytest.raises(ValidationError):
        ProductContract.model_validate({'name': 'Widget', 'price': '$99.99', 'sale_price': '$49.99', 'sku': 'XYZ-001'})

    # Model validator rejects (sale > price)
    with pytest.raises(ValidationError):
        ProductContract.model_validate({'name': 'Widget', 'price': '$10.00', 'sale_price': '$20.00', 'sku': 'ABC-001'})
