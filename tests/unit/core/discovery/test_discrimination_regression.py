"""Regression matrix for the discrimination gate over realistic SERP fixtures.

Locks the gate verdict for a battery of high-signal scenarios (the lucky-pass generic
selector, N-way disjoint regions, heterogeneous contracts, multi-field partial overlap,
the shared-coarse-class trap, a different engine). A regression that weakens region
discrimination flips one of these and fails loudly.
"""

from __future__ import annotations

import pytest

from tests.unit.core.discovery.serp_fixtures import SCENARIOS
from yosoi.core.discovery.discrimination import evaluate_discrimination


@pytest.mark.parametrize('scenario', SCENARIOS, ids=lambda s: s.name)
def test_gate_verdict_matches_expected(scenario) -> None:
    report = evaluate_discrimination(scenario.html, scenario.maps)
    assert report.accepted is scenario.expected_accepted, (
        f'{scenario.name}: expected accepted={scenario.expected_accepted} '
        f'but gate said {report.accepted} — {report.reason}\n  note: {scenario.note}'
    )


@pytest.mark.parametrize('scenario', SCENARIOS, ids=lambda s: s.name)
def test_rejected_scenarios_explain_why(scenario) -> None:
    # Every REJECT must carry a non-empty, actionable reason (overlap, empty, or count).
    report = evaluate_discrimination(scenario.html, scenario.maps)
    if not report.accepted:
        assert report.reason
        assert report.overlaps or report.empty or len(scenario.maps) < 2


def test_scenarios_cover_both_verdicts() -> None:
    verdicts = {s.expected_accepted for s in SCENARIOS}
    assert verdicts == {True, False}, 'regression matrix must exercise both ACCEPT and REJECT'
