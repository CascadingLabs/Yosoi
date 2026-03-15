"""Modular LLM configuration system for Yosoi.

Supports multiple providers, easy extension, and flexible model configuration.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable
from typing import Any, Protocol

# ============================================================================
# 1. CONFIG DATACLASSES - Simple configuration objects
# ============================================================================
from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.models.cerebras import CerebrasModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.huggingface import HuggingFaceModel
from pydantic_ai.models.mistral import MistralModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.models.xai import XaiModel
from pydantic_ai.providers.alibaba import AlibabaProvider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai.providers.cerebras import CerebrasProvider
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.fireworks import FireworksProvider
from pydantic_ai.providers.github import GitHubProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.google_vertex import GoogleVertexProvider
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.providers.heroku import HerokuProvider
from pydantic_ai.providers.huggingface import HuggingFaceProvider
from pydantic_ai.providers.litellm import LiteLLMProvider
from pydantic_ai.providers.mistral import MistralProvider
from pydantic_ai.providers.moonshotai import MoonshotAIProvider
from pydantic_ai.providers.nebius import NebiusProvider
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.providers.ovhcloud import OVHcloudProvider
from pydantic_ai.providers.sambanova import SambaNovaProvider
from pydantic_ai.providers.together import TogetherProvider
from pydantic_ai.providers.vercel import VercelProvider
from pydantic_ai.providers.xai import XaiProvider


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

# Providers that don't require an API key (local or GCP auth-based).
NO_API_KEY_REQUIRED_PROVIDERS: frozenset[str] = frozenset({'ollama', 'vertexai', 'google-vertex'})


def _provider_kwargs(config: LLMConfig) -> dict[str, Any]:
    """Build keyword arguments for a provider constructor.

    Only includes api_key when explicitly set, allowing providers to fall back
    to their own environment variable resolution.
    """
    kwargs: dict[str, Any] = {}
    if config.api_key is not None:
        kwargs['api_key'] = config.api_key
    return kwargs


# --- First-class model providers ---


def create_anthropic_model(config: LLMConfig) -> AnthropicModel:
    """Create an Anthropic model from configuration."""
    prov = AnthropicProvider(**_provider_kwargs(config))
    return AnthropicModel(config.model_name, provider=prov)


def create_cerebras_model(config: LLMConfig) -> CerebrasModel:
    """Create a Cerebras model from configuration."""
    prov = CerebrasProvider(**_provider_kwargs(config))
    return CerebrasModel(config.model_name, provider=prov)


def create_groq_model(config: LLMConfig) -> GroqModel:
    """Create a Groq model from configuration."""
    prov = GroqProvider(**_provider_kwargs(config))
    return GroqModel(config.model_name, provider=prov)


def create_gemini_model(config: LLMConfig) -> GoogleModel:
    """Create a Gemini (Google) model from configuration."""
    prov = GoogleProvider(**_provider_kwargs(config))
    return GoogleModel(config.model_name, provider=prov)


def create_mistral_model(config: LLMConfig) -> MistralModel:
    """Create a Mistral model from configuration."""
    prov = MistralProvider(**_provider_kwargs(config))
    return MistralModel(config.model_name, provider=prov)


def create_huggingface_model(config: LLMConfig) -> HuggingFaceModel:
    """Create a HuggingFace model from configuration.

    Set ``provider_name`` in ``extra_params`` to route to a specific
    inference provider (e.g. ``'nebius'``, ``'together'``, ``'cerebras'``).
    """
    kwargs = _provider_kwargs(config)
    if config.extra_params and 'provider_name' in config.extra_params:
        kwargs['provider_name'] = config.extra_params['provider_name']
    prov = HuggingFaceProvider(**kwargs)
    return HuggingFaceModel(config.model_name, provider=prov)


def create_xai_model(config: LLMConfig) -> XaiModel:
    """Create an xAI model from configuration."""
    prov = XaiProvider(**_provider_kwargs(config))
    return XaiModel(config.model_name, provider=prov)


def create_bedrock_model(config: LLMConfig) -> BedrockConverseModel:
    """Create an AWS Bedrock model from configuration.

    ``api_key`` is treated as ``aws_access_key_id``. Supply
    ``aws_secret_access_key``, ``aws_session_token``, and ``region_name``
    via ``extra_params`` or let boto3 resolve credentials from environment.
    """
    kwargs: dict[str, Any] = {}
    if config.api_key is not None:
        kwargs['aws_access_key_id'] = config.api_key
    for field in ('aws_secret_access_key', 'aws_session_token', 'region_name', 'profile_name'):
        if config.extra_params and field in config.extra_params:
            kwargs[field] = config.extra_params[field]
    prov = BedrockProvider(**kwargs)
    return BedrockConverseModel(config.model_name, provider=prov)


def create_vertexai_model(config: LLMConfig) -> GoogleModel:
    """Create a Google Vertex AI model from configuration.

    Uses application default credentials (``GOOGLE_APPLICATION_CREDENTIALS``)
    or supply ``service_account_file``, ``project_id``, ``region`` via
    ``extra_params``.

    .. deprecated::
        ``GoogleVertexProvider`` is deprecated by pydantic-ai. This provider
        continues to work but may be removed in a future release. Watch
        https://ai.pydantic.dev/models/google/ for the replacement API.
    """
    warnings.warn(
        "The 'vertexai'/'google-vertex' provider uses GoogleVertexProvider which is deprecated "
        'by pydantic-ai. It still works, but watch https://ai.pydantic.dev/models/google/ '
        'for the official replacement.',
        DeprecationWarning,
        stacklevel=3,
    )
    kwargs: dict[str, Any] = {}
    for field in ('service_account_file', 'project_id', 'region'):
        if config.extra_params and field in config.extra_params:
            kwargs[field] = config.extra_params[field]
    prov = GoogleVertexProvider(**kwargs)
    return GoogleModel(config.model_name, provider=prov)  # type: ignore[arg-type]


# --- OpenAI-compatible providers ---


def create_openai_model(config: LLMConfig) -> OpenAIChatModel:
    """Create an OpenAI model from configuration."""
    prov = OpenAIProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_openrouter_model(config: LLMConfig) -> OpenRouterModel:
    """Create an OpenRouter model from configuration."""
    prov = OpenRouterProvider(**_provider_kwargs(config))
    return OpenRouterModel(config.model_name, provider=prov)


def create_azure_model(config: LLMConfig) -> OpenAIChatModel:
    """Create an Azure OpenAI model from configuration.

    Supply ``azure_endpoint`` and optionally ``api_version`` via
    ``extra_params``.
    """
    kwargs = _provider_kwargs(config)
    for field in ('azure_endpoint', 'api_version'):
        if config.extra_params and field in config.extra_params:
            kwargs[field] = config.extra_params[field]
    prov = AzureProvider(**kwargs)
    return OpenAIChatModel(config.model_name, provider=prov)


def create_deepseek_model(config: LLMConfig) -> OpenAIChatModel:
    """Create a DeepSeek model from configuration."""
    prov = DeepSeekProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_ollama_model(config: LLMConfig) -> OpenAIChatModel:
    """Create an Ollama model from configuration.

    Ollama runs locally; no API key is required. Supply ``base_url``
    via ``extra_params`` to override the default ``http://localhost:11434``.
    """
    kwargs: dict[str, Any] = {}
    if config.extra_params and 'base_url' in config.extra_params:
        kwargs['base_url'] = config.extra_params['base_url']
    prov = OllamaProvider(**kwargs)
    return OpenAIChatModel(config.model_name, provider=prov)


def create_fireworks_model(config: LLMConfig) -> OpenAIChatModel:
    """Create a Fireworks AI model from configuration."""
    prov = FireworksProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_together_model(config: LLMConfig) -> OpenAIChatModel:
    """Create a Together AI model from configuration."""
    prov = TogetherProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_nebius_model(config: LLMConfig) -> OpenAIChatModel:
    """Create a Nebius model from configuration."""
    prov = NebiusProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_moonshotai_model(config: LLMConfig) -> OpenAIChatModel:
    """Create a MoonshotAI (Kimi) model from configuration."""
    prov = MoonshotAIProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_grok_model(config: LLMConfig) -> XaiModel:
    """Create a Grok model via the native xAI SDK (alias for xai).

    .. deprecated::
        The ``grok`` provider name is deprecated. Use ``xai`` instead:
        ``ys.provider('xai:grok-3')``.
    """
    warnings.warn(
        "Provider 'grok' is deprecated. Use 'xai' instead: ys.provider('xai:grok-3').",
        DeprecationWarning,
        stacklevel=3,
    )
    return create_xai_model(config)


def create_alibaba_model(config: LLMConfig) -> OpenAIChatModel:
    """Create an Alibaba Cloud (DashScope) model from configuration."""
    prov = AlibabaProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_sambanova_model(config: LLMConfig) -> OpenAIChatModel:
    """Create a SambaNova model from configuration."""
    prov = SambaNovaProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_ovhcloud_model(config: LLMConfig) -> OpenAIChatModel:
    """Create an OVHcloud AI model from configuration."""
    prov = OVHcloudProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_github_model(config: LLMConfig) -> OpenAIChatModel:
    """Create a GitHub Models model from configuration."""
    prov = GitHubProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_vercel_model(config: LLMConfig) -> OpenAIChatModel:
    """Create a Vercel AI model from configuration."""
    prov = VercelProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_heroku_model(config: LLMConfig) -> OpenAIChatModel:
    """Create a Heroku inference model from configuration."""
    prov = HerokuProvider(**_provider_kwargs(config))
    return OpenAIChatModel(config.model_name, provider=prov)


def create_litellm_model(config: LLMConfig) -> OpenAIChatModel:
    """Create a LiteLLM-proxied model from configuration.

    Supply ``api_base`` via ``extra_params`` to point at your LiteLLM proxy.
    """
    kwargs = _provider_kwargs(config)
    if config.extra_params and 'api_base' in config.extra_params:
        kwargs['api_base'] = config.extra_params['api_base']
    prov = LiteLLMProvider(**kwargs)
    return OpenAIChatModel(config.model_name, provider=prov)


# ============================================================================
# 4. MAIN FACTORY - Central creation point
# ============================================================================


PROVIDER_FACTORIES: dict[str, Callable[[LLMConfig], Model]] = {
    # First-class model providers
    'anthropic': create_anthropic_model,
    'claude': create_anthropic_model,  # alias
    'groq': create_groq_model,
    'gemini': create_gemini_model,
    'google': create_gemini_model,  # alias
    'mistral': create_mistral_model,
    'cerebras': create_cerebras_model,
    'huggingface': create_huggingface_model,
    'hf': create_huggingface_model,  # alias
    'xai': create_xai_model,
    'bedrock': create_bedrock_model,
    'aws': create_bedrock_model,  # alias
    'vertexai': create_vertexai_model,
    'google-vertex': create_vertexai_model,  # alias
    # OpenAI-compatible providers
    'openai': create_openai_model,
    'gpt': create_openai_model,  # alias
    'openrouter': create_openrouter_model,
    'azure': create_azure_model,
    'deepseek': create_deepseek_model,
    'ollama': create_ollama_model,
    'fireworks': create_fireworks_model,
    'together': create_together_model,
    'nebius': create_nebius_model,
    'moonshotai': create_moonshotai_model,
    'moonshot': create_moonshotai_model,  # alias
    'grok': create_grok_model,
    'alibaba': create_alibaba_model,
    'dashscope': create_alibaba_model,  # alias
    'sambanova': create_sambanova_model,
    'ovhcloud': create_ovhcloud_model,
    'ovh': create_ovhcloud_model,  # alias
    'github': create_github_model,
    'vercel': create_vercel_model,
    'heroku': create_heroku_model,
    'litellm': create_litellm_model,
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
        available = ', '.join(sorted(PROVIDER_FACTORIES.keys()))
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
            ValueError: If required fields (provider, model_name) are not set.

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
    # First-class providers
    'anthropic': ['ANTHROPIC_API_KEY'],
    'claude': ['ANTHROPIC_API_KEY'],
    'groq': ['GROQ_API_KEY', 'GROQ_KEY'],
    'gemini': ['GEMINI_API_KEY', 'GEMINI_KEY', 'GOOGLE_API_KEY'],
    'google': ['GEMINI_API_KEY', 'GEMINI_KEY', 'GOOGLE_API_KEY'],
    'mistral': ['MISTRAL_API_KEY', 'MISTRAL_KEY'],
    'cerebras': ['CEREBRAS_API_KEY', 'CEREBRAS_KEY'],
    'huggingface': ['HF_TOKEN', 'HUGGINGFACE_API_KEY'],
    'hf': ['HF_TOKEN', 'HUGGINGFACE_API_KEY'],
    'xai': ['XAI_API_KEY'],
    'bedrock': ['AWS_ACCESS_KEY_ID'],
    'aws': ['AWS_ACCESS_KEY_ID'],
    # Vertex AI uses GCP application default credentials — no API key.
    'vertexai': [],
    'google-vertex': [],
    # OpenAI-compatible providers
    'openai': ['OPENAI_API_KEY', 'OPENAI_KEY'],
    'gpt': ['OPENAI_API_KEY', 'OPENAI_KEY'],
    'openrouter': ['OPENROUTER_API_KEY', 'OPENROUTER_KEY'],
    'azure': ['AZURE_OPENAI_API_KEY'],
    'deepseek': ['DEEPSEEK_API_KEY'],
    # Ollama is local — no API key required.
    'ollama': [],
    'fireworks': ['FIREWORKS_API_KEY'],
    'together': ['TOGETHER_API_KEY'],
    'nebius': ['NEBIUS_API_KEY'],
    'moonshotai': ['MOONSHOT_API_KEY'],
    'moonshot': ['MOONSHOT_API_KEY'],
    'grok': ['XAI_API_KEY', 'GROK_API_KEY'],
    'alibaba': ['DASHSCOPE_API_KEY', 'ALIBABA_API_KEY'],
    'dashscope': ['DASHSCOPE_API_KEY', 'ALIBABA_API_KEY'],
    'sambanova': ['SAMBANOVA_API_KEY'],
    'ovhcloud': ['OVH_AI_ENDPOINTS_ACCESS_TOKEN'],
    'ovh': ['OVH_AI_ENDPOINTS_ACCESS_TOKEN'],
    'github': ['GITHUB_TOKEN'],
    'vercel': ['AI_SDK_KEY', 'VERCEL_API_KEY'],
    'heroku': ['HEROKU_INFERENCE_KEY'],
    'litellm': ['LITELLM_API_KEY'],
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


# ============================================================================
# 6. CONVENIENCE HELPER FUNCTIONS - One per provider
# ============================================================================


def anthropic(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Anthropic (Claude).

    Args:
        model_name: Model identifier (e.g. 'claude-opus-4-5', 'claude-sonnet-4-6')
        api_key: Anthropic API key. If omitted, reads from ANTHROPIC_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Anthropic.

    """
    return LLMConfig(
        provider='anthropic', model_name=model_name, api_key=_resolve_api_key('anthropic', api_key), **kwargs
    )


def groq(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Groq.

    Args:
        model_name: Groq model identifier (e.g. 'llama-3.3-70b-versatile')
        api_key: Groq API key. If omitted, reads from GROQ_API_KEY or GROQ_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Groq.

    """
    return LLMConfig(provider='groq', model_name=model_name, api_key=_resolve_api_key('groq', api_key), **kwargs)


def gemini(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Gemini (Google).

    Args:
        model_name: Gemini model identifier (e.g. 'gemini-2.0-flash')
        api_key: Google API key. If omitted, reads from GEMINI_API_KEY, GEMINI_KEY, or GOOGLE_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Gemini.

    """
    return LLMConfig(provider='gemini', model_name=model_name, api_key=_resolve_api_key('gemini', api_key), **kwargs)


def mistral(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Mistral.

    Args:
        model_name: Mistral model identifier (e.g. 'mistral-large-latest')
        api_key: Mistral API key. If omitted, reads from MISTRAL_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Mistral.

    """
    return LLMConfig(provider='mistral', model_name=model_name, api_key=_resolve_api_key('mistral', api_key), **kwargs)


def cerebras(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Cerebras.

    Args:
        model_name: Cerebras model identifier (e.g. 'llama-3.3-70b')
        api_key: Cerebras API key. If omitted, reads from CEREBRAS_API_KEY or CEREBRAS_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Cerebras.

    """
    return LLMConfig(
        provider='cerebras', model_name=model_name, api_key=_resolve_api_key('cerebras', api_key), **kwargs
    )


def huggingface(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for HuggingFace Inference API.

    Args:
        model_name: HuggingFace model ID (e.g. 'Qwen/Qwen3-235B-A22B')
        api_key: HF token. If omitted, reads from HF_TOKEN or HUGGINGFACE_API_KEY.
        **kwargs: Additional LLMConfig fields (e.g. extra_params={'provider_name': 'nebius'}).

    Returns:
        Configured LLMConfig for HuggingFace.

    """
    return LLMConfig(
        provider='huggingface', model_name=model_name, api_key=_resolve_api_key('huggingface', api_key), **kwargs
    )


def xai(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for xAI (Grok models via native xAI client).

    Args:
        model_name: xAI model identifier (e.g. 'grok-3', 'grok-3-mini')
        api_key: xAI API key. If omitted, reads from XAI_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for xAI.

    """
    return LLMConfig(provider='xai', model_name=model_name, api_key=_resolve_api_key('xai', api_key), **kwargs)


def bedrock(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for AWS Bedrock.

    ``api_key`` maps to ``aws_access_key_id``. Supply ``aws_secret_access_key``
    and ``region_name`` via ``extra_params``, or let boto3 resolve credentials
    from the environment.

    Args:
        model_name: Bedrock model ARN or ID (e.g. 'anthropic.claude-3-5-sonnet-20241022-v2:0')
        api_key: AWS access key ID. If omitted, reads from AWS_ACCESS_KEY_ID.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for AWS Bedrock.

    """
    return LLMConfig(provider='bedrock', model_name=model_name, api_key=_resolve_api_key('bedrock', api_key), **kwargs)


def vertexai(model_name: str, **kwargs: Any) -> LLMConfig:
    """Quick config for Google Vertex AI.

    No API key required — uses GCP application default credentials or a
    service account file supplied via ``extra_params``.

    Args:
        model_name: Vertex AI model ID (e.g. 'gemini-2.0-flash-001')
        **kwargs: Additional LLMConfig fields (e.g. extra_params={'project_id': '...', 'region': 'us-east1'}).

    Returns:
        Configured LLMConfig for Google Vertex AI.

    """
    return LLMConfig(provider='vertexai', model_name=model_name, **kwargs)


def openai(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for OpenAI.

    Args:
        model_name: OpenAI model identifier (e.g. 'gpt-4o', 'gpt-4o-mini')
        api_key: OpenAI API key. If omitted, reads from OPENAI_API_KEY or OPENAI_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for OpenAI.

    """
    return LLMConfig(provider='openai', model_name=model_name, api_key=_resolve_api_key('openai', api_key), **kwargs)


def openrouter(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for OpenRouter.

    Args:
        model_name: OpenRouter model identifier (e.g. 'meta-llama/llama-3.3-70b-instruct:free')
        api_key: OpenRouter API key. If omitted, reads from OPENROUTER_API_KEY or OPENROUTER_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for OpenRouter.

    """
    return LLMConfig(
        provider='openrouter', model_name=model_name, api_key=_resolve_api_key('openrouter', api_key), **kwargs
    )


def azure(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Azure OpenAI.

    Supply ``azure_endpoint`` and optionally ``api_version`` via ``extra_params``.

    Args:
        model_name: Azure deployment name (e.g. 'gpt-4o')
        api_key: Azure OpenAI API key. If omitted, reads from AZURE_OPENAI_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Azure OpenAI.

    """
    return LLMConfig(provider='azure', model_name=model_name, api_key=_resolve_api_key('azure', api_key), **kwargs)


def deepseek(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for DeepSeek.

    Args:
        model_name: DeepSeek model identifier (e.g. 'deepseek-chat', 'deepseek-reasoner')
        api_key: DeepSeek API key. If omitted, reads from DEEPSEEK_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for DeepSeek.

    """
    return LLMConfig(
        provider='deepseek', model_name=model_name, api_key=_resolve_api_key('deepseek', api_key), **kwargs
    )


def ollama(model_name: str, **kwargs: Any) -> LLMConfig:
    """Quick config for Ollama (local).

    No API key required. Supply ``base_url`` via ``extra_params`` to override
    the default ``http://localhost:11434``.

    Args:
        model_name: Ollama model tag (e.g. 'llama3', 'mistral', 'qwen2.5')
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Ollama.

    """
    return LLMConfig(provider='ollama', model_name=model_name, **kwargs)


def fireworks(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Fireworks AI.

    Args:
        model_name: Fireworks model identifier (e.g. 'accounts/fireworks/models/llama-v3p3-70b-instruct')
        api_key: Fireworks API key. If omitted, reads from FIREWORKS_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Fireworks.

    """
    return LLMConfig(
        provider='fireworks', model_name=model_name, api_key=_resolve_api_key('fireworks', api_key), **kwargs
    )


def together(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Together AI.

    Args:
        model_name: Together model identifier (e.g. 'meta-llama/Llama-3-70b-chat-hf')
        api_key: Together API key. If omitted, reads from TOGETHER_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Together AI.

    """
    return LLMConfig(
        provider='together', model_name=model_name, api_key=_resolve_api_key('together', api_key), **kwargs
    )


def nebius(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Nebius AI Studio.

    Args:
        model_name: Nebius model identifier (e.g. 'Qwen/Qwen3-235B-A22B-fast')
        api_key: Nebius API key. If omitted, reads from NEBIUS_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Nebius.

    """
    return LLMConfig(provider='nebius', model_name=model_name, api_key=_resolve_api_key('nebius', api_key), **kwargs)


def moonshotai(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for MoonshotAI (Kimi).

    Args:
        model_name: Moonshot model identifier (e.g. 'kimi-k2-0711-preview')
        api_key: Moonshot API key. If omitted, reads from MOONSHOT_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for MoonshotAI.

    """
    return LLMConfig(
        provider='moonshotai', model_name=model_name, api_key=_resolve_api_key('moonshotai', api_key), **kwargs
    )


def grok(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Grok via xAI's OpenAI-compatible endpoint.

    Args:
        model_name: Grok model identifier (e.g. 'grok-3', 'grok-3-mini')
        api_key: xAI API key. If omitted, reads from XAI_API_KEY or GROK_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Grok.

    """
    return LLMConfig(provider='grok', model_name=model_name, api_key=_resolve_api_key('grok', api_key), **kwargs)


def alibaba(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Alibaba Cloud DashScope.

    Args:
        model_name: DashScope model identifier (e.g. 'qwen-plus', 'qwen-max')
        api_key: DashScope API key. If omitted, reads from DASHSCOPE_API_KEY or ALIBABA_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Alibaba DashScope.

    """
    return LLMConfig(provider='alibaba', model_name=model_name, api_key=_resolve_api_key('alibaba', api_key), **kwargs)


def sambanova(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for SambaNova.

    Args:
        model_name: SambaNova model identifier (e.g. 'Meta-Llama-3.3-70B-Instruct')
        api_key: SambaNova API key. If omitted, reads from SAMBANOVA_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for SambaNova.

    """
    return LLMConfig(
        provider='sambanova', model_name=model_name, api_key=_resolve_api_key('sambanova', api_key), **kwargs
    )


def ovhcloud(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for OVHcloud AI Endpoints.

    Args:
        model_name: OVHcloud model identifier
        api_key: OVH access token. If omitted, reads from OVH_AI_ENDPOINTS_ACCESS_TOKEN.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for OVHcloud.

    """
    return LLMConfig(
        provider='ovhcloud', model_name=model_name, api_key=_resolve_api_key('ovhcloud', api_key), **kwargs
    )


def github(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for GitHub Models.

    Args:
        model_name: GitHub Models identifier (e.g. 'gpt-4o', 'Llama-3.3-70B-Instruct')
        api_key: GitHub token. If omitted, reads from GITHUB_TOKEN.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for GitHub Models.

    """
    return LLMConfig(provider='github', model_name=model_name, api_key=_resolve_api_key('github', api_key), **kwargs)


def vercel(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Vercel AI.

    Args:
        model_name: Vercel AI model identifier
        api_key: Vercel API key. If omitted, reads from AI_SDK_KEY or VERCEL_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Vercel AI.

    """
    return LLMConfig(provider='vercel', model_name=model_name, api_key=_resolve_api_key('vercel', api_key), **kwargs)


def heroku(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for Heroku Managed Inference.

    Args:
        model_name: Heroku model identifier (e.g. 'claude-3-5-sonnet')
        api_key: Heroku inference key. If omitted, reads from HEROKU_INFERENCE_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for Heroku.

    """
    return LLMConfig(provider='heroku', model_name=model_name, api_key=_resolve_api_key('heroku', api_key), **kwargs)


def litellm(model_name: str, api_key: str | None = None, **kwargs: Any) -> LLMConfig:
    """Quick config for LiteLLM proxy.

    Supply ``api_base`` via ``extra_params`` to point at your LiteLLM proxy
    endpoint.

    Args:
        model_name: Model identifier passed through to LiteLLM
        api_key: API key for the proxied provider. If omitted, reads from LITELLM_API_KEY.
        **kwargs: Additional LLMConfig fields.

    Returns:
        Configured LLMConfig for LiteLLM.

    """
    return LLMConfig(provider='litellm', model_name=model_name, api_key=_resolve_api_key('litellm', api_key), **kwargs)


# ============================================================================
# 7. UNIFIED PROVIDER FUNCTION - Magic model string parsing
# ============================================================================

# Canonical provider names recognised by `provider()`.  Aliases are included
# so that `ys.provider("gpt:gpt-4o")` works.
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
    _canonical = sorted(
        _KNOWN_PROVIDERS - {'google', 'gpt', 'claude', 'hf', 'aws', 'google-vertex', 'moonshot', 'dashscope', 'ovh'}
    )
    raise ValueError(
        f'Cannot determine provider from {model_string!r}. '
        f"Use 'provider:model-name' format, e.g. 'groq:{model_string}'. "
        f'Known providers: {", ".join(_canonical)}'
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
        config = ys.provider('anthropic:claude-opus-4-5')
        config = ys.provider('deepseek:deepseek-chat')
        config = ys.provider('ollama:llama3')

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
