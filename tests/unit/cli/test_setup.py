"""Tests for yosoi.cli.setup — setup_llm_config, build_yosoi_config."""

import pytest
import rich_click as click

from yosoi.cli.setup import build_yosoi_config, setup_llm_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure no provider env keys leak and .env file is not loaded during tests."""
    for key in (
        'GROQ_KEY',
        'GROQ_API_KEY',
        'GEMINI_KEY',
        'GEMINI_API_KEY',
        'GOOGLE_API_KEY',
        'OPENAI_KEY',
        'OPENAI_API_KEY',
        'CEREBRAS_KEY',
        'CEREBRAS_API_KEY',
        'OPENROUTER_KEY',
        'OPENROUTER_API_KEY',
        'LOGFIRE_TOKEN',
        'YOSOI_MODEL',
    ):
        monkeypatch.delenv(key, raising=False)

    import dotenv

    monkeypatch.setattr(dotenv, 'load_dotenv', lambda: False)


class TestSetupLlmConfig:
    def test_model_arg_with_colon(self):
        """--model flag with provider:model format works."""
        cfg = setup_llm_config('groq:llama-3.3-70b')
        assert cfg.provider == 'groq'
        assert cfg.model_name == 'llama-3.3-70b'
        assert cfg.api_key == ''

    def test_model_arg_no_slash_raises(self):
        """--model flag without separator raises ClickException."""
        with pytest.raises(click.ClickException, match='provider:model-name'):
            setup_llm_config('groq-llama')

    def test_auto_detect_provider(self, monkeypatch):
        """Auto-detects provider from env when no --model."""
        monkeypatch.setenv('GEMINI_KEY', 'gem-key')
        cfg = setup_llm_config(None)
        assert cfg.provider == 'gemini'

    def test_fallback_to_groq_default(self):
        """Falls back to groq when no env keys."""
        cfg = setup_llm_config(None)
        assert cfg.provider == 'groq'

    def test_yosoi_model_env_used_as_default(self, monkeypatch):
        """YOSOI_MODEL env var is used when no --model flag."""
        monkeypatch.setenv('YOSOI_MODEL', 'openrouter:mistralai/mistral-7b')
        cfg = setup_llm_config(None)
        assert cfg.provider == 'openrouter'
        assert cfg.model_name == 'mistralai/mistral-7b'

    def test_model_arg_overrides_yosoi_model_env(self, monkeypatch):
        """--model flag takes precedence over YOSOI_MODEL env var."""
        monkeypatch.setenv('YOSOI_MODEL', 'openrouter:mistralai/mistral-7b')
        cfg = setup_llm_config('groq:llama-3.3-70b')
        assert cfg.provider == 'groq'
        assert cfg.model_name == 'llama-3.3-70b'

    def test_yosoi_model_invalid_raises(self, monkeypatch):
        """Invalid YOSOI_MODEL env var raises ClickException."""
        monkeypatch.setenv('YOSOI_MODEL', 'not-a-valid-model-string')
        with pytest.raises(click.ClickException, match='YOSOI_MODEL'):
            setup_llm_config(None)

    def test_yosoi_model_takes_priority_over_auto_detect(self, monkeypatch):
        """YOSOI_MODEL takes priority over API-key-based auto-detection."""
        monkeypatch.setenv('YOSOI_MODEL', 'gemini:gemini-2.0-flash')
        monkeypatch.setenv('GROQ_KEY', 'groq-key')
        cfg = setup_llm_config(None)
        assert cfg.provider == 'gemini'
        assert cfg.model_name == 'gemini-2.0-flash'


class TestBuildYosoiConfig:
    def test_successful_build(self, monkeypatch):
        """Builds config successfully when API key is available."""
        monkeypatch.setenv('GROQ_KEY', 'groq-key')
        cfg = build_yosoi_config('groq:llama', debug=False)
        assert cfg.llm.api_key == 'groq-key'
        assert cfg.debug.save_html is False

    def test_debug_mode_enabled(self, monkeypatch):
        """Debug mode sets save_html to True."""
        monkeypatch.setenv('GROQ_KEY', 'groq-key')
        cfg = build_yosoi_config('groq:llama', debug=True)
        assert cfg.debug.save_html is True

    def test_no_api_key_raises(self):
        """Missing API key raises ClickException."""
        with pytest.raises(click.ClickException, match='Configuration Error'):
            build_yosoi_config('groq:llama', debug=False)

    def test_provider_fallback_warning(self, monkeypatch, capsys):
        """When configured provider lacks key and another is used, warns."""
        monkeypatch.setenv('GEMINI_KEY', 'gem-key')
        cfg = build_yosoi_config('groq:llama', debug=False)
        # Provider should have been swapped
        assert cfg.llm.provider == 'gemini'
