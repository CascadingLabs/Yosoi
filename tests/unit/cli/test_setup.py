"""Tests for yosoi.cli.setup — build_yosoi_config (thin CLI wrapper over auto_config)."""

import pytest
import rich_click as click

from yosoi.cli.setup import build_yosoi_config


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
        with pytest.raises(click.ClickException):
            build_yosoi_config('groq:llama', debug=False)

    def test_provider_fallback_warning(self, monkeypatch):
        """When configured provider lacks key and another is used, warns."""
        monkeypatch.setenv('GEMINI_KEY', 'gem-key')
        cfg = build_yosoi_config('groq:llama', debug=False)
        # Provider should have been swapped
        assert cfg.llm.provider == 'gemini'

    def test_invalid_model_string_raises(self):
        """Invalid model string raises ClickException."""
        with pytest.raises(click.ClickException):
            build_yosoi_config('invalid-no-provider', debug=False)

    def test_auto_detect_from_env(self, monkeypatch):
        """When no model arg, auto-detects from env key."""
        monkeypatch.setenv('GEMINI_KEY', 'gem-key')
        cfg = build_yosoi_config(None, debug=False)
        assert cfg.llm.provider == 'gemini'

    def test_yosoi_model_env_used(self, monkeypatch):
        """YOSOI_MODEL env var is used when no explicit model."""
        monkeypatch.setenv('YOSOI_MODEL', 'gemini:gemini-2.0-flash')
        monkeypatch.setenv('GEMINI_KEY', 'gem-key')
        cfg = build_yosoi_config(None, debug=False)
        assert cfg.llm.provider == 'gemini'
        assert cfg.llm.model_name == 'gemini-2.0-flash'
