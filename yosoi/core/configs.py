"""Structured configuration for Yosoi pipelines."""

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from yosoi.core.discovery import LLMConfig
from yosoi.core.discovery.config import _PROVIDER_ENV_VARS, NO_API_KEY_REQUIRED_PROVIDERS, _parse_model_string

log = logging.getLogger(__name__)

# Preferred fallback order with default model names per provider.
# Aliases (google, gpt) are excluded — only canonical names here.
PROVIDER_FALLBACK_ORDER: list[tuple[str, str]] = [
    ('groq', 'llama-3.3-70b-versatile'),
    ('gemini', 'gemini-2.0-flash'),
    ('cerebras', 'llama-3.3-70b'),
    ('openai', 'gpt-4o-mini'),
    ('openrouter', 'meta-llama/llama-3.3-70b-instruct:free'),
]


def _find_env_key(provider: str) -> str | None:
    """Try all known env var names for a provider, return the first found value."""
    for env_var in _PROVIDER_ENV_VARS.get(provider, []):
        val = os.getenv(env_var)
        if val:
            return val
    return None


def find_available_provider() -> tuple[str, str, str] | None:
    """Find the first provider with an available API key.

    Returns:
        Tuple of (provider, model_name, api_key) or None if nothing found.
    """
    for provider, default_model in PROVIDER_FALLBACK_ORDER:
        val = _find_env_key(provider)
        if val:
            return provider, default_model, val
    return None


class DebugConfig(BaseModel):
    """Configuration for debug output."""

    save_html: bool = False
    html_dir: Path = Field(default_factory=lambda: Path('.yosoi/debug_html'))


class TelemetryConfig(BaseModel):
    """Configuration for observability / telemetry.

    Langfuse is enabled when both ``langfuse_public_key`` and
    ``langfuse_secret_key`` are set. ``langfuse_host`` is optional and
    defaults to Langfuse Cloud.
    """

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None


class DiscoveryConfig(BaseModel):
    """Configuration for the per-URL field-discovery fan-out.

    Caps how many per-field LLM calls run concurrently inside one URL via
    ``asyncio.gather`` + ``asyncio.Semaphore``. Increase for higher throughput
    on small contracts; decrease if you're hitting LLM rate limits or want
    more deterministic ordering.
    """

    max_concurrent: int = Field(default=5, ge=1, le=50)


class YosoiConfig(BaseModel):
    """Top-level Yosoi configuration bundling LLM, debug, telemetry, and discovery settings.

    Example::

        config = YosoiConfig(
            llm=ys.groq('llama-3.3-70b-versatile', api_key),
            debug=DebugConfig(save_html=False),
            discovery=DiscoveryConfig(max_concurrent=3),
        )
        pipeline = Pipeline(config, contract=MyContract)

    """

    llm: LLMConfig
    debug: DebugConfig = Field(default_factory=DebugConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    logs: bool = True
    force: bool = False
    use_experimental_preprocess: bool = Field(
        default=False,
        description=(
            'Enable spike CAS-18 page-level preprocessor (tier-1 + tier-2 transforms) '
            'after the existing HTMLCleaner. Off by default; tracked under the spike.'
        ),
    )

    @model_validator(mode='after')
    def validate_api_key_env(self) -> 'YosoiConfig':
        """Resolve API key for the selected provider, falling back to others if needed.

        Resolution order:
        1. Use api_key if already set on the LLMConfig.
        2. Try the environment variable for the selected provider.
        3. Walk PROVIDER_FALLBACK_ORDER and use the first provider with a key.
        4. Raise if nothing works.
        """
        if self.llm.api_key:
            return self

        provider = self.llm.provider.lower()

        if provider not in _PROVIDER_ENV_VARS:
            available = ', '.join(_PROVIDER_ENV_VARS.keys())
            raise ValueError(f'Unknown provider {provider!r}. Available: {available}')

        # Providers like ollama (local) and vertexai (GCP auth) need no API key.
        if provider in NO_API_KEY_REQUIRED_PROVIDERS:
            return self

        # Try the configured provider's env vars first
        val = _find_env_key(provider)
        if val:
            self.llm = self.llm.model_copy(update={'api_key': val})
            return self

        # Fallback: try other providers
        fallback = find_available_provider()
        if fallback:
            fb_provider, fb_model, fb_key = fallback
            env_names = _PROVIDER_ENV_VARS.get(provider, [])
            log.warning(
                'No %s found for provider %r — falling back to %r (%s)',
                '/'.join(env_names),
                provider,
                fb_provider,
                fb_model,
            )
            self.llm = self.llm.model_copy(update={'provider': fb_provider, 'model_name': fb_model, 'api_key': fb_key})
            return self

        # Nothing available at all
        all_vars: list[str] = []
        seen: set[str] = set()
        for vars_list in _PROVIDER_ENV_VARS.values():
            for v in vars_list:
                if v not in seen:
                    all_vars.append(v)
                    seen.add(v)
        raise ValueError(f'No API key found. Set one of: {", ".join(all_vars)}')


def auto_config(model: str | None = None, debug: bool = False) -> YosoiConfig:
    """Auto-detect LLM provider and build config.

    Resolution order:
    1. Explicit ``model`` argument (``provider:model-name`` format)
    2. ``$YOSOI_MODEL`` environment variable
    3. First provider with an available API key
    4. Groq default fallback

    Args:
        model: Model string in ``provider:model-name`` format, or None.
        debug: Whether to enable debug HTML saving.

    Returns:
        Validated YosoiConfig.

    Raises:
        ValueError: On configuration errors (bad model format, no API key, etc.).

    """
    from dotenv import load_dotenv

    load_dotenv()

    if model:
        prov, model_name = _parse_model_string(model)
        llm_config = LLMConfig(provider=prov, model_name=model_name, api_key='')
    elif yosoi_model := os.getenv('YOSOI_MODEL'):
        prov, model_name = _parse_model_string(yosoi_model)
        llm_config = LLMConfig(provider=prov, model_name=model_name, api_key='')
    else:
        found = find_available_provider()
        if found:
            provider, model_name, _ = found
            llm_config = LLMConfig(provider=provider, model_name=model_name, api_key='')
        else:
            raise ValueError(
                'No model specified and no API key found. '
                'Pass a model string (e.g. auto_config(model="groq:llama-3.3-70b-versatile")) '
                'or set an API key environment variable.'
            )

    return YosoiConfig(
        llm=llm_config,
        debug=DebugConfig(save_html=debug),
        telemetry=TelemetryConfig(
            langfuse_public_key=os.getenv('LANGFUSE_PUBLIC_KEY'),
            langfuse_secret_key=os.getenv('LANGFUSE_SECRET_KEY'),
            langfuse_host=os.getenv('LANGFUSE_BASE_URL') or os.getenv('LANGFUSE_HOST'),
        ),
    )
