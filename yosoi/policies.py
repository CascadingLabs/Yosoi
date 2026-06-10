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

import hashlib
import json
import os
from collections.abc import Callable, Iterable, Mapping
from enum import Enum
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

TrustTier = Literal['strict', 'yellow']
CrawlModeName = Literal['seed_hunt', 'contract_focus', 'structure_guarded', 'explorer']
FetcherName = Literal['auto', 'simple', 'headless', 'headful']


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
_POLICY_ARN_PREFIX = 'arn:yosoi:policy:'


def _classify_tier(raw: str) -> TrustTier:
    """Normalize a raw trust-mode string to a tier — the ONE place trust aliases are decided."""
    return 'yellow' if raw.strip().lower() in _YELLOW_ALIASES else 'strict'


def _normalize_host(host: str) -> str:
    """Normalize a policy host token without accepting path/query-shaped values."""
    value = host.strip().lower()
    if not value:
        raise ValueError('host entries must be non-empty strings')
    parsed = urlparse(value if '://' in value else f'//{value}')
    if parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
        raise ValueError(f'host entries may not include paths or query strings: {host!r}')
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f'invalid host entry: {host!r}')
    return hostname


def _normalize_path_prefix(raw: str) -> str | None:
    """Normalize a blocked-path-prefix token; empty → None; non-anchored → ValueError."""
    prefix = raw.strip()
    if not prefix:
        return None
    if not prefix.startswith('/'):
        raise ValueError(f'blocked_path_prefixes must start with "/": {prefix!r}')
    return prefix


def _coerce_str_tuple(value: object, *, normalize: Callable[[str], str | None], label: str) -> tuple[str, ...]:
    """Coerce None/str/iterable into a deduped tuple of normalized (non-None) string tokens."""
    if value is None:
        return ()
    if isinstance(value, str):
        raw = (value,)
    elif isinstance(value, Iterable):
        raw = tuple(value)
    else:
        raise TypeError(label)
    return tuple(dict.fromkeys(n for n in (normalize(str(i)) for i in raw) if n is not None))


def policy_arn(namespace: str, name: str) -> str:
    """Return an ARN-like stable address for a local policy preset."""
    namespace = namespace.strip()
    name = name.strip()
    if not namespace or not name:
        raise ValueError('namespace and name must be non-empty')
    return f'{_POLICY_ARN_PREFIX}{namespace}/{name}'


def _reject_bool(value: object) -> object:
    """Reject bools before Pydantic treats them as ints."""
    if isinstance(value, bool):
        raise ValueError('boolean values are not valid numeric policy settings')
    return value


# Numeric policy types that reject bool (Python's bool is an int) before coercion. Each field keeps
# its own Field(default=..., ge=..., le=..., gt=...) — bounds differ per field, so don't fold them in.
StrictInt = Annotated[int, BeforeValidator(_reject_bool)]
StrictFloat = Annotated[float, BeforeValidator(_reject_bool)]
StrictOptInt = Annotated[int | None, BeforeValidator(_reject_bool)]


class CrawlBudget(BaseModel):
    """Budget controls and traversal limits for one crawl/index run."""

    model_config = ConfigDict(frozen=True)

    max_pages: StrictInt = Field(default=1, ge=1, le=1_000_000)
    max_depth: StrictInt = Field(default=0, ge=0, le=20)
    max_attempts: StrictOptInt = Field(default=None, ge=1, le=2_000_000)
    max_pages_per_host: StrictOptInt = Field(default=None, ge=1, le=1_000_000)
    crawl_session_id: str | None = None

    @field_validator('crawl_session_id')
    @classmethod
    def _clean_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > 120:
            raise ValueError('crawl_session_id must be <= 120 characters')
        return cleaned

    @model_validator(mode='after')
    def _validate_attempt_budget(self) -> CrawlBudget:
        if self.max_attempts is not None and self.max_attempts < self.max_pages:
            raise ValueError('max_attempts must be >= max_pages when set')
        if self.max_pages == 1 and self.max_depth > 0:
            raise ValueError('max_depth > 0 requires max_pages > 1')
        return self


class SchedulerPolicy(BaseModel):
    """Concurrency and politeness controls for crawl workers."""

    model_config = ConfigDict(frozen=True)

    max_workers: StrictInt = Field(default=1, ge=1, le=128)
    per_host_concurrency: StrictInt = Field(default=1, ge=1, le=64)
    politeness_delay: StrictFloat = Field(default=1.0, ge=0.0, le=120.0)
    fetch_timeout_seconds: StrictFloat = Field(default=15.0, gt=0.0, le=300.0)
    max_fetch_retries: StrictInt = Field(default=2, ge=0, le=10)

    @model_validator(mode='after')
    def _validate_scheduler_shape(self) -> SchedulerPolicy:
        if self.per_host_concurrency > self.max_workers:
            raise ValueError('per_host_concurrency cannot exceed max_workers')
        return self


class CrawlSafety(BaseModel):
    """Host/domain hygiene and deny rules that fail closed."""

    model_config = ConfigDict(frozen=True)

    respect_robots: bool = True
    allow_cross_domain: bool = False
    allowed_hosts: tuple[str, ...] = ()
    denied_hosts: tuple[str, ...] = ()
    blocked_path_prefixes: tuple[str, ...] = ()

    @field_validator('allowed_hosts', 'denied_hosts', mode='before')
    @classmethod
    def _coerce_hosts(cls, value: object) -> tuple[str, ...]:
        return _coerce_str_tuple(
            value, normalize=_normalize_host, label='host entries must be a string or iterable of strings'
        )

    @field_validator('blocked_path_prefixes', mode='before')
    @classmethod
    def _coerce_path_prefixes(cls, value: object) -> tuple[str, ...]:
        return _coerce_str_tuple(
            value,
            normalize=_normalize_path_prefix,
            label='blocked_path_prefixes must be a string or iterable of strings',
        )

    @model_validator(mode='after')
    def _validate_safety(self) -> CrawlSafety:
        overlap = set(self.allowed_hosts) & set(self.denied_hosts)
        if overlap:
            raise ValueError(f'hosts cannot be both allowed and denied: {sorted(overlap)!r}')
        if self.allow_cross_domain and self.allowed_hosts:
            raise ValueError('allow_cross_domain=True cannot be combined with allowed_hosts')
        return self


class EscalationPolicy(BaseModel):
    """Paid/model/browser escalation permissions for crawl-adjacent work."""

    model_config = ConfigDict(frozen=True)

    allow_model_discovery: bool = False
    allow_paid_scrapers: bool = False
    max_llm_calls: StrictInt = Field(default=0, ge=0, le=100_000)
    max_paid_scraper_calls: StrictInt = Field(default=0, ge=0, le=1_000_000)

    @model_validator(mode='after')
    def _validate_escalation_budget(self) -> EscalationPolicy:
        if not self.allow_model_discovery and self.max_llm_calls:
            raise ValueError('max_llm_calls must be 0 when allow_model_discovery=False')
        if not self.allow_paid_scrapers and self.max_paid_scraper_calls:
            raise ValueError('max_paid_scraper_calls must be 0 when allow_paid_scrapers=False')
        return self


class CrawlTarget(BaseModel):
    """Contract target constraints for crawl planning and reporting."""

    model_config = ConfigDict(frozen=True)

    name: str
    min_fields: StrictInt = Field(default=1, ge=0)
    min_confidence: StrictFloat = Field(default=0.0, ge=0.0, le=1.0)
    max_budget_pages: StrictOptInt = Field(default=None, ge=1)

    @field_validator('name')
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError('target contract name must be non-empty')
        return cleaned


class CrawlPolicy(BaseModel):
    """Declarative crawl/index policy nested under :class:`Policy`."""

    model_config = ConfigDict(frozen=True)

    mode: CrawlModeName = 'contract_focus'
    budget: CrawlBudget = Field(default_factory=CrawlBudget)
    scheduler: SchedulerPolicy = Field(default_factory=SchedulerPolicy)
    safety: CrawlSafety = Field(default_factory=CrawlSafety)
    escalation: EscalationPolicy = Field(default_factory=EscalationPolicy)
    target_contracts: tuple[CrawlTarget, ...] = ()
    fetcher_type: FetcherName = 'auto'

    @model_validator(mode='after')
    def _validate_crawl_policy(self) -> CrawlPolicy:
        if self.mode == 'seed_hunt' and self.target_contracts:
            raise ValueError('seed_hunt policies may not declare target_contracts')
        if self.mode != 'seed_hunt' and not self.target_contracts:
            # Contract names are optional at early API edges, but policy presets for crawl execution
            # should be explicit once the crawl is being planned.
            return self
        return self

    def effective_allowed_hosts(self, seeds: tuple[str, ...] = ()) -> tuple[str, ...]:
        """Resolve the host allow-list that a crawl run should apply."""
        if self.safety.allow_cross_domain:
            return ()
        if self.safety.allowed_hosts:
            return self.safety.allowed_hosts
        hosts: list[str] = []
        for seed in seeds:
            parsed = urlparse(seed)
            if parsed.hostname:
                hosts.append(parsed.hostname.lower())
        return tuple(dict.fromkeys(hosts))

    def to_runtime_config(self, *, seeds: tuple[str, ...] = ()) -> CrawlRuntimeConfig:
        """Return the small runtime config shape needed by crawler executors.

        ``budget``/``scheduler`` splat faithfully (their field sets are exactly the budget/
        scheduler columns of :class:`CrawlRuntimeConfig`); ``safety`` is NOT splatted because
        ``allowed_hosts`` is a computed override (seed-derived) that a splat would clobber.
        """
        return CrawlRuntimeConfig(
            **self.budget.model_dump(),
            **self.scheduler.model_dump(),
            respect_robots=self.safety.respect_robots,
            allow_cross_domain=self.safety.allow_cross_domain,
            denied_hosts=self.safety.denied_hosts,
            blocked_path_prefixes=self.safety.blocked_path_prefixes,
            allowed_hosts=self.effective_allowed_hosts(seeds),
            seeds=seeds,
            mode=self.mode,
            fetcher_type=self.fetcher_type,
        )


class CrawlRuntimeConfig(BaseModel):
    """Executor-facing crawl config produced after policy resolution."""

    model_config = ConfigDict(frozen=True)

    seeds: tuple[str, ...] = ()
    mode: CrawlModeName
    max_pages: int
    max_depth: int
    max_attempts: int | None
    max_pages_per_host: int | None
    crawl_session_id: str | None
    max_workers: int
    per_host_concurrency: int
    politeness_delay: float
    fetch_timeout_seconds: float
    max_fetch_retries: int
    respect_robots: bool
    allow_cross_domain: bool
    allowed_hosts: tuple[str, ...]
    denied_hosts: tuple[str, ...]
    blocked_path_prefixes: tuple[str, ...]
    fetcher_type: FetcherName


class PolicyCheck(BaseModel):
    """Dry-run validation result for policy-as-code workflows."""

    model_config = ConfigDict(frozen=True)

    valid: bool
    policy_hash: str
    warnings: tuple[str, ...] = ()
    runtime: CrawlRuntimeConfig | None = None


_PRESET_CRAWL_POLICIES: dict[str, CrawlPolicy] = {
    'crawl.local_single': CrawlPolicy(
        mode='contract_focus',
        budget=CrawlBudget(max_pages=1, max_depth=0),
        scheduler=SchedulerPolicy(max_workers=1, per_host_concurrency=1, politeness_delay=1.0),
    ),
    'crawl.conservative': CrawlPolicy(
        mode='contract_focus',
        budget=CrawlBudget(max_pages=80, max_depth=2, max_pages_per_host=30),
        scheduler=SchedulerPolicy(max_workers=3, per_host_concurrency=1, politeness_delay=1.0),
    ),
    'crawl.seed_hunt': CrawlPolicy(
        mode='seed_hunt',
        budget=CrawlBudget(max_pages=200, max_depth=2, max_pages_per_host=80),
        scheduler=SchedulerPolicy(max_workers=4, per_host_concurrency=1, politeness_delay=0.8),
    ),
}
_PRESET_ALIASES = {
    **{policy_arn('default', name): name for name in _PRESET_CRAWL_POLICIES},
    'default': 'crawl.local_single',
}


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
    crawl: CrawlPolicy | None = None

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
