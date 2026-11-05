"""Source proximity is distinct from value correctness and respects ancestry."""

from locality import distance


def test_sibling_label_and_value_are_two_hops_apart():
    parents = {"label": "row", "value": "row", "row": "product"}
    assert distance("label", "value", parents) == 2
    assert distance("value", "value", parents) == 0


def test_separate_trees_have_no_distance():
    assert distance("a", "b", {}) is None


def test_source_cycles_are_rejected():
    import pytest

    with pytest.raises(ValueError):
        distance("a", "b", {"a": "a"})
