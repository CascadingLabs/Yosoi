"""Tests for yosoi.cli.setup — setup_llm_config, build_yosoi_config."""

import pytest
import rich_click as click

from yosoi.cli.setup import build_yosoi_config, setup_llm_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure no provider env keys leak."""
    for key in ('GROQ_KEY', 'GEMINI_KEY', 'OPENAI_KEY', 'CEREBRAS_KEY', 'OPENROUTER_KEY', 'LOGFIRE_TOKEN'):
        monkeypatch.delenv(key, raising=False)


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
