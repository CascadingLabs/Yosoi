"""Tests for ``validator_mcp`` rule parsing and in-process check-value feedback."""

from __future__ import annotations

import json

from yosoi.integrations.validator_mcp import FIELD_RULES_ENV, _check_value_feedback, _load_rules, field_rules_env
from yosoi.types.registry import KIND_NUMERIC, SemanticRule


def test_load_rules_returns_empty_for_invalid_json(monkeypatch):
    monkeypatch.setenv(FIELD_RULES_ENV, '{"bad": [1,2,3]')
    rules = _load_rules()
    assert rules == {}


def test_load_rules_skips_invalid_specs(monkeypatch):
    raw = json.dumps(
        {
            'ok': {'kind': KIND_NUMERIC, 'max_chars': 4},
            'bad_kind_missing': {'max_chars': 4},
            'bad_shape': ['unexpected'],
        }
    )
    monkeypatch.setenv(FIELD_RULES_ENV, raw)
    rules = _load_rules()
    assert 'ok' in rules
    assert 'bad_kind_missing' not in rules
    assert 'bad_shape' not in rules
    assert isinstance(rules['ok'], SemanticRule)


def test_field_rules_env_and_check_feedback_round_trip(monkeypatch):
    payload = field_rules_env({'score': SemanticRule(kind=KIND_NUMERIC, max_chars=4)})
    monkeypatch.setenv(FIELD_RULES_ENV, payload)
    rules = _load_rules()

    assert _check_value_feedback('score', '123', rules) == 'ok'
    assert _check_value_feedback('score', 'abc', rules) != 'ok'
    assert _check_value_feedback('missing', 'value', rules) == 'ok'
