"""Tests for reuse risk profiles and their dispositions."""

import pytest

from yosoi.generalization.policy import ReuseProfile, active_profile, disposition
from yosoi.generalization.scope import ReuseScope
from yosoi.generalization.signals import Verdict
from yosoi.generalization.trust import Trust

pytestmark = pytest.mark.unit


def test_active_profile_defaults_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env resolves to the most cautious profile."""
    monkeypatch.delenv('YOSOI_REUSE_PROFILE', raising=False)
    assert active_profile() is ReuseProfile.STRICT


def test_active_profile_unknown_value_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognized value fails closed to strict."""
    monkeypatch.setenv('YOSOI_REUSE_PROFILE', 'banana')
    assert active_profile() is ReuseProfile.STRICT


def test_active_profile_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A recognized value is honored (case-insensitive)."""
    monkeypatch.setenv('YOSOI_REUSE_PROFILE', 'Balanced')
    assert active_profile() is ReuseProfile.BALANCED


def test_strict_never_acts_and_quarantines_allow() -> None:
    """Strict is a pure observer: ALLOW -> quarantine + enqueue, no act."""
    d = disposition(Verdict.ALLOW, ReuseScope.SAME_DOMAIN, ReuseProfile.STRICT)
    assert (d.act, d.trust, d.needs_review) == (False, Trust.QUARANTINED, True)


def test_strict_refuse_is_rejected_without_review_or_act() -> None:
    """Strict records a REFUSE as REJECTED but does not act on it."""
    d = disposition(Verdict.REFUSE, ReuseScope.SUB_PAGE, ReuseProfile.STRICT)
    assert (d.act, d.trust, d.needs_review) == (False, Trust.REJECTED, False)


def test_balanced_acts_on_same_host_allow() -> None:
    """Balanced acts on a confident same-domain/sub-page ALLOW (still quarantined)."""
    d = disposition(Verdict.ALLOW, ReuseScope.SUB_PAGE, ReuseProfile.BALANCED)
    assert (d.act, d.trust, d.needs_review) == (True, Trust.QUARANTINED, False)


def test_balanced_reviews_cross_domain_allow() -> None:
    """Balanced sends a cross-domain ALLOW to the review queue instead of acting."""
    d = disposition(Verdict.ALLOW, ReuseScope.CROSS_DOMAIN, ReuseProfile.BALANCED)
    assert (d.act, d.needs_review) == (False, True)


def test_balanced_reviews_abstain() -> None:
    """Balanced sends every ABSTAIN to the queue."""
    d = disposition(Verdict.ABSTAIN, ReuseScope.SAME_DOMAIN, ReuseProfile.BALANCED)
    assert (d.act, d.needs_review) == (False, True)


def test_balanced_honors_refuse() -> None:
    """Balanced acts on REFUSE (skip the doomed replay)."""
    d = disposition(Verdict.REFUSE, ReuseScope.SAME_DOMAIN, ReuseProfile.BALANCED)
    assert (d.act, d.trust) == (True, Trust.REJECTED)


def test_experiment_auto_promotes_allow() -> None:
    """Experiment acts on everything and auto-promotes ALLOW to VERIFIED."""
    d = disposition(Verdict.ALLOW, ReuseScope.CROSS_DOMAIN, ReuseProfile.EXPERIMENT)
    assert (d.act, d.trust, d.needs_review) == (True, Trust.VERIFIED, False)
