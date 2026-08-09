"""Closed model-facing contracts for indexed action discovery."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from yosoi.qa.discovery import ClickDecision, DiscoveryDecision, NavigateDecision

_DECISION = TypeAdapter(DiscoveryDecision)
_POSTCONDITION = {
    'assertion_id': 'next-heading',
    'semantic_role': 'heading',
    'accessible_name': 'Next page',
}


@pytest.mark.parametrize('field', ['selector', 'javascript', 'input', 'payload', 'browser_id'])
def test_model_decisions_reject_unsafe_extra_channels(field: str) -> None:
    payload = {
        'decision': 'navigate',
        'url': 'https://example.test/next',
        field: 'unsafe',
    }

    with pytest.raises(ValidationError):
        _DECISION.validate_python(payload)


@pytest.mark.parametrize('kind', ['scroll', 'back', 'forward', 'type', 'eval'])
def test_model_decisions_reject_unsupported_action_kinds(kind: str) -> None:
    with pytest.raises(ValidationError):
        _DECISION.validate_python({'decision': kind, 'expect': _POSTCONDITION})


def test_navigation_does_not_ask_the_model_to_guess_unseen_ax_labels() -> None:
    decision = NavigateDecision(url='https://example.test/next')
    assert decision.model_dump() == {'decision': 'navigate', 'url': 'https://example.test/next'}
    with pytest.raises(ValidationError):
        NavigateDecision.model_validate({'url': 'https://example.test/next', 'expect': _POSTCONDITION})


def test_click_requires_snapshot_ordinal_and_explicit_postcondition() -> None:
    with pytest.raises(ValidationError):
        ClickDecision.model_validate({'snapshot_id': 's0', 'ordinal': 1})
