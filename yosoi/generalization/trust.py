r"""Trust lattice and decision records for reuse outcomes.

A reuse decision is never "use it / don't." It moves through a monotonic trust
lattice so unverified data is *usable but marked*, never silently trusted:

    QUARANTINED --(content invariant / judge: ok)--> VERIFIED
         \------(content invariant / judge: wrong)--> REJECTED

A recommendation maps onto an initial :class:`Trust` state; a later ground-truth
signal (a deterministic content invariant, or a batched LLM judge) promotes a
QUARANTINED decision to VERIFIED or REJECTED. Every decision is captured as a
:class:`DecisionRecord` whose ``override_flag`` (driver disagreed with the
recommendation) and ``outcome`` write-back turn each reuse into a free, verified
training row for the eventual autonomous detector.
"""

from __future__ import annotations

from enum import Enum

from pydantic import AwareDatetime, BaseModel

from yosoi.generalization.signals import ReuseSignalPanel, Verdict


class Trust(str, Enum):
    """How much a reuse decision's output may be trusted, right now.

    Attributes:
        VERIFIED: Confirmed correct by a deterministic invariant or a judge.
        QUARANTINED: Usable but unconfirmed; flagged and awaiting adjudication.
        REJECTED: Reuse blocked / output discarded.
    """

    VERIFIED = 'verified'
    QUARANTINED = 'quarantined'
    REJECTED = 'rejected'


class Outcome(str, Enum):
    """Ground-truth outcome of a reuse, back-filled after the fact.

    Attributes:
        PENDING: Not yet adjudicated.
        CONFIRMED: A later check confirmed the reuse produced correct data.
        REFUTED: A later check showed the reuse produced wrong data (a leak).
    """

    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    REFUTED = 'refuted'


def initial_trust(recommendation: Verdict) -> Trust:
    """Map a recommendation onto its initial trust state (fail-closed).

    Args:
        recommendation: The combined panel verdict.

    Returns:
        REJECTED for REFUSE; QUARANTINED for both ALLOW and ABSTAIN — an ALLOW is
        *usable but not yet verified*, never auto-promoted to VERIFIED without an
        adjudication step.
    """
    if recommendation is Verdict.REFUSE:
        return Trust.REJECTED
    return Trust.QUARANTINED


class DecisionRecord(BaseModel):
    """An auditable record of one reuse decision and its eventual outcome.

    The record embeds the full signal panel (snapshots rot if referenced), the
    driver's choice and whether it overrode the recommendation, the current trust
    state, and a back-filled ground-truth outcome. The triple of
    ``(panel, decision, outcome)`` is one labeled training example once the
    outcome is no longer PENDING.

    Attributes:
        panel: The full signal panel the decision was made from.
        decided_at: When the decision was recorded.
        driver: Who/what made the call (e.g. ``human:andrew``, ``claude``).
        driver_verdict: The verdict the driver actually chose.
        override_flag: True when the driver's verdict differs from the panel's
            recommendation — the single highest-value audit signal.
        driver_rationale: Optional free-text reason the driver gave (a source of
            candidate features the cheap signals do not yet capture).
        trust: Current trust state of any output produced under this decision.
        outcome: Ground-truth outcome, back-filled by an invariant or a judge.
    """

    panel: ReuseSignalPanel
    decided_at: AwareDatetime
    driver: str
    driver_verdict: Verdict
    override_flag: bool = False
    driver_rationale: str | None = None
    trust: Trust
    outcome: Outcome = Outcome.PENDING

    def promote(self, *, confirmed: bool) -> DecisionRecord:
        """Return a copy with the outcome back-filled and trust resolved.

        A QUARANTINED decision becomes VERIFIED (confirmed) or REJECTED
        (refuted). Terminal states are returned unchanged.

        Args:
            confirmed: True if a later check confirmed the reuse was correct.

        Returns:
            A new :class:`DecisionRecord` with ``outcome`` and ``trust`` updated.
        """
        if self.trust is not Trust.QUARANTINED:
            return self
        return self.model_copy(
            update={
                'outcome': Outcome.CONFIRMED if confirmed else Outcome.REFUTED,
                'trust': Trust.VERIFIED if confirmed else Trust.REJECTED,
            }
        )


def build_decision(
    panel: ReuseSignalPanel,
    *,
    decided_at: AwareDatetime,
    driver: str,
    driver_verdict: Verdict | None = None,
    driver_rationale: str | None = None,
) -> DecisionRecord:
    """Construct a decision record, defaulting the driver to the recommendation.

    The driver may DOWNGRADE trust (recommendation ALLOW -> driver REFUSE/ABSTAIN)
    but may NEVER upgrade it: a recommendation of REFUSE or ABSTAIN cannot be
    turned into a driver ALLOW. This is enforced here, in code, not in a prompt.

    Args:
        panel: The signal panel produced by the recommender.
        decided_at: Timestamp for the record.
        driver: Identifier of the deciding agent or human.
        driver_verdict: The driver's choice; defaults to the recommendation.
        driver_rationale: Optional free-text reason.

    Returns:
        A :class:`DecisionRecord` with ``override_flag`` and ``trust`` set.

    Raises:
        ValueError: If the driver tries to upgrade a REFUSE/ABSTAIN to ALLOW.
    """
    chosen = driver_verdict if driver_verdict is not None else panel.recommendation
    if chosen is Verdict.ALLOW and panel.recommendation is not Verdict.ALLOW:
        raise ValueError(f'driver cannot upgrade {panel.recommendation.value!r} to ALLOW; trust may only be downgraded')
    return DecisionRecord(
        panel=panel,
        decided_at=decided_at,
        driver=driver,
        driver_verdict=chosen,
        override_flag=chosen is not panel.recommendation,
        driver_rationale=driver_rationale,
        trust=initial_trust(chosen),
    )
