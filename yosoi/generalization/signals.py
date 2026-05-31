"""The reuse-signal contract — the durable interface across skill, MCP, detector.

The recommender does not return a bare boolean. It returns a versioned
:class:`ReuseSignalPanel`: each individual signal carries its own value,
threshold, local verdict, and a human-readable rationale, so the **threshold
travels with the value** and no downstream consumer has to hardcode its own
cutoff (the failure mode that makes signals drift between consumers).

This panel is the seam shared by every reader of the system — a human, an LLM
driver via a skill, an MCP tool, or (eventually) an autonomous detector. Keep it
stable; bump :data:`SCHEMA_VERSION` on any breaking change.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class Verdict(str, Enum):
    """A three-way reuse verdict (fail-closed: ABSTAIN never means allow).

    Attributes:
        ALLOW: Reuse is judged safe for this page.
        REFUSE: Reuse is judged unsafe; re-discover instead.
        ABSTAIN: Signals are inconclusive; escalate (to a driver / LLM judge).
    """

    ALLOW = 'allow'
    REFUSE = 'refuse'
    ABSTAIN = 'abstain'


class SignalReading(BaseModel):
    """One named signal with its value, threshold, local verdict, and reason.

    Attributes:
        name: Stable signal identifier (e.g. ``tag_cosine``, ``route_template``).
        value: The measured value, rendered as a string so heterogeneous signals
            (floats, booleans, template strings) share one schema.
        threshold: The cutoff/expectation the value was judged against, or None
            for boolean/categorical signals that carry their own logic.
        verdict: This signal's local contribution (ALLOW / REFUSE / ABSTAIN).
        rationale: One-line human-readable explanation of the verdict.
    """

    name: str
    value: str
    threshold: str | None = None
    verdict: Verdict
    rationale: str


class ReuseSignalPanel(BaseModel):
    """The full set of reuse signals plus the combined recommendation.

    Attributes:
        schema_version: Contract version; consumers should check before parsing.
        seed_url: URL the recipe was discovered on.
        replay_url: Candidate reuse URL.
        seed_route: Canonical route template of ``seed_url``.
        replay_route: Canonical route template of ``replay_url``.
        same_domain: Whether seed and replay share a host.
        readings: The individual signal readings that drove the recommendation.
        recommendation: The combined fail-closed verdict.
        rationale: One-line explanation of the combined recommendation.
    """

    schema_version: int = SCHEMA_VERSION
    seed_url: str
    replay_url: str
    seed_route: str
    replay_route: str
    same_domain: bool
    readings: list[SignalReading] = Field(default_factory=list)
    recommendation: Verdict
    rationale: str

    def reading(self, name: str) -> SignalReading | None:
        """Return the reading with the given name, or None if absent.

        Args:
            name: Signal identifier to look up.

        Returns:
            The matching :class:`SignalReading`, or None.
        """
        return next((r for r in self.readings if r.name == name), None)
