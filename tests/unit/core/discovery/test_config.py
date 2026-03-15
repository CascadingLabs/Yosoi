"""Tests for yosoi.core.discovery.config — LLMConfig, create_model, LLMBuilder, convenience helpers."""

import pytest

from yosoi.core.discovery.config import (
    NO_API_KEY_REQUIRED_PROVIDERS,
    LLMBuilder,
    LLMConfig,
    alibaba,
    anthropic,
    azure,
    bedrock,
    cerebras,
    create_model,
    deepseek,
    fireworks,
    gemini,
    github,
    grok,
    groq,
    heroku,
    huggingface,
    litellm,
    mistral,
    moonshotai,
    nebius,
    ollama,
    openai,
    openrouter,
    ovhcloud,
    provider,
    sambanova,
    together,
    vercel,
    vertexai,
    xai,
)

# ---------------------------------------------------------------------------
# LLMConfig
# ---------------------------------------------------------------------------


class TestLLMConfig:
    def test_basic_construction(self):
        """LLMConfig can be created with required fields."""
        cfg = LLMConfig(provider='groq', model_name='test-model', api_key='key')
        assert cfg.provider == 'groq'
        assert cfg.model_name == 'test-model'
        assert cfg.api_key == 'key'

    def test_defaults(self):
        """Default temperature, max_tokens, extra_params."""
        cfg = LLMConfig(provider='groq', model_name='test', api_key='k')
        assert cfg.temperature == 0.01
        assert cfg.max_tokens is None
        assert cfg.extra_params is None

    def test_custom_values(self):
        """Custom temperature, max_tokens, extra_params."""
        cfg = LLMConfig(
            provider='openai',
            model_name='gpt-4',
            api_key='k',
            temperature=0.5,
            max_tokens=100,
            extra_params={'top_p': 0.9},
        )
        assert cfg.temperature == 0.5
        assert cfg.max_tokens == 100
        assert cfg.extra_params == {'top_p': 0.9}


# ---------------------------------------------------------------------------
# create_model — factory dispatch
# ---------------------------------------------------------------------------


class TestCreateModel:
    def test_unknown_provider_raises(self):
        """Unknown provider raises ValueError with available providers."""
        cfg = LLMConfig(provider='nonexistent', model_name='m', api_key='k')
        with pytest.raises(ValueError, match='Unknown provider'):
            create_model(cfg)

    def test_groq_provider(self):
        """Groq provider creates a GroqModel."""
        cfg = LLMConfig(provider='groq', model_name='llama', api_key='k')
        model = create_model(cfg)
        assert 'Groq' in type(model).__name__

    def test_gemini_provider(self):
        """Gemini provider creates a GoogleModel."""
        cfg = LLMConfig(provider='gemini', model_name='gemini-2', api_key='k')
        model = create_model(cfg)
        assert 'Google' in type(model).__name__

    def test_google_alias(self):
        """'google' is an alias for gemini."""
        cfg = LLMConfig(provider='google', model_name='gemini-2', api_key='k')
        model = create_model(cfg)
        assert 'Google' in type(model).__name__

    def test_openai_provider(self):
        """OpenAI provider creates an OpenAIChatModel."""
        cfg = LLMConfig(provider='openai', model_name='gpt-4', api_key='k')
        model = create_model(cfg)
        assert 'OpenAI' in type(model).__name__

    def test_gpt_alias(self):
        """'gpt' is an alias for openai."""
        cfg = LLMConfig(provider='gpt', model_name='gpt-4', api_key='k')
        model = create_model(cfg)
        assert 'OpenAI' in type(model).__name__

    def test_cerebras_provider(self):
        """Cerebras provider creates a CerebrasModel."""
        cfg = LLMConfig(provider='cerebras', model_name='llama', api_key='k')
        model = create_model(cfg)
        assert 'Cerebras' in type(model).__name__

    def test_openrouter_provider(self):
        """OpenRouter provider creates an OpenRouterModel."""
        cfg = LLMConfig(provider='openrouter', model_name='meta-llama/llama', api_key='k')
        model = create_model(cfg)
        assert 'OpenRouter' in type(model).__name__

    def test_case_insensitive_provider(self):
        """Provider name is case-insensitive."""
        cfg = LLMConfig(provider='GROQ', model_name='llama', api_key='k')
        model = create_model(cfg)
        assert 'Groq' in type(model).__name__


# ---------------------------------------------------------------------------
# LLMBuilder
# ---------------------------------------------------------------------------


class TestLLMBuilder:
    def test_full_build(self):
        """Builder produces correct LLMConfig."""
        cfg = (
            LLMBuilder()
            .provider('groq')
            .model('llama')
            .api_key('key')
            .temperature(0.5)
            .max_tokens(200)
            .extra(top_p=0.9)
            .build()
        )
        assert cfg.provider == 'groq'
        assert cfg.model_name == 'llama'
        assert cfg.api_key == 'key'
        assert cfg.temperature == 0.5
        assert cfg.max_tokens == 200
        assert cfg.extra_params == {'top_p': 0.9}

    def test_missing_provider_raises(self):
        """Build without provider raises ValueError."""
        with pytest.raises(ValueError, match='Provider must be set'):
            LLMBuilder().model('m').api_key('k').build()

    def test_missing_model_raises(self):
        """Build without model raises ValueError."""
        with pytest.raises(ValueError, match='Model name must be set'):
            LLMBuilder().provider('groq').api_key('k').build()

    def test_missing_api_key_resolves_to_none(self, monkeypatch):
        """Build without api_key resolves to None (provider handles resolution)."""
        monkeypatch.setattr('dotenv.load_dotenv', lambda: None)
        monkeypatch.delenv('GROQ_API_KEY', raising=False)
        monkeypatch.delenv('GROQ_KEY', raising=False)
        cfg = LLMBuilder().provider('groq').model('m').build()
        assert cfg.api_key is None

    def test_no_extra_params_results_in_none(self):
        """When no extra params set, extra_params is None."""
        cfg = LLMBuilder().provider('groq').model('m').api_key('k').build()
        assert cfg.extra_params is None


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


class TestConvenienceHelpers:
    def test_groq_helper(self):
        """groq() creates a groq LLMConfig."""
        cfg = groq('llama', 'key')
        assert cfg.provider == 'groq'
        assert cfg.model_name == 'llama'

    def test_gemini_helper(self):
        """gemini() creates a gemini LLMConfig."""
        cfg = gemini('gemini-2', 'key')
        assert cfg.provider == 'gemini'

    def test_cerebras_helper(self):
        """cerebras() creates a cerebras LLMConfig."""
        cfg = cerebras('llama', 'key')
        assert cfg.provider == 'cerebras'

    def test_openai_helper(self):
        """openai() creates an openai LLMConfig."""
        cfg = openai('gpt-4', 'key')
        assert cfg.provider == 'openai'

    def test_openrouter_helper(self):
        """openrouter() creates an openrouter LLMConfig."""
        cfg = openrouter('meta-llama/llama', 'key')
        assert cfg.provider == 'openrouter'

    def test_kwargs_pass_through(self):
        """Extra kwargs are forwarded to LLMConfig."""
        cfg = groq('llama', 'key', temperature=0.9, max_tokens=50)
        assert cfg.temperature == 0.9
        assert cfg.max_tokens == 50


# ---------------------------------------------------------------------------
# Coverage: lines 228-229 — create_agent function
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# provider() — unified model string parsing
# ---------------------------------------------------------------------------


class TestProvider:
    """Tests for the unified provider() function."""

    # -- Colon format (preferred) --

    def test_colon_groq(self):
        """provider('groq:llama') parses colon format."""
        cfg = provider('groq:llama-3.3-70b-versatile', api_key='k')
        assert cfg.provider == 'groq'
        assert cfg.model_name == 'llama-3.3-70b-versatile'
        assert cfg.api_key == 'k'

    def test_colon_openrouter_preserves_slashes(self):
        """Colon format preserves slashes in OpenRouter model names."""
        cfg = provider('openrouter:meta-llama/llama-3.3-70b-instruct:free', api_key='k')
        assert cfg.provider == 'openrouter'
        assert cfg.model_name == 'meta-llama/llama-3.3-70b-instruct:free'

    def test_colon_openrouter_stepfun(self):
        """openrouter:stepfun/step-3.5-flash:free works."""
        cfg = provider('openrouter:stepfun/step-3.5-flash:free', api_key='k')
        assert cfg.provider == 'openrouter'
        assert cfg.model_name == 'stepfun/step-3.5-flash:free'

    def test_colon_gemini(self):
        """provider('gemini:gemini-2.0-flash') works."""
        cfg = provider('gemini:gemini-2.0-flash', api_key='k')
        assert cfg.provider == 'gemini'
        assert cfg.model_name == 'gemini-2.0-flash'

    def test_colon_openai(self):
        """provider('openai:gpt-4o') works."""
        cfg = provider('openai:gpt-4o', api_key='k')
        assert cfg.provider == 'openai'
        assert cfg.model_name == 'gpt-4o'

    def test_colon_gpt_alias(self):
        """provider('gpt:gpt-4o') uses the gpt alias."""
        cfg = provider('gpt:gpt-4o', api_key='k')
        assert cfg.provider == 'gpt'

    def test_colon_cerebras(self):
        """provider('cerebras:llama-3.3-70b') works."""
        cfg = provider('cerebras:llama-3.3-70b', api_key='k')
        assert cfg.provider == 'cerebras'

    def test_colon_case_insensitive(self):
        """provider('GROQ:llama') is case insensitive."""
        cfg = provider('GROQ:llama', api_key='k')
        assert cfg.provider == 'groq'

    # -- Slash format (legacy / CLI compat) --

    def test_slash_groq(self):
        """provider('groq/llama') still works (legacy format)."""
        cfg = provider('groq/llama-3.3-70b-versatile', api_key='k')
        assert cfg.provider == 'groq'
        assert cfg.model_name == 'llama-3.3-70b-versatile'

    def test_slash_openrouter_known_prefix(self):
        """provider('openrouter/meta-llama/llama:free') works via slash when prefix is known."""
        cfg = provider('openrouter/meta-llama/llama-3.3-70b-instruct:free', api_key='k')
        assert cfg.provider == 'openrouter'
        assert cfg.model_name == 'meta-llama/llama-3.3-70b-instruct:free'

    # -- Error cases --

    def test_bare_model_name_raises(self):
        """A model name without provider prefix raises ValueError."""
        with pytest.raises(ValueError, match='Cannot determine provider'):
            provider('llama-3.3-70b-versatile', api_key='k')

    def test_unknown_prefix_raises(self):
        """Unknown prefix (not a known provider) raises ValueError."""
        with pytest.raises(ValueError, match='Cannot determine provider'):
            provider('meta-llama/llama-3.3-70b-instruct', api_key='k')

    # -- kwargs --

    def test_kwargs_forwarded(self):
        """Extra kwargs like temperature are forwarded."""
        cfg = provider('groq:llama', api_key='k', temperature=0.9, max_tokens=50)
        assert cfg.temperature == 0.9
        assert cfg.max_tokens == 50

    def test_top_level_import(self):
        """provider is accessible as ys.provider."""
        import yosoi as ys

        assert hasattr(ys, 'provider')
        assert callable(ys.provider)


class TestCreateAgent:
    def test_create_agent_returns_agent(self):
        """create_agent returns a pydantic-ai Agent."""
        from pydantic_ai import Agent

        from yosoi.core.discovery.config import create_agent

        cfg = LLMConfig(provider='groq', model_name='llama', api_key='k')
        agent = create_agent(cfg, 'You are helpful')
        assert isinstance(agent, Agent)


# ---------------------------------------------------------------------------
# create_model — new first-class providers
# ---------------------------------------------------------------------------


class TestCreateModelNewFirstClass:
    def test_anthropic_provider(self):
        """Anthropic provider creates an AnthropicModel."""
        cfg = LLMConfig(provider='anthropic', model_name='claude-opus-4-5', api_key='k')
        model = create_model(cfg)
        assert 'Anthropic' in type(model).__name__

    def test_claude_alias(self):
        """'claude' is an alias for anthropic."""
        cfg = LLMConfig(provider='claude', model_name='claude-opus-4-5', api_key='k')
        model = create_model(cfg)
        assert 'Anthropic' in type(model).__name__

    def test_mistral_provider(self):
        """Mistral provider creates a MistralModel."""
        cfg = LLMConfig(provider='mistral', model_name='mistral-large-latest', api_key='k')
        model = create_model(cfg)
        assert 'Mistral' in type(model).__name__

    def test_xai_provider(self):
        """xAI provider creates an XaiModel."""
        cfg = LLMConfig(provider='xai', model_name='grok-3', api_key='k')
        model = create_model(cfg)
        assert 'Xai' in type(model).__name__

    def test_bedrock_provider(self):
        """Bedrock provider creates a BedrockConverseModel (region required)."""
        cfg = LLMConfig(
            provider='bedrock',
            model_name='anthropic.claude-3-5-sonnet',
            api_key='k',
            extra_params={'region_name': 'us-east-1'},
        )
        model = create_model(cfg)
        assert 'Bedrock' in type(model).__name__

    def test_aws_alias(self):
        """'aws' is an alias for bedrock."""
        cfg = LLMConfig(
            provider='aws',
            model_name='anthropic.claude-3-5-sonnet',
            api_key='k',
            extra_params={'region_name': 'us-east-1'},
        )
        model = create_model(cfg)
        assert 'Bedrock' in type(model).__name__

    def test_huggingface_provider(self):
        """HuggingFace provider creates a HuggingFaceModel."""
        cfg = LLMConfig(provider='huggingface', model_name='Qwen/Qwen3-235B-A22B', api_key='k')
        model = create_model(cfg)
        assert 'HuggingFace' in type(model).__name__

    def test_hf_alias(self):
        """'hf' is an alias for huggingface."""
        cfg = LLMConfig(provider='hf', model_name='Qwen/Qwen3-235B-A22B', api_key='k')
        model = create_model(cfg)
        assert 'HuggingFace' in type(model).__name__

    def test_vertexai_provider(self):
        """Vertex AI provider creates a GoogleModel (no api_key required) with a deprecation warning."""
        cfg = LLMConfig(provider='vertexai', model_name='gemini-2.0-flash-001')
        with pytest.warns(DeprecationWarning, match='vertexai'):
            model = create_model(cfg)
        assert 'Google' in type(model).__name__

    def test_google_vertex_alias(self):
        """'google-vertex' is an alias for vertexai, also emits a deprecation warning."""
        cfg = LLMConfig(provider='google-vertex', model_name='gemini-2.0-flash-001')
        with pytest.warns(DeprecationWarning, match='vertexai'):
            model = create_model(cfg)
        assert 'Google' in type(model).__name__


# ---------------------------------------------------------------------------
# create_model — new OpenAI-compatible providers
# ---------------------------------------------------------------------------


class TestCreateModelOpenAICompat:
    """All OpenAI-compatible providers should produce an OpenAIChatModel."""

    def _assert_openai_model(self, provider_name: str, model_name: str = 'test-model') -> None:
        cfg = LLMConfig(provider=provider_name, model_name=model_name, api_key='k')
        model = create_model(cfg)
        assert 'OpenAI' in type(model).__name__, f'{provider_name} should produce an OpenAIChatModel'

    def test_azure(self, monkeypatch):
        """Azure requires an endpoint and api_version."""
        monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://my.openai.azure.com/')
        monkeypatch.setenv('OPENAI_API_VERSION', '2024-12-01-preview')
        self._assert_openai_model('azure')

    def test_deepseek(self):
        self._assert_openai_model('deepseek')

    def test_fireworks(self):
        self._assert_openai_model('fireworks')

    def test_together(self):
        self._assert_openai_model('together')

    def test_nebius(self):
        self._assert_openai_model('nebius')

    def test_moonshotai(self):
        self._assert_openai_model('moonshotai')

    def test_moonshot_alias(self):
        self._assert_openai_model('moonshot')

    def test_grok(self):
        """grok emits a deprecation warning and delegates to xai (XaiModel)."""
        cfg = LLMConfig(provider='grok', model_name='grok-3', api_key='k')
        with pytest.warns(DeprecationWarning, match="'grok' is deprecated"):
            model = create_model(cfg)
        assert 'Xai' in type(model).__name__

    def test_alibaba(self):
        self._assert_openai_model('alibaba')

    def test_dashscope_alias(self):
        self._assert_openai_model('dashscope')

    def test_sambanova(self):
        self._assert_openai_model('sambanova')

    def test_ovhcloud(self):
        self._assert_openai_model('ovhcloud')

    def test_ovh_alias(self):
        self._assert_openai_model('ovh')

    def test_github(self):
        self._assert_openai_model('github')

    def test_vercel(self):
        self._assert_openai_model('vercel')

    def test_heroku(self):
        self._assert_openai_model('heroku')

    def test_litellm(self):
        self._assert_openai_model('litellm')

    def test_ollama_no_api_key(self):
        """Ollama is local — no api_key required; base_url supplied via extra_params."""
        cfg = LLMConfig(provider='ollama', model_name='llama3', extra_params={'base_url': 'http://localhost:11434'})
        model = create_model(cfg)
        assert 'OpenAI' in type(model).__name__


# ---------------------------------------------------------------------------
# Special provider behaviour
# ---------------------------------------------------------------------------


class TestSpecialProviderBehaviour:
    def test_bedrock_extra_params_forwarded(self):
        """Bedrock passes aws_secret_access_key and region_name from extra_params."""
        cfg = LLMConfig(
            provider='bedrock',
            model_name='anthropic.claude-3-5-sonnet',
            api_key='access-key-id',
            extra_params={'aws_secret_access_key': 'secret', 'region_name': 'eu-west-1'},
        )
        # Should not raise; provider is constructed without network calls.
        model = create_model(cfg)
        assert 'Bedrock' in type(model).__name__

    def test_azure_extra_params_forwarded(self, monkeypatch):
        """Azure passes azure_endpoint and api_version from extra_params."""
        monkeypatch.setenv('OPENAI_API_VERSION', '2024-12-01-preview')
        cfg = LLMConfig(
            provider='azure',
            model_name='gpt-4o',
            api_key='k',
            extra_params={'azure_endpoint': 'https://my-resource.openai.azure.com/'},
        )
        model = create_model(cfg)
        assert 'OpenAI' in type(model).__name__

    def test_ollama_extra_params_base_url(self):
        """Ollama accepts a custom base_url via extra_params."""
        cfg = LLMConfig(
            provider='ollama',
            model_name='llama3',
            extra_params={'base_url': 'http://localhost:11434'},
        )
        model = create_model(cfg)
        assert 'OpenAI' in type(model).__name__

    def test_huggingface_provider_name_extra_param(self):
        """HuggingFace forwards provider_name from extra_params."""
        cfg = LLMConfig(
            provider='huggingface',
            model_name='Qwen/Qwen3-235B-A22B',
            api_key='hf_token',
            extra_params={'provider_name': 'nebius'},
        )
        model = create_model(cfg)
        assert 'HuggingFace' in type(model).__name__

    def test_litellm_api_base_extra_param(self):
        """LiteLLM forwards api_base from extra_params."""
        cfg = LLMConfig(
            provider='litellm',
            model_name='gpt-4o',
            api_key='k',
            extra_params={'api_base': 'http://localhost:4000'},
        )
        model = create_model(cfg)
        assert 'OpenAI' in type(model).__name__

    def test_vertexai_extra_params_project(self):
        """Vertex AI accepts project_id and region from extra_params."""
        cfg = LLMConfig(
            provider='vertexai',
            model_name='gemini-2.0-flash-001',
            extra_params={'project_id': 'my-project', 'region': 'us-east1'},
        )
        with pytest.warns(DeprecationWarning, match='vertexai'):
            model = create_model(cfg)
        assert 'Google' in type(model).__name__


# ---------------------------------------------------------------------------
# NO_API_KEY_REQUIRED_PROVIDERS
# ---------------------------------------------------------------------------


class TestNoApiKeyProviders:
    def test_ollama_in_set(self):
        """ollama is in NO_API_KEY_REQUIRED_PROVIDERS."""
        assert 'ollama' in NO_API_KEY_REQUIRED_PROVIDERS

    def test_vertexai_in_set(self):
        """vertexai is in NO_API_KEY_REQUIRED_PROVIDERS."""
        assert 'vertexai' in NO_API_KEY_REQUIRED_PROVIDERS

    def test_google_vertex_alias_in_set(self):
        """google-vertex is in NO_API_KEY_REQUIRED_PROVIDERS."""
        assert 'google-vertex' in NO_API_KEY_REQUIRED_PROVIDERS

    def test_ollama_helper_no_api_key(self):
        """ollama() produces a config with api_key=None."""
        cfg = ollama('llama3')
        assert cfg.api_key is None

    def test_vertexai_helper_no_api_key(self):
        """vertexai() produces a config with api_key=None; model creation warns."""
        cfg = vertexai('gemini-2.0-flash-001')
        assert cfg.api_key is None
        with pytest.warns(DeprecationWarning, match='vertexai'):
            create_model(cfg)


# ---------------------------------------------------------------------------
# New convenience helpers
# ---------------------------------------------------------------------------


class TestNewConvenienceHelpers:
    def test_anthropic_helper(self):
        cfg = anthropic('claude-opus-4-5', 'key')
        assert cfg.provider == 'anthropic'
        assert cfg.model_name == 'claude-opus-4-5'
        assert cfg.api_key == 'key'

    def test_mistral_helper(self):
        cfg = mistral('mistral-large-latest', 'key')
        assert cfg.provider == 'mistral'
        assert cfg.model_name == 'mistral-large-latest'

    def test_xai_helper(self):
        cfg = xai('grok-3', 'key')
        assert cfg.provider == 'xai'
        assert cfg.model_name == 'grok-3'

    def test_bedrock_helper(self):
        cfg = bedrock('anthropic.claude-3-5-sonnet', 'access-key')
        assert cfg.provider == 'bedrock'
        assert cfg.model_name == 'anthropic.claude-3-5-sonnet'
        assert cfg.api_key == 'access-key'

    def test_huggingface_helper(self):
        cfg = huggingface('Qwen/Qwen3-235B-A22B', 'hf_token')
        assert cfg.provider == 'huggingface'

    def test_azure_helper(self):
        cfg = azure('gpt-4o', 'key')
        assert cfg.provider == 'azure'

    def test_deepseek_helper(self):
        cfg = deepseek('deepseek-chat', 'key')
        assert cfg.provider == 'deepseek'

    def test_ollama_helper(self):
        cfg = ollama('llama3')
        assert cfg.provider == 'ollama'
        assert cfg.model_name == 'llama3'

    def test_fireworks_helper(self):
        cfg = fireworks('accounts/fireworks/models/llama', 'key')
        assert cfg.provider == 'fireworks'

    def test_together_helper(self):
        cfg = together('meta-llama/Llama-3-70b', 'key')
        assert cfg.provider == 'together'

    def test_nebius_helper(self):
        cfg = nebius('Qwen/Qwen3-235B-A22B-fast', 'key')
        assert cfg.provider == 'nebius'

    def test_moonshotai_helper(self):
        cfg = moonshotai('kimi-k2-0711-preview', 'key')
        assert cfg.provider == 'moonshotai'

    def test_grok_helper(self):
        cfg = grok('grok-3', 'key')
        assert cfg.provider == 'grok'

    def test_alibaba_helper(self):
        cfg = alibaba('qwen-plus', 'key')
        assert cfg.provider == 'alibaba'

    def test_sambanova_helper(self):
        cfg = sambanova('Meta-Llama-3.3-70B-Instruct', 'key')
        assert cfg.provider == 'sambanova'

    def test_ovhcloud_helper(self):
        cfg = ovhcloud('mixtral-8x22b', 'key')
        assert cfg.provider == 'ovhcloud'

    def test_github_helper(self):
        cfg = github('gpt-4o', 'token')
        assert cfg.provider == 'github'

    def test_vercel_helper(self):
        cfg = vercel('gpt-4o', 'key')
        assert cfg.provider == 'vercel'

    def test_heroku_helper(self):
        cfg = heroku('claude-3-5-sonnet', 'key')
        assert cfg.provider == 'heroku'

    def test_litellm_helper(self):
        cfg = litellm('gpt-4o', 'key')
        assert cfg.provider == 'litellm'

    def test_vertexai_helper(self):
        cfg = vertexai('gemini-2.0-flash-001')
        assert cfg.provider == 'vertexai'

    def test_kwargs_pass_through(self):
        """Extra kwargs forwarded for all new helpers."""
        cfg = anthropic('claude-opus-4-5', 'k', temperature=0.5, max_tokens=100)
        assert cfg.temperature == 0.5
        assert cfg.max_tokens == 100


# ---------------------------------------------------------------------------
# provider() — new providers via unified string parsing
# ---------------------------------------------------------------------------


class TestProviderNewProviders:
    def test_anthropic(self):
        cfg = provider('anthropic:claude-opus-4-5', api_key='k')
        assert cfg.provider == 'anthropic'
        assert cfg.model_name == 'claude-opus-4-5'

    def test_mistral(self):
        cfg = provider('mistral:mistral-large-latest', api_key='k')
        assert cfg.provider == 'mistral'
        assert cfg.model_name == 'mistral-large-latest'

    def test_xai(self):
        cfg = provider('xai:grok-3', api_key='k')
        assert cfg.provider == 'xai'
        assert cfg.model_name == 'grok-3'

    def test_bedrock(self):
        cfg = provider('bedrock:anthropic.claude-3-5-sonnet', api_key='k')
        assert cfg.provider == 'bedrock'
        assert cfg.model_name == 'anthropic.claude-3-5-sonnet'

    def test_deepseek(self):
        cfg = provider('deepseek:deepseek-chat', api_key='k')
        assert cfg.provider == 'deepseek'
        assert cfg.model_name == 'deepseek-chat'

    def test_ollama(self):
        cfg = provider('ollama:llama3')
        assert cfg.provider == 'ollama'
        assert cfg.model_name == 'llama3'
        assert cfg.api_key is None

    def test_fireworks(self):
        cfg = provider('fireworks:accounts/fireworks/models/llama', api_key='k')
        assert cfg.provider == 'fireworks'
        assert cfg.model_name == 'accounts/fireworks/models/llama'

    def test_together(self):
        cfg = provider('together:meta-llama/Llama-3-70b', api_key='k')
        assert cfg.provider == 'together'
        assert cfg.model_name == 'meta-llama/Llama-3-70b'

    def test_grok(self):
        cfg = provider('grok:grok-3', api_key='k')
        assert cfg.provider == 'grok'
        assert cfg.model_name == 'grok-3'
        with pytest.warns(DeprecationWarning, match="'grok' is deprecated"):
            create_model(cfg)

    def test_github(self):
        cfg = provider('github:gpt-4o', api_key='token')
        assert cfg.provider == 'github'
        assert cfg.model_name == 'gpt-4o'

    def test_vertexai(self):
        cfg = provider('vertexai:gemini-2.0-flash-001')
        assert cfg.provider == 'vertexai'
        assert cfg.model_name == 'gemini-2.0-flash-001'
        assert cfg.api_key is None
        with pytest.warns(DeprecationWarning, match='vertexai'):
            create_model(cfg)

    def test_bedrock_colon_in_model_name(self):
        """Bedrock model ARNs with colons are parsed correctly."""
        cfg = provider('bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0', api_key='k')
        assert cfg.provider == 'bedrock'
        assert cfg.model_name == 'anthropic.claude-3-5-sonnet-20241022-v2:0'
