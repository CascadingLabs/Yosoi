"""Tests for BodyText type coercion."""

import yosoi as ys
from yosoi.models.contract import Contract


def test_body_text_strips_whitespace():
    class C(Contract):
        body: str = ys.BodyText()

    assert C.model_validate({'body': '  Some text.  '}).body == 'Some text.'


def test_body_text_strips_tabs_and_newlines():
    class C(Contract):
        body: str = ys.BodyText()

    assert C.model_validate({'body': '\n\tParagraph content.\n'}).body == 'Paragraph content.'
