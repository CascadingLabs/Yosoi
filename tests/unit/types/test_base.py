"""Tests for YosoiType base class."""

from yosoi.types.base import YosoiType
from yosoi.types.registry import _registry


def test_subclass_with_type_name_auto_registers():
    class MyPhoneType(YosoiType):
        type_name = '_test_phone_xyz'

        @staticmethod
        def coerce(v, config, source_url=None):
            return str(v).upper()

    assert '_test_phone_xyz' in _registry
    assert _registry['_test_phone_xyz']('hello', {}) == 'HELLO'


def test_subclass_without_type_name_does_not_register():
    before = set(_registry.keys())

    class MyAnonymousType(YosoiType):
        @staticmethod
        def coerce(v, config, source_url=None):
            return str(v).lower()

    assert set(_registry.keys()) == before


def test_default_coerce_strips_whitespace():
    result = YosoiType.coerce('  hello world  ', {})
    assert result == 'hello world'


def test_default_coerce_none_returns_empty_string():
    result = YosoiType.coerce(None, {})
    assert result == ''
