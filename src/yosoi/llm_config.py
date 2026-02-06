"""
llm_config.py
=============
Modular LLM configuration system for Yosoi.

Supports multiple providers, easy extension, and flexible model configuration.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.providers.openai import OpenAIProvider

# ============================================================================
# 1. CONFIG DATACLASSES - Simple configuration objects
# ============================================================================


@dataclass
class LLMConfig:
    """Base configuration for any LLM provider.

    Attributes:
        provider: Provider name ('groq', 'gemini', 'openai', etc.)
        model_name: Model identifier string
        api_key: API key for authentication
        temperature: Sampling temperature (0.0-2.0). Defaults to 0.7.
        max_tokens: Maximum tokens for generation. Defaults to None.
        extra_params: Additional provider-specific parameters. Defaults to None.
    """

    provider: str
    model_name: str
    api_key: str
    temperature: float = 0.7
    max_tokens: int | None = None
    extra_params: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization.

        Raises:
            ValueError: If API key or model name is missing.
        """
        if not self.api_key:
            raise ValueError(f'API key required for {self.provider}')
        if not self.model_name:
            raise ValueError(f'Model name required for {self.provider}')


@dataclass
class FallbackConfig:
    """Configuration for fallback LLM chain.

    Attributes:
        primary: Primary LLM configuration
        fallbacks: List of fallback LLM configurations
        max_retries_per_model: Maximum retry attempts per model. Defaults to 2.
    """

    primary: LLMConfig
    fallbacks: list[LLMConfig]
    max_retries_per_model: int = 2


# ============================================================================
# 2. PROVIDER PROTOCOL - For custom providers
# ============================================================================


class LLMProvider(Protocol):
    """Protocol that custom LLM providers must implement.

    Methods:
        create_model: Create a model instance from configuration
        create_agent: Create a configured agent from configuration
    """

    def create_model(self, config: LLMConfig) -> Any:
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


def create_groq_model(config: LLMConfig) -> GroqModel:
    """Create a Groq model from configuration.

    Args:
        config: LLM configuration with Groq settings

    Returns:
        Configured GroqModel instance.
    """
    provider = GroqProvider(api_key=config.api_key)

    # Merge extra params if provided
    model_params = {}
    if config.temperature is not None:
        model_params['temperature'] = config.temperature
    if config.extra_params:
        model_params.update(config.extra_params)

    return GroqModel(config.model_name, provider=provider)


def create_gemini_model(config: LLMConfig) -> GoogleModel:
    """Create a Gemini (Google) model from configuration.

    Args:
        config: LLM configuration with Gemini settings

    Returns:
        Configured GoogleModel instance.
    """
    provider = GoogleProvider(api_key=config.api_key)

    model_params = {}
    if config.temperature is not None:
        model_params['temperature'] = config.temperature
    if config.extra_params:
        model_params.update(config.extra_params)

    return GoogleModel(config.model_name, provider=provider)


def create_openai_model(config: LLMConfig) -> OpenAIModel:
    """Create an OpenAI model from configuration.

    Args:
        config: LLM configuration with OpenAI settings

    Returns:
        Configured OpenAIModel instance.
    """
    provider = OpenAIProvider(api_key=config.api_key)

    model_params = {}
    if config.temperature is not None:
        model_params['temperature'] = config.temperature
    if config.max_tokens:
        model_params['max_tokens'] = config.max_tokens
    if config.extra_params:
        model_params.update(config.extra_params)

    return OpenAIModel(config.model_name, provider=provider)


# ============================================================================
# 4. MAIN FACTORY - Central creation point
# ============================================================================


PROVIDER_FACTORIES = {
    'groq': create_groq_model,
    'gemini': create_gemini_model,
    'google': create_gemini_model,  # Alias
    'openai': create_openai_model,
    'gpt': create_openai_model,  # Alias
}


def create_model(config: LLMConfig) -> Any:
    """
    Create a model from configuration.

    Args:
        config: LLMConfig specifying the provider and parameters

    Returns:
        Model instance (GroqModel, GoogleModel, OpenAIModel, etc.)

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
    """
    Create a Pydantic AI agent from configuration.

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

    def __init__(self):
        """Initialize the builder with default values."""
        self._provider: str | None = None
        self._model_name: str | None = None
        self._api_key: str | None = None
        self._temperature: float = 0.7
        self._max_tokens: int | None = None
        self._extra_params: dict[str, Any] = {}

    def provider(self, name: str) -> 'LLMBuilder':
        """Set the provider (groq, gemini, openai, etc.).

        Args:
            name: Provider name

        Returns:
            Self for method chaining.
        """
        self._provider = name
        return self

    def model(self, name: str) -> 'LLMBuilder':
        """Set the model name.

        Args:
            name: Model identifier

        Returns:
            Self for method chaining.
        """
        self._model_name = name
        return self

    def api_key(self, key: str) -> 'LLMBuilder':
        """Set the API key.

        Args:
            key: API key string

        Returns:
            Self for method chaining.
        """
        self._api_key = key
        return self

    def temperature(self, temp: float) -> 'LLMBuilder':
        """Set the temperature (0.0-2.0).

        Args:
            temp: Temperature value

        Returns:
            Self for method chaining.
        """
        self._temperature = temp
        return self

    def max_tokens(self, tokens: int) -> 'LLMBuilder':
        """Set max tokens for generation.

        Args:
            tokens: Maximum number of tokens

        Returns:
            Self for method chaining.
        """
        self._max_tokens = tokens
        return self

    def extra(self, **kwargs) -> 'LLMBuilder':
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
        if not self._api_key:
            raise ValueError('API key must be set')

        return LLMConfig(
            provider=self._provider,
            model_name=self._model_name,
            api_key=self._api_key,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            extra_params=self._extra_params if self._extra_params else None,
        )


def groq(model_name: str, api_key: str, **kwargs) -> LLMConfig:
    """Quick config for Groq.

    Args:
        model_name: Groq model identifier
        api_key: Groq API key
        **kwargs: Additional configuration options

    Returns:
        Configured LLMConfig for Groq.
    """
    return LLMConfig(provider='groq', model_name=model_name, api_key=api_key, **kwargs)


def gemini(model_name: str, api_key: str, **kwargs) -> LLMConfig:
    """Quick config for Gemini.

    Args:
        model_name: Gemini model identifier
        api_key: Google API key
        **kwargs: Additional configuration options

    Returns:
        Configured LLMConfig for Gemini.
    """
    return LLMConfig(provider='gemini', model_name=model_name, api_key=api_key, **kwargs)


def openai(model_name: str, api_key: str, **kwargs) -> LLMConfig:
    """Quick config for OpenAI.

    Args:
        model_name: OpenAI model identifier
        api_key: OpenAI API key
        **kwargs: Additional configuration options

    Returns:
        Configured LLMConfig for OpenAI.
    """
    return LLMConfig(provider='openai', model_name=model_name, api_key=api_key, **kwargs)


# ============================================================================
# 6. MULTI-MODEL SUPPORT - Fallback chains and comparison
# ============================================================================


class MultiModelAgent:
    """Agent that can use multiple models with fallback.

    Attributes:
        configs: List of LLM configurations in priority order
        system_prompt: System prompt used for all agents
        agents: List of configured Pydantic AI agents
    """

    def __init__(self, configs: list[LLMConfig], system_prompt: str):
        """Initialize with multiple model configurations.

        Args:
            configs: List of LLMConfig objects in priority order
            system_prompt: System prompt for all agents
        """
        self.configs = configs
        self.system_prompt = system_prompt
        self.agents = [create_agent(config, system_prompt) for config in configs]

    def run_with_fallback(self, prompt: str, max_retries: int = 1) -> tuple[Any, str]:
        """Run prompt with fallback to next model on failure.

        Args:
            prompt: Prompt to send to the model
            max_retries: Maximum retry attempts per model. Defaults to 1.

        Returns:
            Tuple of (result, model_id) where model_id is in format 'provider:model_name'.

        Raises:
            RuntimeError: If all models fail to process the prompt.
        """
        for i, agent in enumerate(self.agents):
            config = self.configs[i]
            for attempt in range(max_retries):
                try:
                    result = agent.run_sync(prompt)
                    model_id = f'{config.provider}:{config.model_name}'
                    return result, model_id
                except Exception as e:
                    if attempt < max_retries - 1:
                        continue
                    # Last retry for this model failed
                    if i < len(self.agents) - 1:
                        # Try next model
                        break
                    # Last model also failed
                    raise RuntimeError(f'All models failed. Last error: {e}') from e

        raise RuntimeError('All models exhausted without success')

    def run_all_compare(self, prompt: str) -> dict[str, Any]:
        """Run prompt on all models and return all results for comparison.

        Args:
            prompt: Prompt to send to all models

        Returns:
            Dictionary mapping model_id to result or error.
            Model IDs are in format 'provider:model_name'.
        """
        results: dict[str, Any] = {}
        for config, agent in zip(self.configs, self.agents, strict=True):
            model_id = f'{config.provider}:{config.model_name}'
            try:
                result = agent.run_sync(prompt)
                results[model_id] = result
            except Exception as e:
                results[model_id] = {'error': str(e)}

        return results


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
        .model('gemini-2.0-flash-exp')
        .api_key(os.getenv('GEMINI_KEY', 'test-key'))
        .temperature(0.5)
        .build()
    )
    print(f'  Config: {config2.provider} / {config2.model_name}')

    # Example 3: Quick helpers
    print('\nExample 3: Quick Helpers')
    config3 = groq('llama-3.3-70b-versatile', os.getenv('GROQ_KEY', 'test-key'))
    print(f'  Config: {config3.provider} / {config3.model_name}')

    # Example 4: Multi-model with fallback
    print('\nExample 4: Multi-Model Fallback')
    configs = [
        groq('llama-3.3-70b-versatile', os.getenv('GROQ_KEY', 'test-key')),
        gemini('gemini-2.0-flash-exp', os.getenv('GEMINI_KEY', 'test-key')),
    ]
    print(f'  Primary: {configs[0].provider}')
    print(f'  Fallback: {configs[1].provider}')

    print('\n✓ All examples completed')
