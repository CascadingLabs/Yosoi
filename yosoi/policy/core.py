"""The policy **core** — one resolved, immutable value object over every pipeline stack.

A :class:`Policy` collapses the decisions that change *how* the pipeline behaves (not *what* a
contract means) into a single frozen value, **resolved once at the edge** and threaded through the
pure core — so the replay ``resolve()`` stays a deterministic function of its inputs and never reads
the environment deep in the stack (the CAS-119 purity contract).

``Policy`` holds the always-on knobs (atom reads, trust tier) plus an optional per-stack sub-policy
(``crawl`` today). Each stack lives in its own module (:mod:`yosoi.policy.crawl`, …) so the surface
grows horizontally; ``core`` only knows how to *carry and resolve* them.

Precedence (lowest → highest): ``defaults < env < session < contract < call-site``.
:meth:`Policy.cascade` merges partial overrides (only the fields each layer explicitly set) into
one effective Policy.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from yosoi.policy._base import (
    _TRUTHY,
    QUARANTINED_SOURCES,
    TRUSTED_SOURCES,
    Trust,
    TrustTier,
    _classify_tier,
)
from yosoi.policy.crawl import (
    _PRESET_ALIASES,
    _PRESET_CRAWL_POLICIES,
    CrawlPolicy,
    CrawlRuntimeConfig,
)
from yosoi.policy.fingerprint import FingerprintPolicy


class PolicyCheck(BaseModel):
    """Dry-run validation result for policy-as-code workflows."""

    model_config = ConfigDict(frozen=True)

    valid: bool
    policy_hash: str
    warnings: tuple[str, ...] = ()
    runtime: CrawlRuntimeConfig | None = None


class Policy(BaseModel):
    """Effective pipeline policy. Frozen — share freely across threads/sessions without copying.

    Attributes:
        atom_reads: Serve a contract from the field-atom index on a legacy-cache miss. Default-deny.
        trust_tier: ``strict`` serves only :data:`TRUSTED_SOURCES` (quarantines the risky
            fingerprint-generalized reuse); ``yellow`` ("let it ride") serves every tier.
        crawl: Optional crawl-stack sub-policy (see :mod:`yosoi.policy.crawl`).
        fingerprint: Optional signal-lane sub-policy (see :mod:`yosoi.policy.fingerprint`).
    """

    model_config = ConfigDict(frozen=True)

    atom_reads: bool = False
    trust_tier: TrustTier = 'strict'
    crawl: CrawlPolicy | None = None
    fingerprint: FingerprintPolicy | None = None

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
    def for_crawl(
        cls,
        preset: str | None = 'crawl.conservative',
        **overrides: Any,
    ) -> Policy:
        """Build a policy with a resolved crawl preset and validated overrides."""
        crawl = resolve_crawl_policy(preset)
        if overrides:
            crawl_payload = crawl.model_dump()
            crawl_payload.update(overrides)
            crawl = CrawlPolicy.model_validate(crawl_payload)
        return cls(crawl=crawl)

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
    def policy_hash(self) -> str:
        """Stable content hash for provenance and artifact records."""
        payload = self.model_dump(mode='json', exclude_unset=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
        return hashlib.sha256(encoded).hexdigest()[:16]

    def require_crawl(self) -> CrawlPolicy:
        """Return the crawl policy or fail before a crawl can start."""
        if self.crawl is None:
            raise ValueError('Policy does not include crawl settings')
        return self.crawl

    def check_crawl(self, *, seeds: tuple[str, ...] = ()) -> PolicyCheck:
        """Dry-run crawl policy validation and runtime config derivation."""
        crawl = self.require_crawl()
        runtime = crawl.to_runtime_config(seeds=seeds)
        warnings: list[str] = []
        if runtime.max_workers > runtime.max_pages:
            warnings.append('max_workers exceeds max_pages; some workers will be idle')
        if runtime.max_depth > 0 and runtime.max_pages <= runtime.max_depth:
            warnings.append('max_pages may be too small to use the requested max_depth')
        if not runtime.allowed_hosts and not runtime.allow_cross_domain:
            warnings.append('no allowed_hosts resolved; pass seeds or set safety.allowed_hosts')
        if runtime.per_host_concurrency > 1 and runtime.politeness_delay == 0:
            warnings.append('same-host concurrency without politeness_delay can be impolite')
        return PolicyCheck(valid=True, policy_hash=self.policy_hash, warnings=tuple(warnings), runtime=runtime)

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


def resolve_crawl_policy(policy: str | CrawlPolicy | Policy | None = None) -> CrawlPolicy:
    """Resolve a crawl policy preset, ARN, inline crawl policy, or full Policy."""
    if isinstance(policy, Policy):
        return policy.require_crawl()
    if isinstance(policy, CrawlPolicy):
        return policy
    key = policy or 'crawl.local_single'
    key = _PRESET_ALIASES.get(key, key)
    if key in _PRESET_CRAWL_POLICIES:
        return _PRESET_CRAWL_POLICIES[key]
    raise KeyError(f'Unknown crawl policy: {policy}')


def check_policy(policy: str | CrawlPolicy | Policy | None = None, *, seeds: tuple[str, ...] = ()) -> PolicyCheck:
    """Validate a crawl policy reference without running network, browser, or model work."""
    resolved = policy if isinstance(policy, Policy) else Policy(crawl=resolve_crawl_policy(policy))
    return resolved.check_crawl(seeds=seeds)
