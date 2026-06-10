"""Type stubs for yosoi public API."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from yosoi.core.configs import TelemetryConfig as _TelemetryConfig
from yosoi.core.configs import YosoiConfig as _YosoiConfig
from yosoi.core.crawler import CrawlRunSummary as CrawlRunSummary
from yosoi.core.discovery import LLMConfig as _LLMConfig
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
from yosoi.policy import DiscoveryPolicy as _DiscoveryPolicy
from yosoi.policy import DownloadPolicy as _DownloadPolicy
from yosoi.policy import EscalationPolicy as _EscalationPolicy
from yosoi.policy import FingerprintPolicy as _FingerprintPolicy
from yosoi.policy import ModelPolicy as _ModelPolicy
from yosoi.policy import Outcome as _Outcome
from yosoi.policy import OutputPolicy as _OutputPolicy
from yosoi.policy import Policy as _Policy
from yosoi.policy import PolicyCheck as _PolicyCheck
from yosoi.policy import ResolvedRunSpec as _ResolvedRunSpec
from yosoi.policy import SchedulerPolicy as _SchedulerPolicy
from yosoi.policy import ScrapePolicy as _ScrapePolicy
from yosoi.policy import SecretRef as _SecretRef
from yosoi.policy import TelemetryPolicy as _TelemetryPolicy
from yosoi.policy import Trust as _Trust
from yosoi.types.field import Field as Field
from yosoi.types.field import js as js
from yosoi.types.registry import register_coercion as register_coercion
from yosoi.utils.contracts import resolve_contract as resolve_contract
from yosoi.utils.urls import load_urls_from_file as load_urls_from_file

TrustTier = Literal['strict', 'yellow']
CrawlModeName = Literal['seed_hunt', 'contract_focus', 'structure_guarded', 'explorer']
FetcherName = Literal['auto', 'simple', 'headless', 'headful']
DiscoveryMode = Literal['auto', 'static', 'mcp']

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

class SecretRef(_SecretRef):
    source: Literal['env']
    name: str

    def __init__(self, *, source: Literal['env'], name: str) -> None: ...
    @classmethod
    def env(cls, name: str) -> SecretRef: ...
    def resolve(self, env: Mapping[str, str] | None = ...) -> str | None: ...

class ModelPolicy(_ModelPolicy):
    provider: str | None
    model_name: str | None
    temperature: float
    max_tokens: int | None
    extra_params: Mapping[str, Any] | None
    credential_ref: SecretRef | None

    def __init__(
        self,
        *,
        provider: str | None = ...,
        model_name: str | None = ...,
        temperature: float = ...,
        max_tokens: int | None = ...,
        extra_params: Mapping[str, Any] | None = ...,
        credential_ref: SecretRef | None = ...,
    ) -> None: ...
    @classmethod
    def from_string(cls, model: str, **kwargs: Any) -> ModelPolicy: ...

class ScrapePolicy(_ScrapePolicy):
    force: bool
    skip_verification: bool
    fetcher_type: Literal['auto', 'simple', 'headless', 'headful', 'waterfall']
    selector_level: SelectorLevel
    max_concurrency: int | None
    cross_origin_dom: bool

    def __init__(
        self,
        *,
        force: bool = ...,
        skip_verification: bool = ...,
        fetcher_type: Literal['auto', 'simple', 'headless', 'headful', 'waterfall'] = ...,
        selector_level: SelectorLevel = ...,
        max_concurrency: int | None = ...,
        cross_origin_dom: bool = ...,
    ) -> None: ...

class DiscoveryPolicy(_DiscoveryPolicy):
    max_concurrent: int
    mode: DiscoveryMode
    lesson_cache: bool
    replay_verify_threshold: float
    static_mode_warning: bool

    def __init__(
        self,
        *,
        max_concurrent: int = ...,
        mode: DiscoveryMode = ...,
        lesson_cache: bool = ...,
        replay_verify_threshold: float = ...,
        static_mode_warning: bool = ...,
    ) -> None: ...

class TelemetryPolicy(_TelemetryPolicy):
    langfuse_public_key_ref: SecretRef | None
    langfuse_secret_key_ref: SecretRef | None
    langfuse_host: str | None

    def __init__(
        self,
        *,
        langfuse_public_key_ref: SecretRef | None = ...,
        langfuse_secret_key_ref: SecretRef | None = ...,
        langfuse_host: str | None = ...,
    ) -> None: ...

class OutputPolicy(_OutputPolicy):
    formats: tuple[str, ...]
    quiet: bool
    json_output: bool
    debug_html: bool
    debug_html_dir: Any
    logs: bool

class DownloadPolicy(_DownloadPolicy):
    allow: bool
    allowed_types: tuple[str, ...]
    directory: str | None
    max_bytes: int | None
    keep: bool

class ResolvedRunSpec(_ResolvedRunSpec):
    policy_hash: str
    llm_config: _LLMConfig
    telemetry_config: _TelemetryConfig
    force: bool
    fetcher_type: str
    selector_level: SelectorLevel
    cross_origin_dom: bool

class Policy(_Policy):
    atom_reads: bool
    trust_tier: TrustTier
    model: ModelPolicy | None
    scrape: ScrapePolicy | None
    discovery: DiscoveryPolicy | None
    telemetry: TelemetryPolicy | None
    output: OutputPolicy | None
    download: DownloadPolicy | None
    crawl: CrawlPolicy | None
    fingerprint: FingerprintPolicy | None

    def __init__(
        self,
        *,
        atom_reads: bool = ...,
        trust_tier: TrustTier = ...,
        model: ModelPolicy | None = ...,
        scrape: ScrapePolicy | None = ...,
        discovery: DiscoveryPolicy | None = ...,
        telemetry: TelemetryPolicy | None = ...,
        output: OutputPolicy | None = ...,
        download: DownloadPolicy | None = ...,
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
    def resolve_run_spec(self, env: Mapping[str, str] | None = ...) -> ResolvedRunSpec: ...
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
def alibaba(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def anthropic(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def azure(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def bedrock(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def cerebras(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def claude_sdk(model_name: str = ..., **kwargs: Any) -> ModelPolicy: ...
def deepseek(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def fireworks(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def gemini(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def github(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def grok(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def groq(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def heroku(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def huggingface(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def litellm(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def mistral(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def moonshotai(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def nebius(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def ollama(model_name: str, **kwargs: Any) -> ModelPolicy: ...
def openai(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def opencode(model_name: str = ..., **kwargs: Any) -> ModelPolicy: ...
def openrouter(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def ovhcloud(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def provider(model_string: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def sambanova(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def together(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def vercel(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
def vertexai(model_name: str, **kwargs: Any) -> ModelPolicy: ...
def xai(model_name: str, api_key: str | None = ..., **kwargs: Any) -> ModelPolicy: ...
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
    model: _YosoiConfig | _LLMConfig | ModelPolicy | str | None = ...,
    **kwargs: Any,
) -> list[dict[str, Any]] | dict[str, list[dict[str, Any]]] | dict[str, dict[str, list[dict[str, Any]]]]: ...
async def scrape_many(
    urls: list[str] | tuple[str, ...],
    contract: type[Contract] | str,
    model: _YosoiConfig | _LLMConfig | ModelPolicy | str | None = ...,
    **kwargs: Any,
) -> dict[str, list[dict[str, Any]]]: ...
def scrape_sync(
    url: str,
    contract: type[Contract] | str,
    model: _YosoiConfig | _LLMConfig | ModelPolicy | str | None = ...,
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
