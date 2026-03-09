"""Tests for Author type coercion."""

import yosoi as ys
from yosoi.models.contract import Contract


def test_author_strips_whitespace():
    class C(Contract):
        author: str = ys.Author()

    assert C.model_validate({'author': '\tJane Austen\n'}).author == 'Jane Austen'


def test_author_strips_leading_trailing_spaces():
    class C(Contract):
        author: str = ys.Author()

    assert C.model_validate({'author': '   John Smith   '}).author == 'John Smith'
