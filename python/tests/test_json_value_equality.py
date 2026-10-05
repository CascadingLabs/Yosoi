"""JSON projection equality follows Rust value types and object semantics."""

import pytest
from pydantic import ValidationError

from yosoi.outcomes import JsonValueProjection


@pytest.mark.parametrize(
    ("left", "right", "equal"),
    [
        (True, 1, False),
        (False, 0, False),
        (1, 1.0, False),
        ({"a": True}, {"a": 1}, False),
        ([True, {"value": 2}], [1, {"value": 2}], False),
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}, True),
        ([1, 2], [2, 1], False),
        (None, None, True),
    ],
)
def test_json_projection_preserves_rust_equality(left, right, equal):
    first = JsonValueProjection(kind="json", value=left)
    second = JsonValueProjection(kind="json", value=right)
    assert (first == second) is equal
    assert (first != second) is (not equal)


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), {"nested": [float("nan")]}]
)
def test_nonfinite_json_values_are_not_silently_replaced_with_null(value):
    with pytest.raises(ValidationError):
        JsonValueProjection(kind="json", value=value)
