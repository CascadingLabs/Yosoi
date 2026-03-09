"""Tests for Title type coercion."""

import yosoi as ys
from yosoi.models.contract import Contract


def test_title_strips_whitespace():
    class C(Contract):
        title: str = ys.Title()

    assert C.model_validate({'title': '  Hello World  '}).title == 'Hello World'


def test_title_strips_tabs_and_newlines():
    class C(Contract):
        title: str = ys.Title()

    assert C.model_validate({'title': '\tMy Title\n'}).title == 'My Title'
