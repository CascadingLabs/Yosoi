"""Modular LLM configuration system for Yosoi.

Supports multiple providers, easy extension, and flexible model configuration.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

# ============================================================================
# 1. CONFIG DATACLASSES - Simple configuration objects
# ============================================================================
from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.cerebras import CerebrasModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.cerebras import CerebrasProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider


class LLMConfig(BaseModel):
    """Base configuration for any LLM provider.

    Attributes:
        provider: Provider name ('groq', 'gemini', 'openai', etc.)
        model_name: Model identifier string
        api_key: API key for authentication
        temperature: Sampling temperature (0.0-2.0). Defaults to 0.01.
        max_tokens: Maximum tokens for generation. Defaults to None.
        extra_params: Additional provider-specific parameters. Defaults to None.

    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: str
    model_name: str
    api_key: str | None = None
    temperature: float = 0.01
    max_tokens: int | None = None
    extra_params: dict[str, Any] | None = None


# ============================================================================
# 2. PROVIDER PROTOCOL - For custom providers
# ============================================================================


class LLMProvider(Protocol):
    """Protocol that custom LLM providers must implement.

    Methods:
        create_model: Create a model instance from configuration
        create_agent: Create a configured agent from configuration

    """

    def create_model(self, config: LLMConfig) -> Model:
        """Create a model instance from configuration.

        Args:
            config: LLM configuration

        Returns:
            Model instance specific to the provider.

        """
        ...

    def create_agent(self, config: LLMConfig, system_prompt: str) -> Agent:
        """Create a configured agent from configuration.

        Args:
            config: LLM configuration
            system_prompt: System prompt for the agent

        Returns:
            Configured Pydantic AI Agent.

        """
        ...


# ============================================================================
# 3. BUILT-IN PROVIDERS - Factory functions for common providers
# ============================================================================


def _provider_kwargs(config: LLMConfig) -> dict[str, Any]:
    """Build keyword arguments for a provider constructor.

    Only includes api_key when explicitly set, allowing providers to fall back
    to their own environment variable resolution.
    """
    kwargs: dict[str, Any] = {}
    if config.api_key is not None:
        kwargs['api_key'] = config.api_key
    return kwargs


def create_cerebras_model(config: LLMConfig) -> CerebrasModel:
    """Create a Cerebras model from configuration.

    Args:
        config: LLM configuration with Cerebras settings

    Returns:
        Configured CerebrasModel instance.

    """
    provider = CerebrasProvider(**_provider_kwargs(config))
    return CerebrasModel(config.model_name, provider=provider)


def create_groq_model(config: LLMConfig) -> GroqModel:
    """Create a Groq model from configuration.

    Args:
        config: LLM configuration with Groq settings

    Returns:
        Configured GroqModel instance.

    """
    provider = GroqProvider(**_provider_kwargs(config))
    return GroqModel(config.model_name, provider=provider)


def create_gemini_model(config: LLMConfig) -> GoogleModel:
    """Create a Gemini (Google) model from configuration.

    Args:
        config: LLM configuration with Gemini settings

    Returns:
        Configured GoogleModel instance.

    """
    provider = GoogleProvider(**_provider_kwargs(config))
    return GoogleModel(config.model_name, provider=provider)


def create_openai_model(config: LLMConfig) -> OpenAIChatModel:
    """Create an OpenAI model from configuration.

    Args:
        config: LLM configuration with OpenAI settings

    Returns:
        Configured OpenAIChatModel instance.

    """
    provider = OpenAIProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=provider)


def create_openrouter_model(config: LLMConfig) -> OpenRouterModel:
    """Create an OpenRouter model from configuration.

    Uses the native pydantic-ai OpenRouterModel/OpenRouterProvider, giving
    access to hundreds of models from different providers via a single key.

    Args:
        config: LLM configuration with OpenRouter settings

    Returns:
        Configured OpenRouterModel instance.

    """
    provider = OpenRouterProvider(**_provider_kwargs(config))
    return OpenRouterModel(config.model_name, provider=provider)


# ============================================================================
# 4. MAIN FACTORY - Central creation point
# ============================================================================


PROVIDER_FACTORIES = {
    'groq': create_groq_model,
    'gemini': create_gemini_model,
    'google': create_gemini_model,  # Alias
    'openai': create_openai_model,
    'gpt': create_openai_model,  # Alias
    'cerebras': create_cerebras_model,
    'openrouter': create_openrouter_model,
}


def create_model(config: LLMConfig) -> Model:
    """Create a model from configuration.

    Args:
        config: LLMConfig specifying the provider and parameters

    Returns:
        Model instance (GroqModel, GoogleModel, OpenAIChatModel, etc.)

    Raises:
        ValueError: If provider is not supported

    Example:
        >>> config = LLMConfig(
        ...     provider='groq',
        ...     model_name='llama-3.3-70b-versatile',
        ...     api_key='your-key'
        ... )
        >>> model = create_model(config)

    """
    provider_name = config.provider.lower()

    if provider_name not in PROVIDER_FACTORIES:
        available = ', '.join(PROVIDER_FACTORIES.keys())
        raise ValueError(f'Unknown provider: {provider_name}. Available: {available}')

    factory = PROVIDER_FACTORIES[provider_name]
    return factory(config)


def create_agent(config: LLMConfig, system_prompt: str) -> Agent:
    """Create a Pydantic AI agent from configuration.

    Args:
        config: LLMConfig specifying the provider and parameters
        system_prompt: System prompt for the agent

    Returns:
        Configured Pydantic AI Agent

    Example:
        >>> config = LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='key')
        >>> agent = create_agent(config, 'You are a helpful assistant')

    """
    model = create_model(config)
    return Agent(model, system_prompt=system_prompt)


# ============================================================================
# 5. CONVENIENCE BUILDERS - Quick setup for common scenarios
# ============================================================================


class LLMBuilder:
    """Fluent builder for creating LLM configurations.

    Example:
        >>> config = (LLMBuilder()
        ...     .provider('groq')
        ...     .model('llama-3.3-70b-versatile')
        ...     .api_key('your-key')
        ...     .temperature(0.5)
        ...     .build())

    """

    def __init__(self) -> None:
        """Initialize the builder with default values."""
        self._provider: str | None = None
        self._model_name: str | None = None
        self._api_key: str | None = None
        self._temperature: float = 0.7
        self._max_tokens: int | None = None
        self._extra_params: dict[str, str | int | float | bool] = {}

    def provider(self, name: str) -> LLMBuilder:
        """Set the provider (groq, gemini, openai, etc.).

        Args:
            name: Provider name

        Returns:
            Self for method chaining.

        """
        self._provider = name
        return self

    def model(self, name: str) -> LLMBuilder:
        """Set the model name.

        Args:
            name: Model identifier

        Returns:
            Self for method chaining.

        """
        self._model_name = name
        return self

    def api_key(self, key: str) -> LLMBuilder:
        """Set the API key.

        Args:
            key: API key string

        Returns:
            Self for method chaining.

        """
        self._api_key = key
        return self

    def temperature(self, temp: float) -> LLMBuilder:
        """Set the temperature (0.0-2.0).

        Args:
            temp: Temperature value

        Returns:
            Self for method chaining.

        """
        self._temperature = temp
        return self

    def max_tokens(self, tokens: int) -> LLMBuilder:
        """Set max tokens for generation.

        Args:
            tokens: Maximum number of tokens

        Returns:
            Self for method chaining.

        """
        self._max_tokens = tokens
        return self

    def extra(self, **kwargs: str | int | float | bool) -> LLMBuilder:
        """Add extra provider-specific parameters.

        Args:
            **kwargs: Additional parameters

        Returns:
            Self for method chaining.

        """
        self._extra_params.update(kwargs)
        return self

    def build(self) -> LLMConfig:
        """Build the configuration.

        Returns:
            Configured LLMConfig instance.

        Raises:
            ValueError: If required fields (provider, model_name, api_key) are not set.

        """
        if not self._provider:
            raise ValueError('Provider must be set')
        if not self._model_name:
            raise ValueError('Model name must be set')
        return LLMConfig(
            provider=self._provider,
            model_name=self._model_name,
            api_key=_resolve_api_key(self._provider, self._api_key),
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            extra_params=self._extra_params if self._extra_params else None,
        )


_PROVIDER_ENV_VARS: dict[str, list[str]] = {
    'groq': ['GROQ_API_KEY', 'GROQ_KEY'],
    'gemini': ['GEMINI_API_KEY', 'GEMINI_KEY', 'GOOGLE_API_KEY'],
    'google': ['GEMINI_API_KEY', 'GEMINI_KEY', 'GOOGLE_API_KEY'],
    'openai': ['OPENAI_API_KEY', 'OPENAI_KEY'],
    'gpt': ['OPENAI_API_KEY', 'OPENAI_KEY'],
    'cerebras': ['CEREBRAS_API_KEY', 'CEREBRAS_KEY'],
    'openrouter': ['OPENROUTER_API_KEY', 'OPENROUTER_KEY'],
}


def _resolve_api_key(provider: str, api_key: str | None) -> str | None:
    """Resolve an API key from the explicit value or environment variables.

    Automatically loads a .env file (if present) before checking env vars.
    Checks the provider's known env var names (e.g. OPENROUTER_API_KEY,
    OPENROUTER_KEY) and returns the first one found. Returns None if nothing
    is available, letting the underlying provider attempt its own resolution.
    """
    if api_key is not None:
        return api_key
    from dotenv import load_dotenv

    load_dotenv()
    for env_var in _PROVIDER_ENV_VARS.get(provider, []):
        val = os.environ.get(env_var)
        if val:
            return val
    return None


def groq(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Groq.

    Args:
        model_name: Groq model identifier
        api_key: Groq API key. If omitted, reads from GROQ_API_KEY or GROQ_KEY env vars.
        **kwargs: Additional configuration options

    Returns:
        Configured LLMConfig for Groq.

    """
    return LLMConfig(provider='groq', model_name=model_name, api_key=_resolve_api_key('groq', api_key), **kwargs)


def gemini(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Gemini.

    Args:
        model_name: Gemini model identifier
        api_key: Google API key. If omitted, reads from GEMINI_API_KEY, GEMINI_KEY, or GOOGLE_API_KEY env vars.
        **kwargs: Additional configuration options

    Returns:
        Configured LLMConfig for Gemini.

    """
    return LLMConfig(provider='gemini', model_name=model_name, api_key=_resolve_api_key('gemini', api_key), **kwargs)


def cerebras(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Cerebras.

    Args:
        model_name: Cerebras model identifier (e.g. 'llama-3.3-70b')
        api_key: Cerebras API key. If omitted, reads from CEREBRAS_API_KEY or CEREBRAS_KEY env vars.
        **kwargs: Additional configuration options

    Returns:
        Configured LLMConfig for Cerebras.

    """
    return LLMConfig(
        provider='cerebras', model_name=model_name, api_key=_resolve_api_key('cerebras', api_key), **kwargs
    )


def openai(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for OpenAI.

    Args:
        model_name: OpenAI model identifier
        api_key: OpenAI API key. If omitted, reads from OPENAI_API_KEY or OPENAI_KEY env vars.
        **kwargs: Additional configuration options

    Returns:
        Configured LLMConfig for OpenAI.

    """
    return LLMConfig(provider='openai', model_name=model_name, api_key=_resolve_api_key('openai', api_key), **kwargs)


def openrouter(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for OpenRouter.

    Args:
        model_name: OpenRouter model identifier (e.g. 'stepfun/step-3.5-flash:free')
        api_key: OpenRouter API key. If omitted, reads from OPENROUTER_API_KEY or OPENROUTER_KEY env vars.
        **kwargs: Additional configuration options

    Returns:
        Configured LLMConfig for OpenRouter.

    """
    return LLMConfig(
        provider='openrouter', model_name=model_name, api_key=_resolve_api_key('openrouter', api_key), **kwargs
    )


# ============================================================================
# 6. UNIFIED PROVIDER FUNCTION - Magic model string parsing
# ============================================================================

# Canonical provider names recognised by `provider()`.  Aliases (google, gpt)
# are included so that `ys.provider("gpt:gpt-4o")` works.
_KNOWN_PROVIDERS: set[str] = set(PROVIDER_FACTORIES.keys())


def _parse_model_string(model_string: str) -> tuple[str, str]:
    """Split a model string into (provider, model_name).

    Supports two formats (checked in order):

    1. **Colon format** (preferred): ``provider:model-name``
       e.g. ``groq:llama-3.3-70b-versatile``,
       ``openrouter:meta-llama/llama-3.3-70b-instruct:free``
    2. **Slash format** (legacy / CLI compat): ``provider/model-name``
       Only when the first segment is a known provider name.

    The colon format is unambiguous even for OpenRouter models whose names
    contain slashes.

    Returns:
        Tuple of (provider, model_name).

    Raises:
        ValueError: When no provider can be determined.
    """
    # 1. Try colon format — split on FIRST colon only
    if ':' in model_string:
        first, rest = model_string.split(':', 1)
        if first.lower() in _KNOWN_PROVIDERS:
            return first.lower(), rest

    # 2. Try slash format — only if the first segment is a known provider
    if '/' in model_string:
        first, rest = model_string.split('/', 1)
        if first.lower() in _KNOWN_PROVIDERS:
            return first.lower(), rest

    # Neither format matched
    raise ValueError(
        f'Cannot determine provider from {model_string!r}. '
        f"Use 'provider:model-name' format, e.g. 'groq:{model_string}'. "
        f'Known providers: {", ".join(sorted(_KNOWN_PROVIDERS - {"google", "gpt"}))}'
    )


def provider(model_string: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Create an LLM config from a single model string.

    This is the recommended, unified way to configure a model.  The provider is
    parsed from the model string automatically.

    Preferred format uses ``:`` as the separator::

        import yosoi as ys

        config = ys.provider('groq:llama-3.3-70b-versatile')
        config = ys.provider('openrouter:meta-llama/llama-3.3-70b-instruct:free')
        config = ys.provider('gemini:gemini-2.0-flash')

    The ``provider/model`` format is also supported for known providers::

        config = ys.provider('groq/llama-3.3-70b-versatile')

    Args:
        model_string: Model identifier in ``provider:model-name`` format.
        api_key: Explicit API key. If omitted, resolved from environment.
        **kwargs: Additional LLMConfig fields (temperature, max_tokens, etc.)

    Returns:
        Configured LLMConfig instance.

    Raises:
        ValueError: If the provider cannot be determined.

    """
    prov, model_name = _parse_model_string(model_string)
    return LLMConfig(
        provider=prov,
        model_name=model_name,
        api_key=_resolve_api_key(prov, api_key),
        **kwargs,
    )


# ============================================================================
# 7. EXAMPLES & USAGE
# ============================================================================

if __name__ == '__main__':
    import os

    from dotenv import load_dotenv

    load_dotenv()

    # Example 1: Simple configuration
    print('Example 1: Simple Config')
    config = LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key=os.getenv('GROQ_KEY', 'test-key'))
    print(f'  Config: {config.provider} / {config.model_name}')

    # Example 2: Using builder
    print('\nExample 2: Fluent Builder')
    config2 = (
        LLMBuilder()
        .provider('gemini')
        .model('gemini-2.0-flash')
        .api_key(os.getenv('GEMINI_KEY', 'test-key'))
        .temperature(0.5)
        .build()
    )
    print(f'  Config: {config2.provider} / {config2.model_name}')

    # Example 3: Quick helpers
    print('\nExample 3: Quick Helpers')
    config3 = groq('llama-3.3-70b-versatile', os.getenv('GROQ_KEY', 'test-key'))
    print(f'  Config: {config3.provider} / {config3.model_name}')

    print('\n✓ All examples completed')
