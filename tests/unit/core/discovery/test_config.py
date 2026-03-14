"""Tests for yosoi.core.discovery.config — LLMConfig, create_model, LLMBuilder, convenience helpers."""

import pytest

from yosoi.core.discovery.config import (
    LLMBuilder,
    LLMConfig,
    cerebras,
    create_model,
    gemini,
    groq,
    openai,
    openrouter,
    provider,
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
