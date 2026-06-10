"""Type stubs for policy-as-code helpers."""

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel

TrustTier = Literal['strict', 'yellow']
CrawlModeName = Literal['seed_hunt', 'contract_focus', 'structure_guarded', 'explorer']
FetcherName = Literal['auto', 'simple', 'headless', 'headful']

TRUSTED_SOURCES: frozenset[str]
QUARANTINED_SOURCES: frozenset[str]

class Trust(str, Enum):
    VERIFIED = 'verified'
    QUARANTINED = 'quarantined'
    REJECTED = 'rejected'

class Outcome(str, Enum):
    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    REFUTED = 'refuted'

class CrawlBudget(BaseModel):
    max_pages: int
    max_depth: int
    max_attempts: int | None
    max_pages_per_host: int | None
    crawl_session_id: str | None

    def __init__(
        self,
        *,
        max_pages: int = ...,
        max_depth: int = ...,
        max_attempts: int | None = ...,
        max_pages_per_host: int | None = ...,
        crawl_session_id: str | None = ...,
    ) -> None: ...

class SchedulerPolicy(BaseModel):
    max_workers: int
    per_host_concurrency: int
    politeness_delay: float
    fetch_timeout_seconds: float
    max_fetch_retries: int

    def __init__(
        self,
        *,
        max_workers: int = ...,
        per_host_concurrency: int = ...,
        politeness_delay: float = ...,
        fetch_timeout_seconds: float = ...,
        max_fetch_retries: int = ...,
    ) -> None: ...

class CrawlSafety(BaseModel):
    respect_robots: bool
    allow_cross_domain: bool
    allowed_hosts: tuple[str, ...]
    denied_hosts: tuple[str, ...]
    blocked_path_prefixes: tuple[str, ...]

    def __init__(
        self,
        *,
        respect_robots: bool = ...,
        allow_cross_domain: bool = ...,
        allowed_hosts: tuple[str, ...] = ...,
        denied_hosts: tuple[str, ...] = ...,
        blocked_path_prefixes: tuple[str, ...] = ...,
    ) -> None: ...

class EscalationPolicy(BaseModel):
    allow_model_discovery: bool
    allow_paid_scrapers: bool
    max_llm_calls: int
    max_paid_scraper_calls: int

    def __init__(
        self,
        *,
        allow_model_discovery: bool = ...,
        allow_paid_scrapers: bool = ...,
        max_llm_calls: int = ...,
        max_paid_scraper_calls: int = ...,
    ) -> None: ...

class CrawlTarget(BaseModel):
    name: str
    min_fields: int
    min_confidence: float
    max_budget_pages: int | None

    def __init__(
        self,
        *,
        name: str,
        min_fields: int = ...,
        min_confidence: float = ...,
        max_budget_pages: int | None = ...,
    ) -> None: ...

class CrawlRuntimeConfig(BaseModel):
    seeds: tuple[str, ...]
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

class CrawlPolicy(BaseModel):
    mode: CrawlModeName
    budget: CrawlBudget
    scheduler: SchedulerPolicy
    safety: CrawlSafety
    escalation: EscalationPolicy
    target_contracts: tuple[CrawlTarget, ...]
    fetcher_type: FetcherName

    def __init__(
        self,
        *,
        mode: CrawlModeName = ...,
        budget: CrawlBudget = ...,
        scheduler: SchedulerPolicy = ...,
        safety: CrawlSafety = ...,
        escalation: EscalationPolicy = ...,
        target_contracts: tuple[CrawlTarget, ...] = ...,
        fetcher_type: FetcherName = ...,
    ) -> None: ...
    def effective_allowed_hosts(self, seeds: tuple[str, ...] = ...) -> tuple[str, ...]: ...
    def to_runtime_config(self, *, seeds: tuple[str, ...] = ...) -> CrawlRuntimeConfig: ...

class PolicyCheck(BaseModel):
    valid: bool
    policy_hash: str
    warnings: tuple[str, ...]
    runtime: CrawlRuntimeConfig | None

class Policy(BaseModel):
    atom_reads: bool
    trust_tier: TrustTier
    crawl: CrawlPolicy | None

    def __init__(
        self,
        *,
        atom_reads: bool = ...,
        trust_tier: TrustTier = ...,
        crawl: CrawlPolicy | None = ...,
    ) -> None: ...
    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = ...) -> Policy: ...
    @classmethod
    def for_crawl(cls, preset: str | None = ..., **overrides: Any) -> Policy: ...
    @classmethod
    def cascade(cls, *layers: Policy | None) -> Policy: ...
    @property
    def policy_hash(self) -> str: ...
    @property
    def allowed_sources(self) -> frozenset[str] | None: ...
    def require_crawl(self) -> CrawlPolicy: ...
    def check_crawl(self, *, seeds: tuple[str, ...] = ...) -> PolicyCheck: ...
    def source_trust(self, source: str) -> Trust: ...
    def allows_source(self, source: str) -> bool: ...
    def output_trust(self, source: str) -> Trust: ...

def policy_arn(namespace: str, name: str) -> str: ...
def resolve_crawl_policy(policy: str | CrawlPolicy | Policy | None = ...) -> CrawlPolicy: ...
def check_policy(policy: str | CrawlPolicy | Policy | None = ..., *, seeds: tuple[str, ...] = ...) -> PolicyCheck: ...
def promote_trust(trust: Trust, *, confirmed: bool) -> tuple[Trust, Outcome]: ...
