"""Agent-facing reuse hints — advisory, not authoritative.

The recommender (:mod:`yosoi.generalization.recommend`) produces a full
:class:`~yosoi.generalization.signals.ReuseSignalPanel`. That panel is rich but
verbose; a discovery agent deciding whether to *try* reusing a cached recipe
wants a small, glanceable nudge, not a six-row table.

A :class:`ReuseHint` is that nudge. Crucially it is **advisory**: it suggests an
action the agent MAY take, and it states plainly that whatever the agent produces
is still semantically verified downstream (see
:mod:`yosoi.core.verification.semantic`). The hint is therefore allowed to be
wrong — a bad "reuse" suggestion is caught by verification and the agent
re-discovers. This is what lets the signal be a cheap cost optimization rather
than a correctness gate.

The hint never *decides*; it informs. The agent (or a human driver) owns the
action, and verification owns correctness.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from yosoi.generalization.fingerprint import PageObservation
from yosoi.generalization.recommend import recommend
from yosoi.generalization.signals import ReuseSignalPanel, Verdict


class SuggestedAction(str, Enum):
    """What the hint suggests the agent consider doing (never mandates).

    Attributes:
        TRY_REUSE: The cached recipe plausibly applies — try replaying it first;
            verification will confirm or reject.
        REDISCOVER: The page looks like a different class — discovery is the safe
            bet; reuse would likely waste a verification round.
        UNSURE: Signals are inconclusive — the agent's own judgement should lead.
    """

    TRY_REUSE = 'try_reuse'
    REDISCOVER = 'rediscover'
    UNSURE = 'unsure'


_ACTION_BY_VERDICT = {
    Verdict.ALLOW: SuggestedAction.TRY_REUSE,
    Verdict.REFUSE: SuggestedAction.REDISCOVER,
    Verdict.ABSTAIN: SuggestedAction.UNSURE,
}


class ReuseHint(BaseModel):
    """A compact, advisory reuse suggestion for a discovery agent.

    Attributes:
        suggested_action: What to consider — TRY_REUSE / REDISCOVER / UNSURE.
        confidence: A 0-1 readout of how strongly the cheap signals agree; a
            convenience for ranking, not a probability of correctness.
        headline: A one-line, human/agent-readable summary of the signals.
        advisory: Always True — a flag making it explicit at the call site that
            this does not gate anything; downstream semantic verification does.
        panel: The full underlying signal panel, for an agent that wants detail.
    """

    suggested_action: SuggestedAction
    confidence: float
    headline: str
    advisory: bool = True
    panel: ReuseSignalPanel

    def as_prompt_line(self) -> str:
        """Render the hint as a single line suitable for a discovery prompt.

        Returns:
            A terse, prefixed advisory line, e.g.
            ``[reuse-hint · advisory] TRY_REUSE (0.92): same route + structure``.
            The ``advisory`` prefix signals to the agent that it is free to
            ignore this and that correctness is verified downstream.
        """
        return f'[reuse-hint · advisory] {self.suggested_action.value.upper()} ({self.confidence:.2f}): {self.headline}'


def _confidence(panel: ReuseSignalPanel) -> float:
    """Fraction of readings that agree with the combined recommendation.

    A cheap agreement score in ``[0, 1]`` — how unanimous the signals were — used
    only for ranking/display, never as a correctness probability.
    """
    if not panel.readings:
        return 0.0
    agree = sum(1 for r in panel.readings if r.verdict is panel.recommendation)
    return agree / len(panel.readings)


def advise_reuse(seed: PageObservation, replay: PageObservation) -> ReuseHint:
    """Produce an advisory reuse hint for a (seed, replay) page pair.

    Wraps :func:`~yosoi.generalization.recommend.recommend` and reshapes its
    panel into a small, agent-facing :class:`ReuseHint`. The hint suggests an
    action but does not decide: whatever the agent does is semantically verified
    downstream, so the hint is free to be a cheap, fallible nudge.

    Args:
        seed: Observation of the page a recipe was discovered on.
        replay: Observation of the candidate reuse page.

    Returns:
        A :class:`ReuseHint` wrapping the full signal panel.
    """
    panel = recommend(seed, replay)
    return ReuseHint(
        suggested_action=_ACTION_BY_VERDICT[panel.recommendation],
        confidence=_confidence(panel),
        headline=panel.rationale,
        panel=panel,
    )
