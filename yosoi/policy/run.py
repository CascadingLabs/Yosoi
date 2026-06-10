"""Run-stack policy models and execution-time resolution."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from yosoi.models.selectors import SelectorLevel
from yosoi.policy._base import StrictFloat, StrictInt

FetcherPolicyName = Literal['auto', 'simple', 'headless', 'headful', 'waterfall']
DiscoveryMode = Literal['auto', 'static', 'mcp']


class SecretRef(BaseModel):
    """Reference to a secret resolved only at run time."""

    model_config = ConfigDict(frozen=True)

    source: Literal['env']
    name: str
    _secret_value: str | None = PrivateAttr(default=None)

    @classmethod
    def env(cls, name: str) -> SecretRef:
        """Reference an environment variable without embedding its value."""
        return cls(source='env', name=name)

    @field_validator('name')
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('secret env var name must be non-empty')
        return value

    def resolve(self, env: Mapping[str, str] | None = None) -> str | None:
        """Resolve this reference from the provided environment mapping."""
        src = os.environ if env is None else env
        return src.get(self.name)


class ModelPolicy(BaseModel):
    """Declarative model/provider policy."""

    model_config = ConfigDict(frozen=True)

    provider: str | None = None
    model_name: str | None = None
    temperature: StrictFloat = Field(default=0.01, ge=0.0, le=2.0)
    max_tokens: StrictInt | None = Field(default=None, gt=0)
    extra_params: Mapping[str, Any] | None = None
    credential_ref: SecretRef | None = None
    _runtime_api_key: str | None = PrivateAttr(default=None)

    @classmethod
    def from_string(cls, model: str, **kwargs: Any) -> ModelPolicy:
        """Build a model policy from ``provider:model-name``."""
        from yosoi.core.discovery.config import _parse_model_string

        provider, model_name = _parse_model_string(model)
        return cls(provider=provider, model_name=model_name, **kwargs)

    @model_validator(mode='after')
    def _validate_pair(self) -> ModelPolicy:
        if (self.provider is None) != (self.model_name is None):
            raise ValueError('model.provider and model.model_name must be set together')
        return self


def _model_policy(provider_name: str, model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Build a public model policy while keeping direct secrets runtime-only."""
    policy = ModelPolicy(provider=provider_name, model_name=model_name, **kwargs)
    if api_key is not None:
        policy._runtime_api_key = api_key
    return policy


def provider(model_string: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a model policy from ``provider:model-name``."""
    policy = ModelPolicy.from_string(model_string, **kwargs)
    if api_key is not None:
        policy._runtime_api_key = api_key
    return policy


def anthropic(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create an Anthropic model policy."""
    return _model_policy('anthropic', model_name, api_key, **kwargs)


def groq(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Groq model policy."""
    return _model_policy('groq', model_name, api_key, **kwargs)


def gemini(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Gemini model policy."""
    return _model_policy('gemini', model_name, api_key, **kwargs)


def mistral(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Mistral model policy."""
    return _model_policy('mistral', model_name, api_key, **kwargs)


def cerebras(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Cerebras model policy."""
    return _model_policy('cerebras', model_name, api_key, **kwargs)


def huggingface(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Hugging Face model policy."""
    return _model_policy('huggingface', model_name, api_key, **kwargs)


def xai(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create an xAI model policy."""
    return _model_policy('xai', model_name, api_key, **kwargs)


def bedrock(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Bedrock model policy."""
    return _model_policy('bedrock', model_name, api_key, **kwargs)


def vertexai(model_name: str, **kwargs: Any) -> ModelPolicy:
    """Create a Vertex AI model policy."""
    return _model_policy('vertexai', model_name, None, **kwargs)


def openai(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create an OpenAI model policy."""
    return _model_policy('openai', model_name, api_key, **kwargs)


def openrouter(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create an OpenRouter model policy."""
    return _model_policy('openrouter', model_name, api_key, **kwargs)


def azure(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create an Azure OpenAI model policy."""
    return _model_policy('azure', model_name, api_key, **kwargs)


def deepseek(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a DeepSeek model policy."""
    return _model_policy('deepseek', model_name, api_key, **kwargs)


def ollama(model_name: str, **kwargs: Any) -> ModelPolicy:
    """Create an Ollama model policy."""
    return _model_policy('ollama', model_name, None, **kwargs)


def fireworks(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Fireworks model policy."""
    return _model_policy('fireworks', model_name, api_key, **kwargs)


def together(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Together AI model policy."""
    return _model_policy('together', model_name, api_key, **kwargs)


def nebius(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Nebius model policy."""
    return _model_policy('nebius', model_name, api_key, **kwargs)


def moonshotai(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Moonshot AI model policy."""
    return _model_policy('moonshotai', model_name, api_key, **kwargs)


def grok(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Grok model policy."""
    return _model_policy('grok', model_name, api_key, **kwargs)


def alibaba(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create an Alibaba model policy."""
    return _model_policy('alibaba', model_name, api_key, **kwargs)


def sambanova(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a SambaNova model policy."""
    return _model_policy('sambanova', model_name, api_key, **kwargs)


def ovhcloud(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create an OVHcloud model policy."""
    return _model_policy('ovhcloud', model_name, api_key, **kwargs)


def github(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a GitHub Models policy."""
    return _model_policy('github', model_name, api_key, **kwargs)


def vercel(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Vercel AI model policy."""
    return _model_policy('vercel', model_name, api_key, **kwargs)


def heroku(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a Heroku model policy."""
    return _model_policy('heroku', model_name, api_key, **kwargs)


def litellm(model_name: str, api_key: str | None = None, **kwargs: Any) -> ModelPolicy:
    """Create a LiteLLM model policy."""
    return _model_policy('litellm', model_name, api_key, **kwargs)


def claude_sdk(model_name: str = 'claude-opus-4-7', **kwargs: Any) -> ModelPolicy:
    """Create a Claude SDK model policy."""
    return _model_policy('claude-sdk', model_name, None, **kwargs)


def opencode(model_name: str = 'openai/gpt-5-codex', **kwargs: Any) -> ModelPolicy:
    """Create an OpenCode model policy."""
    return _model_policy('opencode', model_name, None, **kwargs)


class ScrapePolicy(BaseModel):
    """Policy for one scrape execution."""

    model_config = ConfigDict(frozen=True)

    force: bool = False
    skip_verification: bool = False
    fetcher_type: FetcherPolicyName = 'auto'
    selector_level: SelectorLevel = SelectorLevel.CSS
    max_concurrency: StrictInt | None = Field(default=None, gt=0)


class DiscoveryPolicy(BaseModel):
    """Policy for selector discovery behavior."""

    model_config = ConfigDict(frozen=True)

    max_concurrent: StrictInt = Field(default=5, ge=1, le=50)
    mode: DiscoveryMode = 'auto'
    lesson_cache: bool = True
    replay_verify_threshold: StrictFloat = Field(default=1.0, ge=0.0, le=1.0)
    static_mode_warning: bool = True


class TelemetryPolicy(BaseModel):
    """Telemetry policy with secret references instead of raw values."""

    model_config = ConfigDict(frozen=True)

    langfuse_public_key_ref: SecretRef | None = None
    langfuse_secret_key_ref: SecretRef | None = None
    langfuse_host: str | None = None


class OutputPolicy(BaseModel):
    """Output policy for saved formats and CLI presentation."""

    model_config = ConfigDict(frozen=True)

    formats: tuple[str, ...] = ()
    quiet: bool = True
    json_output: bool = False
    debug_html: bool = False
    debug_html_dir: Path = Path('.yosoi/debug_html')
    logs: bool = True

    @field_validator('formats', mode='before')
    @classmethod
    def _coerce_formats(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Sequence):
            return tuple(str(item) for item in value)
        raise TypeError('formats must be a string or sequence of strings')


class DownloadPolicy(BaseModel):
    """Policy for download side effects."""

    model_config = ConfigDict(frozen=True)

    allow: bool = False
    allowed_types: tuple[str, ...] = ()
    directory: str | None = None
    max_bytes: StrictInt | None = Field(default=None, gt=0)
    keep: bool = True

    @field_validator('allowed_types', mode='before')
    @classmethod
    def _coerce_types(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Sequence):
            return tuple(str(item) for item in value)
        raise TypeError('allowed_types must be a string or sequence of strings')

    @model_validator(mode='after')
    def _validate_downloads(self) -> DownloadPolicy:
        if not self.allow and (self.allowed_types or self.directory or self.max_bytes is not None or not self.keep):
            raise ValueError('download settings require DownloadPolicy(allow=True)')
        return self


class ResolvedRunSpec(BaseModel):
    """Execution-time run configuration, including resolved secrets."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    policy_hash: str
    llm_config: Any
    telemetry_config: Any
    debug_html: bool
    debug_html_dir: Path
    force: bool
    skip_verification: bool
    fetcher_type: str
    selector_level: SelectorLevel
    max_concurrency: int | None
    output_formats: tuple[str, ...]
    quiet: bool
    json_output: bool
    allow_downloads: bool
    allowed_download_types: tuple[str, ...]
    download_dir: str | None
    max_download_bytes: int | None
    keep_downloads: bool
    discovery_max_concurrent: int
    discovery_mode: DiscoveryMode
    lesson_cache: bool
    replay_verify_threshold: float
    static_mode_warning: bool


def resolve_telemetry_values(
    telemetry: TelemetryPolicy | None, env: Mapping[str, str] | None = None
) -> dict[str, str | None]:
    """Resolve a telemetry policy's secret refs into raw runtime values.

    Returns plain ``TelemetryConfig`` kwargs instead of the config object so this
    module never imports ``yosoi.core.configs`` (which imports back into policy).
    """
    resolved = telemetry or TelemetryPolicy()
    return {
        'langfuse_public_key': resolved.langfuse_public_key_ref.resolve(env)
        if resolved.langfuse_public_key_ref is not None
        else None,
        'langfuse_secret_key': resolved.langfuse_secret_key_ref.resolve(env)
        if resolved.langfuse_secret_key_ref is not None
        else None,
        'langfuse_host': resolved.langfuse_host,
    }


def find_secret_ref(provider: str, env: Mapping[str, str] | None = None) -> SecretRef | None:
    """Return the first set provider credential ref, preserving env-name only."""
    from yosoi.core.discovery.config import _PROVIDER_ENV_VARS

    src = os.environ if env is None else env
    for env_var in _PROVIDER_ENV_VARS.get(provider, ()):
        if src.get(env_var):
            return SecretRef.env(env_var)
    return None
