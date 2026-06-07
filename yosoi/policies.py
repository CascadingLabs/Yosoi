"""``ys.policies`` — pipeline-affecting configuration as one resolved, immutable value.

A :class:`Policy` collapses the decisions that change *how* the pipeline behaves (not *what* a
contract means) into a single frozen value object, **resolved once at the edge** and threaded
through the pure core — so the replay ``resolve()`` stays a deterministic function of its inputs and
never reads the environment deep in the stack (the CAS-119 purity contract).

This is the MVP slice of CAS-168. Today it subsumes the atom-read flag and the trust tier; new knobs
(reuse thresholds, the fingerprint signal-lane priority/backpressure) become new fields under the
same cascade — never a new ``os.environ`` read site or a new buried conditional.

Precedence (lowest → highest): ``defaults < env < session < contract < call-site``.
:meth:`Policy.cascade` merges partial overrides (only the fields each layer explicitly set) into
one effective Policy. (Phase 1 wires defaults+env; session/contract/call layers arrive in phase 2.)
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

TrustTier = Literal['strict', 'yellow']


class Trust(str, Enum):
    """Trust lattice for reuse output.

    ``QUARANTINED`` is the key middle state from the CAS-85 spike: output may be
    produced under an explicit ride/yellow policy, but it is not silently treated
    as verified until a later invariant/judge confirms it.
    """

    VERIFIED = 'verified'
    QUARANTINED = 'quarantined'
    REJECTED = 'rejected'


class Outcome(str, Enum):
    """Ground-truth outcome that resolves a quarantined reuse decision."""

    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    REFUTED = 'refuted'


# Strict serves ONLY these provenance tiers — a POSITIVE allow-list (deny-by-default). A new tier in
# storage.atoms.SOURCE_TRUST is refused under strict until it is consciously promoted here, so reuse
# can never silently fail OPEN as P5 adds tiers. The partition (TRUSTED | QUARANTINED == all known
# sources, disjoint) is asserted by test, forcing a deliberate classification when a tier is added.
TRUSTED_SOURCES = frozenset({'verified', 'manual', 'llm'})
QUARANTINED_SOURCES = frozenset({'fingerprint'})  # the fingerprint-generalized reuse — risky, strict-denied

_TRUTHY = frozenset({'1', 'true', 'yes', 'on'})
_YELLOW_ALIASES = frozenset({'yellow', 'ride'})  # "let it ride"; ANYTHING else (incl. unset) → strict


def _classify_tier(raw: str) -> TrustTier:
    """Normalize a raw trust-mode string to a tier — the ONE place trust aliases are decided."""
    return 'yellow' if raw.strip().lower() in _YELLOW_ALIASES else 'strict'


class Policy(BaseModel):
    """Effective pipeline policy. Frozen — share freely across threads/sessions without copying.

    Attributes:
        atom_reads: Serve a contract from the field-atom index on a legacy-cache miss. Default-deny.
        trust_tier: ``strict`` serves only :data:`TRUSTED_SOURCES` (quarantines the risky
            fingerprint-generalized reuse); ``yellow`` ("let it ride") serves every tier.
    """

    model_config = ConfigDict(frozen=True)

    atom_reads: bool = False
    trust_tier: TrustTier = 'strict'

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Policy:
        """The ``env`` layer of the cascade: read the (legacy) ``YOSOI_*`` switches.

        Only sets a field when its env var is actually PRESENT, so an unset var contributes nothing
        to a :meth:`cascade` — an absent ``YOSOI_ATOM_TRUST`` can never reset a lower layer's tier.
        """
        src = os.environ if env is None else env
        kwargs: dict[str, Any] = {}
        if 'YOSOI_ATOM_READS' in src:
            kwargs['atom_reads'] = src['YOSOI_ATOM_READS'].strip().lower() in _TRUTHY
        if 'YOSOI_ATOM_TRUST' in src:
            kwargs['trust_tier'] = _classify_tier(src['YOSOI_ATOM_TRUST'])
        return cls(**kwargs)

    @classmethod
    def cascade(cls, *layers: Policy | None) -> Policy:
        """Merge cascade layers (lowest precedence first) into one effective Policy.

        Precedence ``defaults < env < session < contract < call-site``, e.g.
        ``Policy.cascade(Policy.from_env(), session_policy, contract_policy, call_policy)``.
        Each layer contributes only the fields it explicitly set (``exclude_unset``), so a partial
        override like ``Policy(trust_tier='yellow')`` changes only the tier; ``None`` layers are
        skipped so callers can pass optional overrides positionally.
        """
        merged: dict[str, Any] = {}
        for layer in layers:
            if layer is not None:
                merged.update(layer.model_dump(exclude_unset=True))
        return cls(**merged)

    @property
    def allowed_sources(self) -> frozenset[str] | None:
        """Provenance tiers eligible to serve under this policy; ``None`` = all (yellow).

        Strict returns the positive :data:`TRUSTED_SOURCES` allow-list (default-deny the risky);
        yellow returns ``None`` (serve every tier, including fingerprint-generalized reuse).
        """
        return None if self.trust_tier == 'yellow' else TRUSTED_SOURCES

    def source_trust(self, source: str) -> Trust:
        """Classify a provenance source in the trust lattice, independent of serving policy.

        Known verified/manual/LLM sources are verified. Known fingerprint-generalized
        sources are quarantined. Unknown sources are rejected so newly-added tiers
        fail closed until explicitly classified.
        """
        if source in TRUSTED_SOURCES:
            return Trust.VERIFIED
        if source in QUARANTINED_SOURCES:
            return Trust.QUARANTINED
        return Trust.REJECTED

    def allows_source(self, source: str) -> bool:
        """Whether this policy may serve a source at all."""
        trust = self.source_trust(source)
        if trust is Trust.REJECTED:
            return False
        if trust is Trust.QUARANTINED:
            return self.trust_tier == 'yellow'
        return True

    def output_trust(self, source: str) -> Trust:
        """Trust state of output produced from ``source`` under this policy."""
        trust = self.source_trust(source)
        if trust is Trust.QUARANTINED and not self.allows_source(source):
            return Trust.REJECTED
        return trust


def promote_trust(trust: Trust, *, confirmed: bool) -> tuple[Trust, Outcome]:
    """Resolve a quarantined trust state with a later ground-truth signal.

    Terminal states remain terminal. A quarantined result promotes to verified
    when confirmed, or rejected when refuted.
    """
    if trust is Trust.QUARANTINED:
        return (
            Trust.VERIFIED if confirmed else Trust.REJECTED,
            Outcome.CONFIRMED if confirmed else Outcome.REFUTED,
        )
    return trust, Outcome.PENDING
