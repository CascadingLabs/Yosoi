"""Tests for yosoi.cli.main — the main CLI command."""

import os

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


class TestSessionIdOrdering:
    """A4b: --session-id must set YOSOI_SESSION_ID before observability.configure() runs.

    Asserting on _PROCESS_SESSION_ID directly is the wrong shape — it is module-state
    set on first call to process_session_id(). The invariant we care about is that
    when configure() is invoked, the env var is already in place.
    """

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_session_id_flag_sets_env_var_before_pipeline_construction(self, runner, monkeypatch, mocker):
        """Pipeline() is one transitive step from observability.configure(); capturing
        os.environ at Pipeline-construction time directly tests the ordering invariant.
        """
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        monkeypatch.delenv('YOSOI_SESSION_ID', raising=False)
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
        mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')

        captured: dict[str, str | None] = {}
        mock_pipe = mocker.MagicMock()
        mock_pipe.process_urls = mocker.AsyncMock(return_value={'successful': [], 'failed': []})

        def _capturing_pipeline(*_args, **_kwargs):
            captured['session_id_at_pipeline'] = os.environ.get('YOSOI_SESSION_ID')
            return mock_pipe

        mocker.patch('yosoi.Pipeline', side_effect=_capturing_pipeline)

        result = runner.invoke(main, ['--session-id', 'foo-bar-123', '-u', 'https://example.com'])
        assert result.exit_code == 0, result.output
        assert captured['session_id_at_pipeline'] == 'foo-bar-123'

    def test_no_session_id_flag_leaves_env_var_unset(self, runner, monkeypatch, mocker):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        monkeypatch.delenv('YOSOI_SESSION_ID', raising=False)
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
        mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')

        captured: dict[str, str | None] = {}
        mock_pipe = mocker.MagicMock()
        mock_pipe.process_urls = mocker.AsyncMock(return_value={'successful': [], 'failed': []})

        def _capturing_pipeline(*_args, **_kwargs):
            captured['session_id_at_pipeline'] = os.environ.get('YOSOI_SESSION_ID')
            return mock_pipe

        mocker.patch('yosoi.Pipeline', side_effect=_capturing_pipeline)

        result = runner.invoke(main, ['-u', 'https://example.com'])
        assert result.exit_code == 0, result.output
        assert captured['session_id_at_pipeline'] is None

    def test_origin_cli_passed_to_process_urls(self, runner, monkeypatch, mocker):
        """The CLI must pass origin='cli' through to Pipeline.process_urls so the
        Langfuse session is tagged with the CLI origin (vs. 'script' for API callers)."""
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
        mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')

        mock_pipe = mocker.MagicMock()
        mock_pipe.process_urls = mocker.AsyncMock(return_value={'successful': [], 'failed': []})
        mocker.patch('yosoi.Pipeline', return_value=mock_pipe)

        result = runner.invoke(main, ['-u', 'https://example.com'])
        assert result.exit_code == 0, result.output
        mock_pipe.process_urls.assert_awaited_once()
        kwargs = mock_pipe.process_urls.await_args.kwargs
        assert kwargs.get('origin') == 'cli'

    def test_atom_reads_flag_is_threaded_into_pipeline_policy(self, runner, monkeypatch, mocker):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
        mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')

        captured: dict[str, object] = {}
        mock_pipe = mocker.MagicMock()
        mock_pipe.process_urls = mocker.AsyncMock(return_value={'successful': [], 'failed': []})

        def _capturing_pipeline(*_args, **kwargs):
            captured.update(kwargs)
            return mock_pipe

        mocker.patch('yosoi.Pipeline', side_effect=_capturing_pipeline)

        result = runner.invoke(main, ['--atom-reads', '-u', 'https://example.com'])

        assert result.exit_code == 0, result.output
        assert captured['policy'].atom_reads is True
        assert 'Field atoms' in result.output
        assert 'armed, strict trust' in result.output

    @pytest.mark.parametrize('args', [[], ['scrape'], ['discover']])
    def test_atom_reads_is_exposed_in_cli_help(self, runner, args):
        result = runner.invoke(main, [*args, '--help'])

        assert result.exit_code == 0, result.output
        assert '--atom-reads' in result.output
