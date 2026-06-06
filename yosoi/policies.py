"""``ys.policies`` — pipeline-affecting configuration as one resolved, immutable value.

A :class:`Policy` collapses the decisions that change *how* the pipeline behaves (not *what* a
contract means) into a single frozen value object, **resolved once at the edge** and threaded
through the pure core — so ``resolve()`` stays a deterministic function of its inputs and never
reads the environment deep in the stack (the CAS-119 purity contract).

This is the MVP slice of P6 (`docs/plans/ys-policies-p6.md`, CAS-168). Today it subsumes the
atom-read flag and the trust tier; new knobs (reuse thresholds, the fingerprint signal-lane
priority/backpressure) become new fields under the same cascade — never a new ``os.environ`` read
site or a new buried conditional.

Precedence (lowest → highest): ``defaults < env < session < contract < call-site``.
:meth:`Policy.resolve` merges partial overrides (only the fields each layer explicitly set) into
one effective Policy.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

TrustTier = Literal['strict', 'yellow']

# Provenance sources quarantined by the strict default — never served unless opted into yellow.
# (Mirrors the historical default-deny; the fingerprint-generalized tier is the risky one.)
QUARANTINED_SOURCES = frozenset({'fingerprint'})

_TRUTHY = frozenset({'1', 'true', 'yes', 'on'})
_YELLOW_ALIASES = frozenset({'yellow', 'ride', 'all'})  # "let it ride"; 'green' is an alias of strict


class Policy(BaseModel):
    """Effective pipeline policy. Frozen — share freely across threads/sessions without copying.

    Attributes:
        atom_reads: Serve a contract from the field-atom index on a legacy-cache miss. Default-deny.
        trust_tier: ``strict`` quarantines the fingerprint-generalized (risky) reuse tier;
            ``yellow`` ("let it ride") serves every tier.
    """

    model_config = ConfigDict(frozen=True)

    atom_reads: bool = False
    trust_tier: TrustTier = 'strict'

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Policy:
        """The ``env`` layer of the cascade: read the (legacy) ``YOSOI_*`` switches.

        Both fields are set explicitly, so this layer overrides the shipped defaults but is itself
        overridden by any session/contract/call layer passed after it to :meth:`resolve`.
        """
        src = os.environ if env is None else env
        reads = src.get('YOSOI_ATOM_READS', '').strip().lower() in _TRUTHY
        mode = src.get('YOSOI_ATOM_TRUST', 'strict').strip().lower()
        tier: TrustTier = 'yellow' if mode in _YELLOW_ALIASES else 'strict'
        return cls(atom_reads=reads, trust_tier=tier)

    @classmethod
    def resolve(cls, *layers: Policy | None) -> Policy:
        """Merge cascade layers (lowest precedence first) into one effective Policy.

        Each layer contributes only the fields it explicitly set (``model_fields_set``), so a
        partial override like ``Policy(trust_tier='yellow')`` changes only the tier. ``None`` layers
        are skipped, so callers can pass optional session/contract/call overrides positionally.
        """
        merged: dict[str, Any] = {}
        for layer in layers:
            if layer is not None:
                merged.update(layer.model_dump(exclude_unset=True))
        return cls(**merged)

    @property
    def allowed_sources(self) -> frozenset[str] | None:
        """Provenance ``source`` tiers eligible to serve under this policy; ``None`` = all (yellow).

        Strict serves everything EXCEPT :data:`QUARANTINED_SOURCES` (default-deny the risky);
        yellow returns ``None`` (serve every tier, including fingerprint-generalized reuse).
        """
        from yosoi.storage.atoms import SOURCE_TRUST

        if self.trust_tier == 'yellow':
            return None
        return frozenset(s for s in SOURCE_TRUST if s not in QUARANTINED_SOURCES)
