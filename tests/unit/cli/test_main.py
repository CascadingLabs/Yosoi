"""Tests for yosoi.cli.main — the main CLI command."""

import pytest
from click.testing import CliRunner

from yosoi.cli.main import _LEVEL_MAP, main


class TestLevelMap:
    def test_all_selector_levels_mapped(self):
        """All SelectorLevel members are in the level map."""
        from yosoi.models.selectors import SelectorLevel

        for level in SelectorLevel:
            assert level.name.lower() in _LEVEL_MAP

    def test_all_alias(self):
        """'all' alias maps to max level."""
        from yosoi.models.selectors import SelectorLevel

        assert _LEVEL_MAP['all'] == max(SelectorLevel)


class TestMainCLI:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_no_urls_error(self, runner, monkeypatch):
        """No URLs provided raises usage error."""
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        result = runner.invoke(main, [])
        assert result.exit_code != 0
        assert 'No URLs provided' in result.output

    def test_summary_flag(self, runner, monkeypatch, mocker):
        """--summary flag triggers show_summary on Pipeline."""
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
        mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')
        mock_pipeline = mocker.MagicMock()
        mocker.patch('yosoi.Pipeline', return_value=mock_pipeline)

        runner.invoke(main, ['--summary', '-C', 'NewsArticle'])
        mock_pipeline.show_summary.assert_called_once()
