"""Tests for yosoi.core.configs — YosoiConfig, DebugConfig, TelemetryConfig, find_available_provider."""

import pytest

from yosoi.core.configs import (
    DebugConfig,
    TelemetryConfig,
    YosoiConfig,
    find_available_provider,
)
from yosoi.core.discovery.config import LLMConfig


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure no provider env keys leak into tests."""
    for key in ('GROQ_KEY', 'GEMINI_KEY', 'OPENAI_KEY', 'CEREBRAS_KEY', 'OPENROUTER_KEY'):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# find_available_provider
# ---------------------------------------------------------------------------


class TestFindAvailableProvider:
    def test_returns_none_when_no_keys_set(self):
        """Returns None when no API key env vars are set."""
        assert find_available_provider() is None

    def test_returns_first_provider_with_key(self, monkeypatch):
        """Returns the first provider in fallback order that has a key."""
        monkeypatch.setenv('GEMINI_KEY', 'gk-123')
        result = find_available_provider()
        assert result is not None
        provider, _model, key = result
        assert provider == 'gemini'
        assert key == 'gk-123'

    def test_groq_takes_priority_over_gemini(self, monkeypatch):
        """Groq is first in fallback order, so it wins when both are set."""
        monkeypatch.setenv('GROQ_KEY', 'groq-abc')
        monkeypatch.setenv('GEMINI_KEY', 'gem-xyz')
        result = find_available_provider()
        assert result is not None
        assert result[0] == 'groq'

    def test_openrouter_used_if_only_key(self, monkeypatch):
        """OpenRouter is used when it's the only key available."""
        monkeypatch.setenv('OPENROUTER_KEY', 'or-key')
        result = find_available_provider()
        assert result is not None
        assert result[0] == 'openrouter'


# ---------------------------------------------------------------------------
# DebugConfig / TelemetryConfig
# ---------------------------------------------------------------------------


class TestDebugConfig:
    def test_defaults(self):
        """Default values: save_html=True, html_dir=.yosoi/debug_html."""
        cfg = DebugConfig()
        assert cfg.save_html is True
        assert 'debug_html' in str(cfg.html_dir)

    def test_custom_values(self, tmp_path):
        """Custom values are accepted."""
        cfg = DebugConfig(save_html=False, html_dir=tmp_path / 'debug')
        assert cfg.save_html is False


class TestTelemetryConfig:
    def test_defaults(self):
        """Default logfire_token is None."""
        cfg = TelemetryConfig()
        assert cfg.logfire_token is None

    def test_custom_token(self):
        """Custom token is accepted."""
        cfg = TelemetryConfig(logfire_token='tok-123')
        assert cfg.logfire_token == 'tok-123'


# ---------------------------------------------------------------------------
# YosoiConfig — validate_api_key_env
# ---------------------------------------------------------------------------


class TestYosoiConfig:
    def test_api_key_already_set_passes_through(self):
        """When api_key is provided, no env lookup is needed."""
        llm = LLMConfig(provider='groq', model_name='test', api_key='direct-key')
        cfg = YosoiConfig(llm=llm)
        assert cfg.llm.api_key == 'direct-key'

    def test_env_key_resolved_for_configured_provider(self, monkeypatch):
        """When api_key is empty, env var for the provider is used."""
        monkeypatch.setenv('GROQ_KEY', 'env-groq')
        llm = LLMConfig(provider='groq', model_name='test', api_key='')
        cfg = YosoiConfig(llm=llm)
        assert cfg.llm.api_key == 'env-groq'

    def test_unknown_provider_raises_value_error(self):
        """An unknown provider with no api_key raises ValueError."""
        llm = LLMConfig(provider='unknown_provider', model_name='test', api_key='')
        with pytest.raises(ValueError, match='Unknown provider'):
            YosoiConfig(llm=llm)

    def test_fallback_to_another_provider(self, monkeypatch):
        """When configured provider has no key, falls back to another."""
        monkeypatch.setenv('GEMINI_KEY', 'gem-fb')
        llm = LLMConfig(provider='groq', model_name='test', api_key='')
        cfg = YosoiConfig(llm=llm)
        assert cfg.llm.provider == 'gemini'
        assert cfg.llm.api_key == 'gem-fb'

    def test_no_key_anywhere_raises_value_error(self):
        """When no provider has a key and none is provided, raises ValueError."""
        llm = LLMConfig(provider='groq', model_name='test', api_key='')
        with pytest.raises(ValueError, match='No API key found'):
            YosoiConfig(llm=llm)

    def test_defaults_for_debug_telemetry_logs(self):
        """Default values for debug, telemetry, logs, force."""
        llm = LLMConfig(provider='groq', model_name='test', api_key='key')
        cfg = YosoiConfig(llm=llm)
        assert cfg.debug.save_html is True
        assert cfg.telemetry.logfire_token is None
        assert cfg.logs is True
        assert cfg.force is False
