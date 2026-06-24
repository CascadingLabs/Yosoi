"""Tests for CLI structured I/O, exit codes, and --json flag (CAS-120)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from yosoi.cli import exit_codes, main
from yosoi.models.needs_discovery import NeedsDiscovery


class TestExitCodes:
    def test_constants_are_distinct(self):
        codes = [
            exit_codes.RECORDS,
            exit_codes.ERROR,
            exit_codes.NEEDS_DISCOVERY,
            exit_codes.FETCH_FAILED,
            exit_codes.VALIDATION_FAILED,
        ]
        assert len(codes) == len(set(codes))

    def test_records_is_zero(self):
        assert exit_codes.RECORDS == 0

    def test_error_is_one(self):
        assert exit_codes.ERROR == 1

    def test_needs_discovery_is_two(self):
        assert exit_codes.NEEDS_DISCOVERY == 2


class TestNeedsDiscovery:
    def test_round_trip_json(self):
        nd = NeedsDiscovery(domain='example.com', contract_fingerprint='abc123', fields=['headline', 'author'])
        parsed = json.loads(nd.to_exit_json())
        assert parsed['type'] == 'needs_discovery'
        assert parsed['domain'] == 'example.com'
        assert parsed['contract_fingerprint'] == 'abc123'
        assert 'headline' in parsed['fields']

    def test_default_type_field(self):
        nd = NeedsDiscovery(domain='x.com', contract_fingerprint='fp', fields=[])
        assert nd.type == 'needs_discovery'

    def test_message_is_present(self):
        nd = NeedsDiscovery(domain='x.com', contract_fingerprint='fp', fields=[])
        assert 'discover' in nd.message.lower()


def _json_lines(output: str) -> list[dict]:
    """Extract valid JSON lines from mixed stdout+stderr output."""
    import contextlib

    result = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith('{'):
            with contextlib.suppress(json.JSONDecodeError):
                result.append(json.loads(stripped))
    return result


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_pipeline_json(mocker):
    """Mock pipeline for --json mode tests."""
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')

    item = {'headline': 'Test', 'author': 'Me', 'date': '2026-01-01'}

    async def _scrape(*args, **kwargs):
        yield item

    mock_pipe = mocker.MagicMock()
    mock_pipe.scrape = _scrape
    mock_pipe.__aenter__ = mocker.AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = mocker.AsyncMock(return_value=False)

    mocker.patch('yosoi.Pipeline', return_value=mock_pipe)
    return mock_pipe


class TestJsonFlag:
    def test_json_flag_emits_ndjson_to_stdout(self, runner, mock_pipeline_json, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        result = runner.invoke(main, ['--json', '-u', 'https://example.com'])
        records = _json_lines(result.output)
        assert len(records) >= 1, f'Expected JSON record in output, got: {result.output!r}'
        assert records[0].get('headline') == 'Test'

    def test_json_flag_exit_code_zero_on_records(self, runner, mock_pipeline_json, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        result = runner.invoke(main, ['--json', '-u', 'https://example.com'])
        assert result.exit_code == exit_codes.RECORDS

    def test_json_error_emits_error_json(self, runner, mocker, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
        mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')

        async def _raise(*a, **kw):
            raise RuntimeError('boom')
            yield  # make it a generator to satisfy AsyncGenerator type expectations

        mock_pipe = mocker.MagicMock()
        mock_pipe.scrape = _raise
        mock_pipe.__aenter__ = mocker.AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = mocker.AsyncMock(return_value=False)
        mocker.patch('yosoi.Pipeline', return_value=mock_pipe)

        result = runner.invoke(main, ['--json', '-u', 'https://example.com'])
        assert result.exit_code == exit_codes.ERROR
        err_docs = _json_lines(result.output)
        assert len(err_docs) >= 1, f'Expected error JSON, got: {result.output!r}'
        assert err_docs[0]['type'] == 'error'
        assert 'boom' in err_docs[0]['message']
