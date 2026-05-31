"""Provenance & quarantine for reuse decisions: use it, but mark it.

The user's refinement: data extracted via an ensemble ALLOW that the LLM judge
has NOT yet adjudicated is *usable* but must be **marked** and **QUARANTINED**
until the batch judge (or a deterministic content invariant) confirms it. This is
the repo's fail-fast ethos applied to data integrity: never silently emit
unverified data — emit it tagged, in quarantine, with a clear path to promotion.

Status lattice (monotonic; data can only move toward more-trusted or rejected):

    QUARANTINED ──(batch judge / invariant says ok)──> VERIFIED
         │
         └────────(batch judge / invariant says wrong)──> REJECTED

A reuse decision therefore carries a Provenance, not just a bool:
  - VERIFIED   : a deterministic REFUSE/ALLOW rule fired, or the batch judge ruled.
  - QUARANTINED: the ensemble ALLOWED on cheap signals alone; downstream may use it
                 IF it tolerates quarantine, but it is flagged and queued for judging.
  - REJECTED   : a refuse fired -> the reuse is blocked, no data emitted.

This makes "unverified but useful" a first-class, typed state instead of a silent
leak. Mirrors DownloadRecord's quarantine-dir pattern (CAS-105): produce into a
quarantine, scan/judge, then promote.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from detector import Verdict
from ensemble import EnsembleResult


class Trust(str, Enum):
    """How much we trust a reuse decision's output, right now."""

    VERIFIED = 'verified'  # deterministic rule or adjudicated by judge/invariant
    QUARANTINED = 'quarantined'  # ensemble-allowed on cheap signals; awaiting judge
    REJECTED = 'rejected'  # a refuse fired; reuse blocked


# rules whose ALLOW we trust deterministically without a judge round-trip
_VERIFIED_ALLOW_RULES = frozenset({'simhash_rescue'})
# everything else that ALLOWs (e.g. ensemble_allow on cheap-signal agreement) is
# usable-but-quarantined until the batch judge confirms the signature once.


@dataclass(frozen=True)
class Provenance:
    """A reuse verdict + its trust state + why + the batch signature it queues under."""

    trust: Trust
    verdict: Verdict
    rule: str
    reason: str
    signature: str | None  # set when QUARANTINED -> the dedup key for batch judging


def classify(res: EnsembleResult, signature: str) -> Provenance:
    """Map an ensemble result onto the trust lattice."""
    if res.verdict is Verdict.REFUSE:
        return Provenance(Trust.REJECTED, res.verdict, res.rule, res.reason, None)
    if res.verdict is Verdict.ABSTAIN:
        # not even ensemble-confident -> nothing emitted yet, queued for judge
        return Provenance(Trust.QUARANTINED, res.verdict, res.rule, res.reason, signature)
    # ALLOW: deterministic-allow rules are verified; cheap-signal allows quarantine
    if res.rule in _VERIFIED_ALLOW_RULES:
        return Provenance(Trust.VERIFIED, res.verdict, res.rule, res.reason, None)
    return Provenance(Trust.QUARANTINED, res.verdict, res.rule, res.reason, signature)


def promote(prov: Provenance, judged_allow: bool) -> Provenance:
    """Apply a batch-judge / content-invariant verdict to a quarantined decision."""
    if prov.trust is not Trust.QUARANTINED:
        return prov  # already terminal
    if judged_allow:
        return Provenance(Trust.VERIFIED, Verdict.ALLOW, f'judged:{prov.rule}', prov.reason, None)
    return Provenance(Trust.REJECTED, Verdict.REFUSE, f'judged:{prov.rule}', prov.reason, None)
