"""Tests for the yosoi-aware Field wrapper."""

import pytest
from pydantic.fields import FieldInfo

from yosoi.types.field import Field, js


def test_field_returns_field_info():
    result = Field()
    assert isinstance(result, FieldInfo)


def test_field_no_args_returns_empty_schema_extra():
    result = Field()
    # No frozen, no selector → json_schema_extra is None or empty
    if result.json_schema_extra is not None:
        assert isinstance(result.json_schema_extra, dict)
        assert 'yosoi_frozen' not in result.json_schema_extra
        assert 'yosoi_selector' not in result.json_schema_extra


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


def test_field_frozen_and_selector_together():
    result = Field(frozen=True, selector='p.class')
    extra = result.json_schema_extra
    assert isinstance(extra, dict)
    assert extra['yosoi_frozen'] is True
    assert extra['yosoi_selector'] == 'p.class'


def test_field_passes_kwargs_to_pydantic_field():
    result = Field(description='A test field')
    assert result.description == 'A test field'


def test_field_with_existing_json_schema_extra():
    result = Field(json_schema_extra={'custom_key': 'custom_val'}, frozen=True)
    extra = result.json_schema_extra
    assert isinstance(extra, dict)
    assert extra['custom_key'] == 'custom_val'
    assert extra['yosoi_frozen'] is True


def test_field_frozen_false_not_stored():
    """frozen=False means the key should NOT be in extra."""
    result = Field(frozen=False)
    extra = result.json_schema_extra
    # frozen=False → should not add yosoi_frozen key
    if extra is not None and isinstance(extra, dict):
        assert extra.get('yosoi_frozen') is not True


def test_field_selector_none_not_stored():
    """selector=None means yosoi_selector should NOT be in extra."""
    result = Field(selector=None)
    extra = result.json_schema_extra
    if extra is not None and isinstance(extra, dict):
        assert 'yosoi_selector' not in extra


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


def test_field_no_frozen_no_selector_extra_is_none():
    """With no yosoi args, json_schema_extra should be None."""
    result = Field()
    assert result.json_schema_extra is None


def test_field_existing_json_schema_extra_preserved_exactly():
    """Existing json_schema_extra keys must not be overwritten."""
    result = Field(json_schema_extra={'my_custom': 42}, frozen=True)
    extra = result.json_schema_extra
    assert isinstance(extra, dict)
    assert extra['my_custom'] == 42
    assert extra['yosoi_frozen'] is True


# ---------------------------------------------------------------------------
# js() field factory
# ---------------------------------------------------------------------------


def test_js_with_script_returns_field_info():
    """js(script=...) returns a FieldInfo with yosoi_action metadata."""
    result = js(script='document.title')
    assert isinstance(result, FieldInfo)
    extra = result.json_schema_extra
    assert isinstance(extra, dict)
    assert extra['yosoi_action']['type'] == 'js'
    assert extra['yosoi_action']['script'] == 'document.title'


def test_js_no_script_no_description_raises():
    """js() without script or description raises ValueError (line 45)."""
    with pytest.raises(ValueError, match='requires either script='):
        js()


def test_js_description_propagated_to_pydantic_field():
    """js(description=...) stores description in pydantic field kwargs (line 54)."""
    result = js(description='Detect competitor widgets')
    assert isinstance(result, FieldInfo)
    assert result.description == 'Detect competitor widgets'


def test_js_with_description_only_is_discovery_driven():
    """js(description=...) without script enables discovery mode."""
    result = js(description='Detect competitor widgets')
    extra = result.json_schema_extra
    assert isinstance(extra, dict)
    assert extra['yosoi_action']['script'] is None
    assert extra['yosoi_action']['description'] == 'Detect competitor widgets'
