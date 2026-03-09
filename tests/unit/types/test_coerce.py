"""Tests for the coercion dispatch function."""

from yosoi.types.coerce import dispatch
from yosoi.types.registry import register_coercion


def test_unknown_type_returns_value_unchanged():
    result = dispatch('_totally_unknown_type_xyz', 'hello', {})
    assert result == 'hello'


def test_none_value_returns_none():
    result = dispatch('price', None, {})
    assert result is None


def test_registered_type_dispatches_to_coercer():
    @register_coercion('_test_dispatch_xyz', description='test')
    def TestDispatchXyz(v, config, source_url=None):
        return str(v).upper()

    result = dispatch('_test_dispatch_xyz', 'hello', {})
    assert result == 'HELLO'


def test_source_url_forwarded_to_coercer():
    received_url = []

    @register_coercion('_test_url_fwd_xyz', description='test')
    def TestUrlFwdXyz(v, config, source_url=None):
        received_url.append(source_url)
        return v

    dispatch('_test_url_fwd_xyz', 'value', {}, source_url='https://example.com')
    assert received_url == ['https://example.com']
