"""Tests for yosoi.cli.main — the main CLI command."""

import json
import os
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from yosoi.cli.main import _LEVEL_MAP, main


def _clear_policy_env(monkeypatch):
    for key in (
        'YOSOI_ATOM_READS',
        'YOSOI_ATOM_TRUST',
        'YOSOI_MODEL',
        'YOSOI_FORCE',
        'YOSOI_FETCHER_TYPE',
        'YOSOI_SELECTOR_LEVEL',
        'YOSOI_CROSS_ORIGIN_DOM',
        'YOSOI_DISCOVERY_MODE',
        'YOSOI_SEARCH_BACKEND',
        'YOSOI_SEARCH_REGION',
        'YOSOI_SEARCH_SAFESEARCH',
        'YOSOI_SEARCH_MAX_RESULTS',
        'YOSOI_SEARCH_PAGE',
        'YOSOI_SEARCH_TIMELIMIT',
        'LANGFUSE_PUBLIC_KEY',
        'LANGFUSE_SECRET_KEY',
        'LANGFUSE_HOST',
        'LANGFUSE_BASE_URL',
    ):
        monkeypatch.delenv(key, raising=False)
    import dotenv

    def _skip_dotenv() -> bool:
        return False

    monkeypatch.setattr(dotenv, 'load_dotenv', _skip_dotenv)


def _isolate_policy_home(monkeypatch) -> Path:
    home = Path.cwd() / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    return home


def _plain_help(output: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[│╭╮╰╯─]', ' ', output))


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

    def test_root_help_shows_effective_policy_values_from_global_and_local_policy(self, runner, monkeypatch):
        _clear_policy_env(monkeypatch)
        with runner.isolated_filesystem():
            home = _isolate_policy_home(monkeypatch)
            global_policy = home / '.config' / 'yosoi'
            global_policy.mkdir(parents=True)
            (global_policy / 'policy.yaml').write_text(
                'scrape:\n  max_concurrency: 8\n  fetcher_type: simple\n',
                encoding='utf-8',
            )
            Path('.yosoi').mkdir()
            Path('.yosoi/policy.yaml').write_text(
                'atom_reads: true\n'
                'scrape:\n'
                '  max_concurrency: 12\n'
                '  selector_level: xpath\n'
                'page:\n'
                '  fetcher_type: headless\n'
                'output:\n'
                '  formats: [json, csv]\n',
                encoding='utf-8',
            )

            result = runner.invoke(main, ['-h'], terminal_width=200)

        assert result.exit_code == 0, result.output
        help_text = _plain_help(result.output)
        assert 'policy: 12' in help_text
        assert 'policy: simple' in help_text
        assert 'policy: xpath' in help_text
        assert 'policy: json,csv' in help_text
        assert 'policy: true' in help_text
        assert 'policy: none' in help_text

    def test_search_help_shows_search_policy_values(self, runner, monkeypatch):
        _clear_policy_env(monkeypatch)
        with runner.isolated_filesystem():
            _isolate_policy_home(monkeypatch)
            Path('.yosoi').mkdir()
            Path('.yosoi/policy.yaml').write_text(
                'search:\n'
                '  backend: brave\n'
                '  region: wt-wt\n'
                '  safesearch: off\n'
                '  max_results: 7\n'
                '  page: 3\n'
                '  timelimit: w\n',
                encoding='utf-8',
            )

            result = runner.invoke(main, ['search', '--help'], terminal_width=200)

        assert result.exit_code == 0, result.output
        help_text = _plain_help(result.output)
        assert 'policy: 7' in help_text
        assert 'policy: brave' in help_text
        assert 'policy: wt-wt' in help_text
        assert 'policy: off' in help_text
        assert 'policy: 3' in help_text
        assert 'policy: w' in help_text

    def test_json_help_includes_policy_annotations(self, runner, monkeypatch):
        _clear_policy_env(monkeypatch)
        with runner.isolated_filesystem():
            _isolate_policy_home(monkeypatch)
            Path('.yosoi').mkdir()
            Path('.yosoi/policy.yaml').write_text('scrape:\n  max_concurrency: 8\n', encoding='utf-8')

            result = runner.invoke(main, ['--help', '--json'])

        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        workers = next(option for option in doc['options'] if option['name'] == 'workers')
        assert 'policy: 8' in workers['help']

    def test_help_renders_empty_policy_sequence_as_word(self, runner, monkeypatch):
        _clear_policy_env(monkeypatch)
        with runner.isolated_filesystem():
            _isolate_policy_home(monkeypatch)
            Path('.yosoi').mkdir()
            Path('.yosoi/policy.yaml').write_text('output:\n  formats: []\n', encoding='utf-8')

            result = runner.invoke(main, ['scrape', '-h'], terminal_width=200)

        assert result.exit_code == 0, result.output
        help_text = _plain_help(result.output)
        assert 'policy: empty' in help_text
        assert 'Policy: []' not in result.output
