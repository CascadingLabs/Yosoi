"""Tests for the yosoi-aware Field wrapper."""

from pydantic.fields import FieldInfo

from yosoi.types.field import Field


def test_field_returns_field_info():
    result = Field()
    assert isinstance(result, FieldInfo)


def test_field_no_args_returns_empty_schema_extra():
    result = Field()
    # No hint, no frozen, no selector → json_schema_extra is None or empty
    if result.json_schema_extra is not None:
        assert isinstance(result.json_schema_extra, dict)
        assert 'yosoi_hint' not in result.json_schema_extra
        assert 'yosoi_frozen' not in result.json_schema_extra
        assert 'yosoi_selector' not in result.json_schema_extra


def test_field_with_hint_sets_yosoi_hint():
    result = Field(hint='Look for the price')
    assert isinstance(result.json_schema_extra, dict)
    assert result.json_schema_extra['yosoi_hint'] == 'Look for the price'


def test_field_without_hint_no_yosoi_hint():
    result = Field()
    extra = result.json_schema_extra
    if extra is not None:
        assert isinstance(extra, dict)
        assert 'yosoi_hint' not in extra


def test_field_with_frozen_true_sets_yosoi_frozen():
    result = Field(frozen=True)
    assert isinstance(result.json_schema_extra, dict)
    assert result.json_schema_extra['yosoi_frozen'] is True


def test_field_with_frozen_false_no_yosoi_frozen():
    result = Field(frozen=False)
    extra = result.json_schema_extra
    if extra is not None:
        assert isinstance(extra, dict)
        assert 'yosoi_frozen' not in extra


def test_field_with_selector_sets_yosoi_selector():
    result = Field(selector='h1.title')
    assert isinstance(result.json_schema_extra, dict)
    assert result.json_schema_extra['yosoi_selector'] == 'h1.title'


def test_field_without_selector_no_yosoi_selector():
    result = Field()
    extra = result.json_schema_extra
    if extra is not None:
        assert isinstance(extra, dict)
        assert 'yosoi_selector' not in extra


def test_field_hint_and_frozen_together():
    result = Field(hint='Find it', frozen=True)
    extra = result.json_schema_extra
    assert isinstance(extra, dict)
    assert extra['yosoi_hint'] == 'Find it'
    assert extra['yosoi_frozen'] is True


def test_field_all_three_options():
    result = Field(hint='My hint', frozen=True, selector='p.class')
    extra = result.json_schema_extra
    assert isinstance(extra, dict)
    assert extra['yosoi_hint'] == 'My hint'
    assert extra['yosoi_frozen'] is True
    assert extra['yosoi_selector'] == 'p.class'


def test_field_passes_kwargs_to_pydantic_field():
    result = Field(description='A test field')
    assert result.description == 'A test field'


def test_field_with_existing_json_schema_extra():
    result = Field(json_schema_extra={'custom_key': 'custom_val'}, hint='My hint')
    extra = result.json_schema_extra
    assert isinstance(extra, dict)
    assert extra['custom_key'] == 'custom_val'
    assert extra['yosoi_hint'] == 'My hint'


def test_field_frozen_false_not_stored():
    """frozen=False means the key should NOT be in extra."""
    result = Field(frozen=False)
    extra = result.json_schema_extra
    # frozen=False → should not add yosoi_frozen key
    if extra is not None and isinstance(extra, dict):
        assert extra.get('yosoi_frozen') is not True


def test_field_hint_none_not_stored():
    """hint=None means yosoi_hint should NOT be in extra."""
    result = Field(hint=None)
    extra = result.json_schema_extra
    if extra is not None and isinstance(extra, dict):
        assert 'yosoi_hint' not in extra


def test_field_selector_none_not_stored():
    """selector=None means yosoi_selector should NOT be in extra."""
    result = Field(selector=None)
    extra = result.json_schema_extra
    if extra is not None and isinstance(extra, dict):
        assert 'yosoi_selector' not in extra


def test_field_hint_exact_value_stored():
    """The exact hint string must be stored in yosoi_hint."""
    hint = 'Look for the price element'
    result = Field(hint=hint)
    assert isinstance(result.json_schema_extra, dict)
    assert result.json_schema_extra['yosoi_hint'] == hint


def test_field_frozen_true_value_is_true():
    """yosoi_frozen must be exactly True, not a truthy value like 1."""
    result = Field(frozen=True)
    assert isinstance(result.json_schema_extra, dict)
    assert result.json_schema_extra['yosoi_frozen'] is True


def test_field_selector_exact_value_stored():
    """The exact selector string must be stored in yosoi_selector."""
    selector = 'div.product-price > span.amount'
    result = Field(selector=selector)
    assert isinstance(result.json_schema_extra, dict)
    assert result.json_schema_extra['yosoi_selector'] == selector


def test_field_no_hint_no_frozen_no_selector_extra_is_none():
    """With no yosoi args, json_schema_extra should be None."""
    result = Field()
    assert result.json_schema_extra is None


def test_field_existing_json_schema_extra_preserved_exactly():
    """Existing json_schema_extra keys must not be overwritten."""
    result = Field(json_schema_extra={'my_custom': 42}, hint='test')
    extra = result.json_schema_extra
    assert isinstance(extra, dict)
    assert extra['my_custom'] == 42
    assert extra['yosoi_hint'] == 'test'


def test_field_hint_condition_checks_truthiness():
    """Only truthy hint values should set yosoi_hint (empty string should not)."""
    result = Field(hint='')
    extra = result.json_schema_extra
    if extra is not None and isinstance(extra, dict):
        assert 'yosoi_hint' not in extra
