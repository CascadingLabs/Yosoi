"""Structured configuration for Yosoi pipelines."""

import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from yosoi.core.discovery import LLMConfig

# Maps provider names to their expected env key
PROVIDER_ENV_KEYS: dict[str, str] = {
    'groq': 'GROQ_KEY',
    'gemini': 'GEMINI_KEY',
    'google': 'GEMINI_KEY',
    'openai': 'OPENAI_KEY',
    'gpt': 'OPENAI_KEY',
    'cerebras': 'CEREBRAS_KEY',
    'openrouter': 'OPENROUTER_KEY',
}


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

    @model_validator(mode='after')
    def validate_api_key_env(self) -> 'YosoiConfig':
        """Enforce environment variable presence for the selected provider.

        This ensures that when a provider is selected, the corresponding
        environment variable (API key) is available.
        """
        provider = self.llm.provider.lower()
        env_key = PROVIDER_ENV_KEYS.get(provider)

        if not self.llm.api_key:
            # If api_key is missing, try to get it from environment
            if env_key:
                val = os.getenv(env_key)
                if val:
                    self.llm.api_key = val
                else:
                    raise ValueError(f'Missing environment variable {env_key} for provider {provider!r}')
            else:
                available = ', '.join(PROVIDER_ENV_KEYS.keys())
                raise ValueError(f'Unknown provider {provider!r}. Available: {available}')

        return self
