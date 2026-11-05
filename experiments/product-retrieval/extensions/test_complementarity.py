"""Proposal fusion must remain bounded, deterministic and independent of labels."""

import pytest
from complementarity import policies, pool


def test_duplicate_coordinates_do_not_spend_budget_twice():
    rankings = {"a": ["same", "second", "fourth"], "b": ["same", "third"]}
    assert pool(rankings, ("a", "b"), 3) == ["same", "second", "third"]
    assert pool(rankings, ("b", "a"), 3) == ["same", "third", "second"]
    assert pool(rankings, ("a", "b"), 0) == []


def test_empty_channels_and_exhausted_lists_do_not_fabricate_proposals():
    assert pool({"a": [], "b": ["only"]}, ("a", "b"), 10) == ["only"]
    assert pool({}, (), 2) == []
    with pytest.raises(ValueError):
        pool({"a": []}, ("a", "a"), 2)


def test_policy_inventory_retains_all_orders_without_gold_selection():
    choices = policies()
    assert len(choices) == 25
    assert len(set(choices)) == len(choices)
