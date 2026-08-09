"""Deterministic, offline checks for the action candidate register."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.boss_fights.actions.manifest import (
    CASES,
    ActionCase,
    EvidenceModality,
    Freshness,
    InputMechanism,
    Lane,
    canonical_manifest_json,
)
from yosoi.actions.models import ActionKind


def test_manifest_serialization_is_deterministic() -> None:
    assert canonical_manifest_json() == canonical_manifest_json()
    assert [case.id for case in CASES] == ['A0', 'A1', 'A2', 'A3', 'A4', 'A5']


def test_first_slice_coverage_and_todomvc_deferred() -> None:
    assert {case.id for case in CASES[:5]} == {'A0', 'A1', 'A2', 'A3', 'A4'}
    todomvc = CASES[-1]
    assert todomvc.id == 'A5'
    assert todomvc.deferred
    assert todomvc.input_mechanism is InputMechanism.KEYBOARD
    assert 'deferred' in todomvc.unsupported_behavior


def test_input_mechanism_is_not_action_kind() -> None:
    assert CASES[0].action_kind is ActionKind.NAVIGATE
    assert CASES[0].input_mechanism is InputMechanism.HTML_NAVIGATION
    assert CASES[1].action_kind is ActionKind.CLICK
    assert CASES[1].required_modalities == (EvidenceModality.RENDERED_DOM, EvidenceModality.AX_TREE)


def test_research_backed_targets_and_modalities_are_exact() -> None:
    by_id = {case.id: case for case in CASES}
    assert by_id['A1'].target_url is not None
    assert by_id['A1'].target_url.endswith('/tabs-automatic/')
    assert by_id['A2'].target_url == 'http://www.uitestingplayground.com/hiddenlayers'
    assert EvidenceModality.GEOMETRY in by_id['A2'].required_modalities
    assert by_id['A3'].target_url == 'http://www.uitestingplayground.com/ajax'
    assert EvidenceModality.NETWORK in by_id['A3'].required_modalities
    assert by_id['A5'].target_url == 'https://todomvc.com/examples/react/dist/'


def test_candidates_do_not_claim_deterministic_fixtures_or_ci() -> None:
    assert all(case.lane in {Lane.CANDIDATE, Lane.LIVE_SMOKE} for case in CASES)
    assert all(case.freshness is Freshness.UNPINNED and not case.ci_gate and case.fixture is None for case in CASES)


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('auth_required', True),
        ('required_modalities', ()),
        ('postconditions', ()),
        ('target_url', 'https://example.test/?token=secret'),
        ('effect_class', 3),
    ],
)
def test_validation_rejects_unsafe_or_incomplete_metadata(field: str, value: object) -> None:
    payload = CASES[0].model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        ActionCase.model_validate(payload)


def test_validation_rejects_false_pinned_and_public_ci_claims() -> None:
    pinned = CASES[0].model_dump()
    pinned['freshness'] = Freshness.PINNED
    with pytest.raises(ValidationError):
        ActionCase.model_validate(pinned)
    public_gate = CASES[0].model_dump()
    public_gate['ci_gate'] = True
    with pytest.raises(ValidationError):
        ActionCase.model_validate(public_gate)


def test_validation_rejects_empty_postcondition_text() -> None:
    payload = CASES[0].model_dump()
    payload['postconditions'] = ('   ',)
    with pytest.raises(ValidationError):
        ActionCase.model_validate(payload)
