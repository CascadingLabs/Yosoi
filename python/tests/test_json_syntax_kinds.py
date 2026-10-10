"""JSON syntax tags remain typed at the public locator error boundary."""

import pytest
from pydantic import TypeAdapter

import yosoi as ys
from yosoi.errors import LocatorError, rust_error_details
from yosoi.locators import JsonQuerySyntaxError


@pytest.mark.parametrize(
    ("expression", "variant"),
    [("bad", "InvalidPointerSyntax"), ("/~2", "InvalidPointerEscape")],
)
def test_json_pointer_preserves_typed_syntax_tag(expression, variant):
    with pytest.raises(LocatorError) as caught:
        ys.json_pointer(expression)
    details = rust_error_details(caught.value)
    assert details is not None
    assert details.variant == "InvalidJsonQuery"
    observed = details.details["source"]["variant"]
    assert TypeAdapter(JsonQuerySyntaxError).validate_python(observed) == variant


@pytest.mark.parametrize(
    "variant",
    [
        "InvalidPointerSyntax",
        "InvalidPointerEscape",
        "InvalidPathSyntax",
        "UnsupportedPathFeature",
    ],
)
def test_all_public_json_syntax_tags_are_represented(variant):
    assert TypeAdapter(JsonQuerySyntaxError).validate_python(variant) == variant
