"""Tests for Url type coercion."""

import pytest
from pydantic import ValidationError

import yosoi as ys
from yosoi.models.contract import Contract


def test_url_strips_whitespace():
    class C(Contract):
        url: str = ys.Url()

    assert C.model_validate({'url': '  https://example.com  '}).url == 'https://example.com'


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
