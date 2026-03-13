"""Tests for Click CLI."""

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
    mock_pipeline_cls = mocker.patch('yosoi.Pipeline', return_value=mock_pipe)
    mocker.patch(
        'yosoi.config.YosoiConfig',
        return_value=mocker.MagicMock(
            llm=mocker.MagicMock(provider='groq', model_name='llama-3.3-70b-versatile'),
        ),
    )
    mocker.patch('yosoi.cli.console')

    return mock_pipe, mock_pipeline_cls


class TestHelpAndUsage:
    def test_help_shows_description(self, runner):
        result = runner.invoke(main, ['--help'])
        assert result.exit_code == 0
        assert 'Discover selectors' in result.output

    def test_no_args_shows_usage_error(self, runner, mock_pipeline, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        result = runner.invoke(main, [])
        assert result.exit_code != 0
        assert 'No URLs provided' in result.output


class TestSchemaParamType:
    def test_exact_match(self):
        param_type = SchemaParamType()
        result = param_type.convert('NewsArticle', None, None)
        assert result is NewsArticle

    def test_case_insensitive_match(self):
        param_type = SchemaParamType()
        result = param_type.convert('product', None, None)
        assert result is Product

    def test_fuzzy_match(self):
        param_type = SchemaParamType()
        result = param_type.convert('Produc', None, None)
        assert result is Product

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
        result = runner.invoke(main, ['-m', 'groq/llama-3.3-70b-versatile', '-u', 'https://example.com'])
        assert result.exit_code == 0, result.output
        mock_pipe.process_urls.assert_called_once()

    def test_model_flag_invalid_format(self, runner, mock_pipeline, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        result = runner.invoke(main, ['-m', 'badformat', '-u', 'https://example.com'])
        assert result.exit_code != 0
        assert 'provider/model-name' in result.output


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
