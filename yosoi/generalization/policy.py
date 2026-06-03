"""Operator risk profiles — what a profile does with a reuse decision.

A *profile* turns a recommender verdict + reuse scope into a :class:`Disposition`:
whether the pipeline may **act** on the hint, the initial **trust** of any reused
output, and whether the decision is **enqueued for review**. Quarantine is the
resting state in every profile except ``experiment`` — promotion to VERIFIED is an
explicit, separate act (the review queue, or a judge).

Set by ``YOSOI_REUSE_PROFILE`` (default ``strict``):

* **strict** — air-gapped. Never act on ALLOW/ABSTAIN; record everything
  QUARANTINED and enqueue it for review. The hint changes no runtime behavior;
  correctness comes from the review queue, not from the hint acting.
* **balanced** — act on a confident same-domain / sub-page ALLOW (output is still
  quarantined, just usable); send cross-domain ALLOW and every ABSTAIN to the
  queue; honor REFUSE (skip the doomed replay).
* **experiment** — act on everything and auto-promote ALLOW to VERIFIED (no gate).

REFUSE is the safe action (declining to reuse) and is honored without review in
``balanced``/``experiment``; in ``strict`` even REFUSE does not change behavior —
it is only recorded — because strict acts on nothing.
"""

from __future__ import annotations

import os
from enum import Enum

from pydantic import BaseModel

from yosoi.generalization.scope import ReuseScope
from yosoi.generalization.signals import Verdict
from yosoi.generalization.trust import Trust

_ENV = 'YOSOI_REUSE_PROFILE'

# Same-host scopes a balanced profile will auto-act on for an ALLOW.
_BALANCED_AUTO: frozenset[ReuseScope] = frozenset({ReuseScope.SAME_DOMAIN, ReuseScope.SUB_PAGE})


class ReuseProfile(str, Enum):
    """Operator-selected risk tolerance for acting on reuse hints.

    Attributes:
        STRICT: Air-gapped; quarantine + enqueue everything, act on nothing.
        BALANCED: Act on confident same-host ALLOW; review the rest.
        EXPERIMENT: Act on everything; auto-promote ALLOW.
    """

    STRICT = 'strict'
    BALANCED = 'balanced'
    EXPERIMENT = 'experiment'


def active_profile() -> ReuseProfile:
    """Resolve the active profile from ``YOSOI_REUSE_PROFILE`` (default strict).

    Returns:
        The configured :class:`ReuseProfile`; ``STRICT`` for unset or unrecognized
        values (fail-closed to the most cautious profile).
    """
    raw = (os.getenv(_ENV) or 'strict').strip().lower()
    try:
        return ReuseProfile(raw)
    except ValueError:
        return ReuseProfile.STRICT


class Disposition(BaseModel):
    """What a profile decides to do with one reuse decision.

    Attributes:
        act: Whether the pipeline may honor the hint's behavioral effect (e.g.
            skip a doomed replay on REFUSE, or reuse on ALLOW).
        trust: Initial trust of any output produced under this decision.
        needs_review: Whether the decision is enqueued for human/judge review.
    """

    act: bool
    trust: Trust
    needs_review: bool


def disposition(verdict: Verdict, scope: ReuseScope, profile: ReuseProfile) -> Disposition:
    """Map (verdict, scope, profile) onto an action/trust/review disposition.

    Args:
        verdict: The recommender (or driver) verdict.
        scope: The reuse scope the decision spans.
        profile: The active operator risk profile.

    Returns:
        The :class:`Disposition` governing this decision.
    """
    if profile is ReuseProfile.EXPERIMENT:
        trust = {
            Verdict.ALLOW: Trust.VERIFIED,
            Verdict.REFUSE: Trust.REJECTED,
            Verdict.ABSTAIN: Trust.QUARANTINED,
        }[verdict]
        return Disposition(act=True, trust=trust, needs_review=False)

    if profile is ReuseProfile.STRICT:
        # Air-gapped: record + (for non-refusals) enqueue; never change behavior.
        if verdict is Verdict.REFUSE:
            return Disposition(act=False, trust=Trust.REJECTED, needs_review=False)
        return Disposition(act=False, trust=Trust.QUARANTINED, needs_review=True)

    # BALANCED
    if verdict is Verdict.REFUSE:
        return Disposition(act=True, trust=Trust.REJECTED, needs_review=False)
    if verdict is Verdict.ALLOW and scope in _BALANCED_AUTO:
        return Disposition(act=True, trust=Trust.QUARANTINED, needs_review=False)
    # Cross-domain ALLOW, or any ABSTAIN: usable only after review.
    return Disposition(act=False, trust=Trust.QUARANTINED, needs_review=True)
