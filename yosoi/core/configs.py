"""Structured configuration for Yosoi pipelines."""

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from yosoi.core.discovery import LLMConfig
from yosoi.core.discovery.config import _PROVIDER_ENV_VARS

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

    save_html: bool = True
    html_dir: Path = Field(default_factory=lambda: Path('.yosoi/debug_html'))


class TelemetryConfig(BaseModel):
    """Configuration for observability / telemetry."""

    logfire_token: str | None = None


class YosoiConfig(BaseModel):
    """Top-level Yosoi configuration bundling LLM, debug, and telemetry settings.

    Example::

        config = YosoiConfig(
            llm=ys.groq('llama-3.3-70b-versatile', api_key),
            debug=DebugConfig(save_html=False),
        )
        pipeline = Pipeline(config, contract=MyContract)

    """

    llm: LLMConfig
    debug: DebugConfig = Field(default_factory=DebugConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    logs: bool = True
    force: bool = False

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

        # Try the configured provider's env vars first
        val = _find_env_key(provider)
        if val:
            self.llm.api_key = val
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
            self.llm.provider = fb_provider
            self.llm.model_name = fb_model
            self.llm.api_key = fb_key
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
