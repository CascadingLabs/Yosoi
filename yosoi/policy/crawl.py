"""The **crawl stack** — declarative crawl policy and the executor-facing runtime config.

One pipeline stack expressed as frozen pydantic models over the shared :mod:`yosoi.policy._base`
primitives. New stacks (e.g. a future ``scrape`` stack) live in sibling modules with the same shape:
nested sub-policies + presets + a ``to_runtime_config`` projection — so ``ys.policy`` grows
horizontally without touching the core :class:`~yosoi.policy.core.Policy` value object.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yosoi.policy._base import (
    StrictFloat,
    StrictInt,
    StrictOptInt,
    _coerce_str_tuple,
    _normalize_host,
    _normalize_path_prefix,
    policy_arn,
)
from yosoi.policy.page import PagePolicy, PageRuntimeConfig

CrawlModeName = Literal['seed_hunt', 'contract_focus', 'structure_guarded', 'explorer']
FetcherName = Literal['auto', 'simple', 'headless', 'headful']
CrawlPresetName = Literal['crawl.local_single', 'crawl.conservative', 'crawl.seed_hunt']


class CrawlBudget(BaseModel):
    """Budget controls and traversal limits for one crawl run."""

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

    respect_robots: bool = True  # default: honor robots.txt; set False to opt out of robots compliance
    allow_redirects: bool = False
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


class PathPlanningPolicy(BaseModel):
    """URL-shape planning controls for crawl frontier prioritization."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    min_similarity: StrictFloat = Field(default=0.72, ge=0.0, le=1.0)
    score_boost: StrictFloat = Field(default=0.20, ge=0.0, le=1.0)
    max_reference_urls: StrictInt = Field(default=25, ge=1, le=1_000)


class CrawlTarget(BaseModel):
    """Contract target constraints for crawl planning and reporting."""

    model_config = ConfigDict(frozen=True)

    name: str
    min_fields: StrictInt = Field(default=1, ge=0)
    min_fit_score: StrictFloat = Field(default=0.0, ge=0.0, le=1.0)
    max_budget_pages: StrictOptInt = Field(default=None, ge=1)
    intent_tokens: tuple[str, ...] = ()

    @field_validator('name')
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError('target contract name must be non-empty')
        return cleaned


class CrawlPolicy(BaseModel):
    """Declarative crawl policy nested under :class:`~yosoi.policy.core.Policy`."""

    model_config = ConfigDict(frozen=True)

    mode: CrawlModeName = 'contract_focus'
    budget: CrawlBudget = Field(default_factory=CrawlBudget)
    scheduler: SchedulerPolicy = Field(default_factory=SchedulerPolicy)
    safety: CrawlSafety = Field(default_factory=CrawlSafety)
    escalation: EscalationPolicy = Field(default_factory=EscalationPolicy)
    path_planning: PathPlanningPolicy = Field(default_factory=PathPlanningPolicy)
    target_contracts: tuple[CrawlTarget, ...] = ()
    scrape_contracts: bool = False
    scrape_url_limit_per_contract: StrictInt = Field(default=1, ge=1, le=1_000)
    fetcher_type: FetcherName = 'auto'

    @field_validator('target_contracts', mode='before')
    @classmethod
    def _coerce_target_contracts(cls, value: object) -> tuple[CrawlTarget, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (CrawlTarget(name=value),)
        if isinstance(value, CrawlTarget):
            return (value,)
        try:
            items: tuple[object, ...] = tuple(value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise TypeError('target_contracts must be a string, CrawlTarget, or iterable of those') from exc
        targets: list[CrawlTarget] = []
        for item in items:
            if isinstance(item, CrawlTarget):
                targets.append(item)
            elif isinstance(item, str):
                targets.append(CrawlTarget(name=item))
            else:
                targets.append(CrawlTarget.model_validate(item))
        return tuple(targets)

    @model_validator(mode='after')
    def _validate_crawl_policy(self) -> CrawlPolicy:
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
            allow_redirects=self.safety.allow_redirects,
            allow_cross_domain=self.safety.allow_cross_domain,
            denied_hosts=self.safety.denied_hosts,
            blocked_path_prefixes=self.safety.blocked_path_prefixes,
            allowed_hosts=self.effective_allowed_hosts(seeds),
            seeds=seeds,
            mode=self.mode,
            path_planning=self.path_planning,
            target_contracts=self.target_contracts,
            page=PagePolicy(
                fetcher_type=self.fetcher_type,
                timeout_seconds=self.scheduler.fetch_timeout_seconds,
                max_fetch_retries=self.scheduler.max_fetch_retries,
                allow_redirects=self.safety.allow_redirects,
            ).to_runtime_config(),
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
    allow_redirects: bool
    allow_cross_domain: bool
    allowed_hosts: tuple[str, ...]
    denied_hosts: tuple[str, ...]
    blocked_path_prefixes: tuple[str, ...]
    path_planning: PathPlanningPolicy = Field(default_factory=PathPlanningPolicy)
    target_contracts: tuple[CrawlTarget, ...] = ()
    page: PageRuntimeConfig
    fetcher_type: FetcherName


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
