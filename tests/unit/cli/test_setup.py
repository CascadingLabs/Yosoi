"""Tests for yosoi.cli.setup — build_yosoi_config (thin CLI wrapper over auto_config)."""

import pytest
import rich_click as click

import yosoi as ys
from yosoi.cli.setup import build_policy, build_yosoi_config


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
        'LANGFUSE_PUBLIC_KEY',
        'LANGFUSE_SECRET_KEY',
        'LANGFUSE_HOST',
        'LANGFUSE_BASE_URL',
        'YOSOI_MODEL',
        'YOSOI_FORCE',
        'YOSOI_FETCHER_TYPE',
        'YOSOI_SELECTOR_LEVEL',
        'YOSOI_DISCOVERY_MODE',
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

    def test_explicit_provider_without_key_raises(self, monkeypatch):
        """Explicit provider selection fails fast instead of falling back."""
        monkeypatch.setenv('GEMINI_KEY', 'gem-key')

        with pytest.raises(click.ClickException, match='explicit provider'):
            build_yosoi_config('groq:llama', debug=False)

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


class TestBuildPolicy:
    def test_build_policy_includes_cli_flags(self, monkeypatch):
        """CLI flags are represented in the policy layer before Pipeline construction."""
        monkeypatch.setenv('GROQ_KEY', 'groq-key')

        policy = build_policy(
            'groq:llama',
            debug=True,
            force=True,
            skip_verification=True,
            fetcher_type='headless',
            selector_level=ys.SelectorLevel.XPATH,
            output_formats=('json', 'csv'),
            quiet=False,
            json_output=False,
            max_concurrency=3,
        )

        assert policy.model is not None
        assert policy.model.provider == 'groq'
        assert policy.scrape == ys.ScrapePolicy(
            force=True,
            skip_verification=True,
            fetcher_type='headless',
            selector_level=ys.SelectorLevel.XPATH,
            max_concurrency=3,
        )
        assert policy.output == ys.OutputPolicy(formats=('json', 'csv'), quiet=False, debug_html=True)

    def test_build_policy_explicit_provider_missing_key_does_not_fallback(self, monkeypatch):
        """Policy CLI path fails when the requested provider key is absent."""
        monkeypatch.setenv('GEMINI_KEY', 'gem-key')

        with pytest.raises(click.ClickException, match='explicit provider'):
            build_policy('groq:llama', debug=False)

    def test_build_policy_loads_dotenv_before_reading_policy_env(self, monkeypatch):
        """CLI policy setup preserves old .env loading behavior."""
        called = False

        def _load_dotenv() -> bool:
            nonlocal called
            called = True
            monkeypatch.setenv('GROQ_KEY', 'groq-key')
            return True

        import dotenv

        monkeypatch.setattr(dotenv, 'load_dotenv', _load_dotenv)

        policy = build_policy('groq:llama', debug=False)

        assert called is True
        assert policy.resolve_run_spec().llm_config.api_key == 'groq-key'

    def test_build_policy_bad_env_is_click_exception(self, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'groq-key')
        monkeypatch.setenv('YOSOI_SELECTOR_LEVEL', 'bogus')

        with pytest.raises(click.ClickException, match='Invalid YOSOI_SELECTOR_LEVEL'):
            build_policy('groq:llama', debug=False)
