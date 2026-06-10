"""Type stubs for yosoi public API."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from yosoi.core.configs import DebugConfig as DebugConfig
from yosoi.core.configs import DiscoveryConfig as DiscoveryConfig
from yosoi.core.configs import TelemetryConfig as TelemetryConfig
from yosoi.core.configs import YosoiConfig as YosoiConfig
from yosoi.core.configs import auto_config as auto_config
from yosoi.core.crawler import CrawlRunSummary as CrawlRunSummary
from yosoi.core.discovery import LLMConfig as LLMConfig
from yosoi.core.discovery.config import LLMBuilder as LLMBuilder
from yosoi.core.pipeline import Pipeline as Pipeline
from yosoi.generalization.fingerprint import PageFingerprint as PageFingerprint
from yosoi.integrations import ClaudeSDKModel as ClaudeSDKModel
from yosoi.integrations import OpenCodeModel as OpenCodeModel
from yosoi.models.contract import Contract as Contract
from yosoi.models.defaults import JobPosting as JobPosting
from yosoi.models.defaults import NewsArticle as NewsArticle
from yosoi.models.defaults import Product as Product
from yosoi.models.defaults import Video as Video
from yosoi.models.download import DownloadRecord as DownloadRecord
from yosoi.models.selectors import FieldSelectors as FieldSelectors
from yosoi.models.selectors import SelectorEntry as SelectorEntry
from yosoi.models.selectors import SelectorLevel as SelectorLevel
from yosoi.models.snapshot import CacheVerdict as CacheVerdict
from yosoi.models.snapshot import SelectorSnapshot as SelectorSnapshot
from yosoi.models.snapshot import SnapshotMap as SnapshotMap
from yosoi.models.snapshot import SnapshotStatus as SnapshotStatus
from yosoi.policy import CrawlBudget as _CrawlBudget
from yosoi.policy import CrawlPolicy as _CrawlPolicy
from yosoi.policy import CrawlRuntimeConfig as _CrawlRuntimeConfig
from yosoi.policy import CrawlSafety as _CrawlSafety
from yosoi.policy import CrawlTarget as _CrawlTarget
from yosoi.policy import EscalationPolicy as _EscalationPolicy
from yosoi.policy import FingerprintPolicy as _FingerprintPolicy
from yosoi.policy import Outcome as _Outcome
from yosoi.policy import Policy as _Policy
from yosoi.policy import PolicyCheck as _PolicyCheck
from yosoi.policy import SchedulerPolicy as _SchedulerPolicy
from yosoi.policy import Trust as _Trust
from yosoi.types.field import Field as Field
from yosoi.types.field import js as js
from yosoi.types.registry import register_coercion as register_coercion
from yosoi.utils.contracts import resolve_contract as resolve_contract
from yosoi.utils.urls import load_urls_from_file as load_urls_from_file

TrustTier = Literal['strict', 'yellow']
CrawlModeName = Literal['seed_hunt', 'contract_focus', 'structure_guarded', 'explorer']
FetcherName = Literal['auto', 'simple', 'headless', 'headful']

class CrawlBudget(_CrawlBudget):
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

class SchedulerPolicy(_SchedulerPolicy):
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

class CrawlSafety(_CrawlSafety):
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

class EscalationPolicy(_EscalationPolicy):
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

class CrawlTarget(_CrawlTarget):
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

class CrawlRuntimeConfig(_CrawlRuntimeConfig):
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

    def __init__(
        self,
        *,
        seeds: tuple[str, ...] = ...,
        mode: CrawlModeName = ...,
        max_pages: int = ...,
        max_depth: int = ...,
        max_attempts: int | None = ...,
        max_pages_per_host: int | None = ...,
        crawl_session_id: str | None = ...,
        max_workers: int = ...,
        per_host_concurrency: int = ...,
        politeness_delay: float = ...,
        fetch_timeout_seconds: float = ...,
        max_fetch_retries: int = ...,
        respect_robots: bool = ...,
        allow_cross_domain: bool = ...,
        allowed_hosts: tuple[str, ...] = ...,
        denied_hosts: tuple[str, ...] = ...,
        blocked_path_prefixes: tuple[str, ...] = ...,
        fetcher_type: FetcherName = ...,
    ) -> None: ...

class CrawlPolicy(_CrawlPolicy):
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

class PolicyCheck(_PolicyCheck):
    valid: bool
    policy_hash: str
    warnings: tuple[str, ...]
    runtime: CrawlRuntimeConfig | None

class FingerprintPolicy(_FingerprintPolicy):
    signal_lane: bool
    backpressure: Literal['defer', 'drop']
    max_queue: int

    def __init__(
        self,
        *,
        signal_lane: bool = ...,
        backpressure: Literal['defer', 'drop'] = ...,
        max_queue: int = ...,
    ) -> None: ...

class Policy(_Policy):
    atom_reads: bool
    trust_tier: TrustTier
    crawl: CrawlPolicy | None
    fingerprint: FingerprintPolicy | None

    def __init__(
        self,
        *,
        atom_reads: bool = ...,
        trust_tier: TrustTier = ...,
        crawl: CrawlPolicy | None = ...,
        fingerprint: FingerprintPolicy | None = ...,
    ) -> None: ...
    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = ...) -> Policy: ...
    @classmethod
    def for_crawl(cls, preset: str | None = ..., **overrides: Any) -> Policy: ...
    @classmethod
    def cascade(cls, *layers: _Policy | None) -> Policy: ...
    @property
    def policy_hash(self) -> str: ...
    @property
    def allowed_sources(self) -> frozenset[str] | None: ...
    def require_crawl(self) -> CrawlPolicy: ...
    def check_crawl(self, *, seeds: tuple[str, ...] = ...) -> PolicyCheck: ...
    def source_trust(self, source: str) -> _Trust: ...
    def allows_source(self, source: str) -> bool: ...
    def output_trust(self, source: str) -> _Trust: ...

def policy_arn(namespace: str, name: str) -> str: ...
def resolve_crawl_policy(policy: str | CrawlPolicy | Policy | None = ...) -> CrawlPolicy: ...
def check_policy(policy: str | CrawlPolicy | Policy | None = ..., *, seeds: tuple[str, ...] = ...) -> PolicyCheck: ...
def promote_trust(trust: _Trust, *, confirmed: bool) -> tuple[_Trust, _Outcome]: ...
def css(value: str) -> SelectorEntry: ...
def xpath(value: str) -> SelectorEntry: ...
def regex(value: str) -> SelectorEntry: ...
def jsonld(value: str) -> SelectorEntry: ...
def attr(value: str, name: str) -> SelectorEntry: ...
def global_id(value: str, name: str) -> SelectorEntry: ...
def role(value: str, name: str, nth: int = ...) -> SelectorEntry: ...
def visual(x: float, y: float, value: str = ...) -> SelectorEntry: ...

# Semantic type factories — override the dynamic signatures produced by @register_coercion
# Return Any (not FieldInfo) so assignments like `name: str = ys.Title()` pass type checking,
# matching pydantic.Field()'s own stub convention.
def Title(description: str = ..., **kwargs: Any) -> Any: ...
def Price(
    description: str = ..., *, currency_symbol: str | None = ..., require_decimals: bool = ..., **kwargs: Any
) -> Any: ...
def Rating(description: str = ..., *, as_float: bool = ..., scale: int = ..., **kwargs: Any) -> Any: ...
def BodyText(description: str = ..., **kwargs: Any) -> Any: ...
def Author(description: str = ..., **kwargs: Any) -> Any: ...
def Url(description: str = ..., *, require_https: bool = ..., strip_tracking: bool = ..., **kwargs: Any) -> Any: ...
def Datetime(
    description: str = ..., *, assume_utc: bool = ..., past_only: bool = ..., as_iso: bool = ..., **kwargs: Any
) -> Any: ...
def File(
    *,
    trigger: str | None = ...,
    href: str | None = ...,
    url: str | None = ...,
    description: str | None = ...,
    allowed_types: Iterable[str] | None = ...,
    max_bytes: int | None = ...,
    **kwargs: Any,
) -> Any: ...

# Selector helpers
def discover() -> SelectorEntry: ...

# Provider helpers
def alibaba(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def anthropic(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def azure(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def bedrock(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def cerebras(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def claude_sdk(model_name: str = ..., **kwargs: Any) -> LLMConfig: ...
def deepseek(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def fireworks(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def gemini(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def github(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def grok(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def groq(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def heroku(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def huggingface(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def litellm(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def mistral(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def moonshotai(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def nebius(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def ollama(model_name: str, **kwargs: Any) -> LLMConfig: ...
def openai(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def opencode(model_name: str = ..., **kwargs: Any) -> LLMConfig: ...
def openrouter(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def ovhcloud(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def provider(model_string: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def sambanova(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def together(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def vercel(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def vertexai(model_name: str, **kwargs: Any) -> LLMConfig: ...
def xai(model_name: str, api_key: str | None = ..., **kwargs: Any) -> LLMConfig: ...
def fingerprint(
    source: object,
    *,
    ax_snapshot: Any = ...,
    headers: dict[str, str] | None = ...,
    endpoints: Sequence[str] | None = ...,
) -> PageFingerprint: ...
async def crawl_index(
    seeds: Sequence[str],
    *,
    policy: Policy | None = ...,
    fetcher_type: str | None = ...,
    persist: bool = ...,
) -> CrawlRunSummary: ...
async def scrape(
    url: str | Sequence[str],
    contract: type[Contract] | str | Sequence[type[Contract] | str],
    model: YosoiConfig | LLMConfig | str | None = ...,
    **kwargs: Any,
) -> list[dict[str, Any]] | dict[str, list[dict[str, Any]]] | dict[str, dict[str, list[dict[str, Any]]]]: ...
async def scrape_many(
    urls: list[str] | tuple[str, ...],
    contract: type[Contract] | str,
    model: YosoiConfig | LLMConfig | str | None = ...,
    **kwargs: Any,
) -> dict[str, list[dict[str, Any]]]: ...
def scrape_sync(
    url: str,
    contract: type[Contract] | str,
    model: YosoiConfig | LLMConfig | str | None = ...,
    **kwargs: Any,
) -> list[dict[str, Any]]: ...
def show(
    value: Any,
    *,
    format: Literal['auto', 'table', 'plain', 'json'] = ...,
    title: str | None = ...,
    console: Any = ...,
    fingerprint: object | bool | None = ...,
) -> None: ...

__version__: str
__all__: list[str]
