"""Tests for Click CLI."""

import importlib
import json

import click
import pytest
from click.testing import CliRunner

from yosoi.cli import SchemaParamType, main
from yosoi.models.defaults import NewsArticle, Product


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_pipeline(mocker):
    """Mock out heavy dependencies so the CLI can run without real config."""
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')

    mock_pipe = mocker.MagicMock()
    mock_pipe.process_urls = mocker.AsyncMock(return_value={'successful': [], 'failed': []})
    mock_pipe.show_summary = mocker.AsyncMock()
    mock_pipe.show_llm_stats = mocker.AsyncMock()
    mock_pipeline_cls = mocker.patch('yosoi.Pipeline', return_value=mock_pipe)
    mocker.patch(
        'yosoi.core.configs.YosoiConfig',
        return_value=mocker.MagicMock(
            llm=mocker.MagicMock(provider='groq', model_name='llama-3.3-70b-versatile'),
        ),
    )
    cli_main_module = importlib.import_module('yosoi.cli.main')
    mocker.patch.object(cli_main_module, 'console')

    return mock_pipe, mock_pipeline_cls


class TestHelpAndUsage:
    def test_help_shows_description(self, runner):
        result = runner.invoke(main, ['--help'])
        assert result.exit_code == 0
        assert 'Discover selectors' in result.output

    def test_no_args_shows_root_help(self, runner, mock_pipeline, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        result = runner.invoke(main, [])
        assert result.exit_code == 0
        assert 'Discover selectors' in result.output

    def test_bare_json_no_llm_threads_cache_only_pipeline(self, runner, mock_pipeline, mocker):
        _mock_pipe, pipeline_cls = mock_pipeline
        run_json = mocker.patch('yosoi.cli.main._run_json', mocker.AsyncMock(return_value=0))

        result = runner.invoke(main, ['--url', 'https://example.com', '--json', '--no-llm'])

        assert result.exit_code == 0, result.output
        assert pipeline_cls.call_args.kwargs['allow_llm'] is False
        run_json.assert_awaited_once()


class TestSearchCommand:
    @pytest.fixture(autouse=True)
    def _no_search_policy_env(self, mocker, monkeypatch):
        mocker.patch('yosoi.policy.files.discover_policy_files', return_value=())
        monkeypatch.delenv('YOSOI_SEARCH_BACKEND', raising=False)
        monkeypatch.delenv('YOSOI_SEARCH_REGION', raising=False)
        monkeypatch.delenv('YOSOI_SEARCH_SAFESEARCH', raising=False)
        monkeypatch.delenv('YOSOI_SEARCH_MAX_RESULTS', raising=False)
        monkeypatch.delenv('YOSOI_SEARCH_PAGE', raising=False)
        monkeypatch.delenv('YOSOI_SEARCH_TIMELIMIT', raising=False)

    def test_search_json_uses_operation_runner(self, runner, mocker):
        from yosoi.operations import SearchHit, SearchRequest, SearchResult

        run = mocker.patch(
            'yosoi.operations.run_search',
            mocker.AsyncMock(
                return_value=SearchResult(
                    request=SearchRequest(query='widgets', max_results=2),
                    hits=[
                        SearchHit(
                            rank=1,
                            title='One',
                            url='https://one.test',
                            snippet='First result',
                            backend='google,bing,brave',
                        )
                    ],
                    urls=['https://one.test'],
                )
            ),
        )

        result = runner.invoke(main, ['search', 'widgets', '--limit', '2', '--json'])

        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        assert doc['hits'][0]['url'] == 'https://one.test'
        request = run.await_args.args[0]
        assert request.query == 'widgets'
        assert request.max_results == 2

    def test_search_human_output_smoke(self, runner, mocker):
        from yosoi.operations import SearchHit, SearchRequest, SearchResult

        mocker.patch(
            'yosoi.operations.run_search',
            mocker.AsyncMock(
                return_value=SearchResult(
                    request=SearchRequest(query='widgets'),
                    hits=[
                        SearchHit(
                            rank=1,
                            title='One',
                            url='https://one.test',
                            snippet='First result',
                            backend='google,bing,brave',
                        )
                    ],
                    urls=['https://one.test'],
                )
            ),
        )

        result = runner.invoke(main, ['search', 'widgets'])

        assert result.exit_code == 0, result.output
        assert 'One' in result.output
        assert 'https://one.test' in result.output

    def test_search_no_query_usage_error(self, runner):
        result = runner.invoke(main, ['search'])

        assert result.exit_code != 0
        assert 'No search query provided' in result.output

    def test_search_dump_request(self, runner):
        result = runner.invoke(
            main,
            [
                'search',
                'cascading',
                'labs',
                '--backend',
                'google,bing,brave',
                '--region',
                'us-en',
                '--safesearch',
                'off',
                '--timelimit',
                'w',
                '--page',
                '2',
                '--limit',
                '3',
                '--dump-request',
            ],
        )

        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        assert doc['query'] == 'cascading labs'
        assert doc['backend'] == 'google,bing,brave'
        assert doc['region'] == 'us-en'
        assert doc['safesearch'] == 'off'
        assert doc['timelimit'] == 'w'
        assert doc['page'] == 2
        assert doc['max_results'] == 3

    def test_search_policy_file_supplies_defaults_and_flags_override(self, runner, mocker, tmp_path):
        from yosoi.operations import SearchResult

        run = mocker.patch(
            'yosoi.operations.run_search',
            mocker.AsyncMock(),
        )
        policy_file = tmp_path / 'policy.yaml'
        policy_file.write_text(
            'search:\n'
            '  backend: bing\n'
            '  region: wt-wt\n'
            '  safesearch: "off"\n'
            '  max_results: 7\n'
            '  page: 3\n'
            '  timelimit: m\n',
            encoding='utf-8',
        )

        def _result(request):
            return SearchResult(request=request)

        run.side_effect = _result

        result = runner.invoke(main, ['search', 'widgets', '--policy', str(policy_file), '--limit', '2', '--json'])

        assert result.exit_code == 0, result.output
        request = run.await_args.args[0]
        assert request.backend == 'bing'
        assert request.region == 'wt-wt'
        assert request.safesearch == 'off'
        assert request.timelimit == 'm'
        assert request.max_results == 2
        assert request.page == 3


class TestSchemaParamType:
    def test_exact_match(self):
        param_type = SchemaParamType()
        result = param_type.convert('NewsArticle', None, None)
        assert result is NewsArticle

    def test_case_insensitive_match_suggests_without_resolving(self):
        param_type = SchemaParamType()
        with pytest.raises(click.exceptions.BadParameter, match='Did you mean'):
            param_type.convert('product', None, None)

    def test_near_match_suggests_without_resolving(self):
        param_type = SchemaParamType()
        with pytest.raises(click.exceptions.BadParameter, match='Did you mean'):
            param_type.convert('Produc', None, None)

    def test_unknown_schema_fails(self):
        param_type = SchemaParamType()
        with pytest.raises(click.exceptions.BadParameter):
            param_type.convert('CompletelyWrong', None, None)


class TestSchemaFlag:
    def test_builtin_schema_passed_to_pipeline(self, runner, mock_pipeline, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        _, mock_pipeline_cls = mock_pipeline
        result = runner.invoke(main, ['-C', 'Product', '-u', 'https://example.com'])
        assert result.exit_code == 0, result.output

        call_kwargs = mock_pipeline_cls.call_args[1]
        assert call_kwargs['contract'] is Product  # resolved_contract passed to Pipeline


class TestSummaryFlag:
    def test_summary_calls_show_summary(self, runner, mock_pipeline, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        mock_pipe, _ = mock_pipeline
        result = runner.invoke(main, ['-s'])
        assert result.exit_code == 0, result.output
        mock_pipe.show_summary.assert_called_once()


class TestModelFlag:
    def test_model_flag_configures_llm(self, runner, mock_pipeline, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        mock_pipe, _ = mock_pipeline
        result = runner.invoke(main, ['-m', 'groq:llama-3.3-70b-versatile', '-u', 'https://example.com'])
        assert result.exit_code == 0, result.output
        mock_pipe.process_urls.assert_called_once()

    def test_repeated_url_flags_process_all_urls(self, runner, mock_pipeline, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        mock_pipe, _ = mock_pipeline
        result = runner.invoke(main, ['-u', 'https://a.example', '-u', 'https://b.example'])
        assert result.exit_code == 0, result.output
        assert mock_pipe.process_urls.call_args[0][0] == ['https://a.example', 'https://b.example']
        assert mock_pipe.process_urls.call_args.kwargs['workers'] == 2

    def test_model_flag_invalid_format(self, runner, mock_pipeline, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        result = runner.invoke(main, ['-m', 'badformat', '-u', 'https://example.com'])
        assert result.exit_code != 0
        assert 'provider:model-name' in result.output


class TestFileFlag:
    def test_file_flag_loads_urls(self, runner, mock_pipeline, monkeypatch, tmp_path):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        mock_pipe, _ = mock_pipeline

        url_file = tmp_path / 'urls.txt'
        url_file.write_text('https://a.com\nhttps://b.com\n')

        result = runner.invoke(main, ['-f', str(url_file)])
        assert result.exit_code == 0, result.output

        call_args = mock_pipe.process_urls.call_args
        assert call_args[0][0] == ['https://a.com', 'https://b.com']

    def test_file_not_found(self, runner, mock_pipeline, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        result = runner.invoke(main, ['-f', '/nonexistent/urls.txt'])
        assert result.exit_code != 0
        assert 'File not found' in result.output


class TestScanForContracts:
    def test_skips_tests_directory(self, tmp_path):
        """Contracts defined under tests/ must not appear in scan results."""
        from yosoi.cli.utils import scan_for_contracts

        user_file = tmp_path / 'my_schema.py'
        user_file.write_text('from yosoi.models.contract import Contract\n\nclass UserContract(Contract):\n    pass\n')

        tests_dir = tmp_path / 'tests'
        tests_dir.mkdir()
        test_file = tests_dir / 'test_something.py'
        test_file.write_text(
            'from yosoi.models.contract import Contract\n\nclass TestFixtureContract(Contract):\n    pass\n'
        )

        results = scan_for_contracts([str(tmp_path)])

        assert 'UserContract' in results
        assert 'TestFixtureContract' not in results

    def test_skips_examples_directory(self, tmp_path):
        """Contracts defined under examples/ must not appear in scan results."""
        from yosoi.cli.utils import scan_for_contracts

        user_file = tmp_path / 'schema.py'
        user_file.write_text('from yosoi.models.contract import Contract\n\nclass RealContract(Contract):\n    pass\n')

        examples_dir = tmp_path / 'examples'
        examples_dir.mkdir()
        example_file = examples_dir / 'demo.py'
        example_file.write_text(
            'from yosoi.models.contract import Contract\n\nclass DemoContract(Contract):\n    pass\n'
        )

        results = scan_for_contracts([str(tmp_path)])

        assert 'RealContract' in results
        assert 'DemoContract' not in results


class TestLimitFlag:
    def test_limit_truncates_urls(self, runner, mock_pipeline, monkeypatch, tmp_path):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        mock_pipe, _ = mock_pipeline

        url_file = tmp_path / 'urls.txt'
        url_file.write_text('https://a.com\nhttps://b.com\nhttps://c.com\n')

        result = runner.invoke(main, ['-f', str(url_file), '-l', '2'])
        assert result.exit_code == 0, result.output

        call_args = mock_pipe.process_urls.call_args
        assert call_args[0][0] == ['https://a.com', 'https://b.com']
