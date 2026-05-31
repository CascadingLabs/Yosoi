"""Tests for the trust lattice and decision records."""

from datetime import datetime, timezone

import pytest

from yosoi.generalization.fingerprint import PageObservation
from yosoi.generalization.recommend import recommend
from yosoi.generalization.signals import Verdict
from yosoi.generalization.trust import Outcome, Trust, build_decision, initial_trust

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

SEED = PageObservation(url='https://qscrape.dev/', rows=10, tag_hist={'div': 54, 'a': 43, 'span': 69})
SIBLING = PageObservation(url='https://qscrape.dev/page/2/', rows=10, tag_hist={'div': 54, 'a': 42, 'span': 69})
DETAIL = PageObservation(url='https://qscrape.dev/author/x', rows=0, tag_hist={'div': 5, 'p': 2})


def test_initial_trust_mapping() -> None:
    """ALLOW/ABSTAIN start QUARANTINED; REFUSE starts REJECTED."""
    assert initial_trust(Verdict.ALLOW) is Trust.QUARANTINED
    assert initial_trust(Verdict.ABSTAIN) is Trust.QUARANTINED
    assert initial_trust(Verdict.REFUSE) is Trust.REJECTED


def test_allow_decision_is_quarantined_not_verified() -> None:
    """An ALLOW is never auto-promoted to VERIFIED without adjudication."""
    panel = recommend(SEED, SIBLING)
    decision = build_decision(panel, decided_at=_NOW, driver='test')
    assert panel.recommendation is Verdict.ALLOW
    assert decision.trust is Trust.QUARANTINED
    assert decision.outcome is Outcome.PENDING
    assert decision.override_flag is False


def test_driver_may_downgrade_allow_to_refuse() -> None:
    """A driver can override an ALLOW recommendation down to REFUSE."""
    panel = recommend(SEED, SIBLING)
    decision = build_decision(panel, decided_at=_NOW, driver='test', driver_verdict=Verdict.REFUSE)
    assert decision.driver_verdict is Verdict.REFUSE
    assert decision.override_flag is True
    assert decision.trust is Trust.REJECTED


def test_driver_may_not_upgrade_refuse_to_allow() -> None:
    """A driver cannot upgrade a REFUSE/ABSTAIN recommendation to ALLOW."""
    panel = recommend(SEED, DETAIL)
    assert panel.recommendation is Verdict.REFUSE
    with pytest.raises(ValueError, match='cannot upgrade'):
        build_decision(panel, decided_at=_NOW, driver='test', driver_verdict=Verdict.ALLOW)


def test_promote_confirms_quarantined_to_verified() -> None:
    """A confirmed outcome promotes QUARANTINED -> VERIFIED."""
    decision = build_decision(recommend(SEED, SIBLING), decided_at=_NOW, driver='test')
    promoted = decision.promote(confirmed=True)
    assert promoted.trust is Trust.VERIFIED
    assert promoted.outcome is Outcome.CONFIRMED


def test_promote_refutes_quarantined_to_rejected() -> None:
    """A refuted outcome promotes QUARANTINED -> REJECTED (a caught leak)."""
    decision = build_decision(recommend(SEED, SIBLING), decided_at=_NOW, driver='test')
    promoted = decision.promote(confirmed=False)
    assert promoted.trust is Trust.REJECTED
    assert promoted.outcome is Outcome.REFUTED


def test_promote_is_noop_on_terminal_state() -> None:
    """Promoting an already-REJECTED decision leaves it unchanged."""
    decision = build_decision(recommend(SEED, DETAIL), decided_at=_NOW, driver='test')
    assert decision.trust is Trust.REJECTED
    assert decision.promote(confirmed=True) == decision
