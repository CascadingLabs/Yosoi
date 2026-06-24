"""Tests for CLI verb group: scrape / discover / cache status (CAS-121)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from yosoi.cli import main
from yosoi.cli.contract_param import ContractParamType
from yosoi.models.defaults import NewsArticle, Product


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def base_mocks(mocker):
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')


class TestSubcommands:
    def test_scrape_help(self, runner):
        result = runner.invoke(main, ['scrape', '--help'])
        assert result.exit_code == 0
        assert 'scrape' in result.output.lower() or 'replay' in result.output.lower()

    def test_discover_help(self, runner):
        result = runner.invoke(main, ['discover', '--help'])
        assert result.exit_code == 0

    def test_cache_help(self, runner):
        result = runner.invoke(main, ['cache', '--help'])
        assert result.exit_code == 0

    def test_cache_status_help(self, runner):
        result = runner.invoke(main, ['cache', 'status', '--help'])
        assert result.exit_code == 0


class TestContractParamType:
    """Three doors — @name, file.json, inline JSON."""

    def test_at_name_resolves_builtin(self):
        param = ContractParamType()
        result = param.convert('@NewsArticle', None, None)
        assert result is NewsArticle

    def test_at_name_resolves_case_insensitive(self):
        param = ContractParamType()
        result = param.convert('@product', None, None)
        assert result is Product

    def test_inline_json_resolves(self):
        param = ContractParamType()
        spec = NewsArticle.to_spec()
        raw = spec.model_dump_json()
        result = param.convert(raw, None, None)
        assert set(result.model_fields) == set(NewsArticle.model_fields)

    def test_json_file_resolves(self, tmp_path):
        param = ContractParamType()
        spec = NewsArticle.to_spec()
        fpath = tmp_path / 'contract.json'
        fpath.write_text(spec.model_dump_json())
        result = param.convert(str(fpath), None, None)
        assert set(result.model_fields) == set(NewsArticle.model_fields)

    def test_path_class_still_works(self, mocker):
        param = ContractParamType()
        mocker.patch('yosoi.cli.args.SchemaParamType.convert', return_value=NewsArticle)
        result = param.convert('mymodule:MyContract', None, None)
        assert result is NewsArticle


class TestTripleDoorFingerprint:
    """@name, file.json, and inline JSON all produce the same fingerprint."""

    def test_three_doors_same_fingerprint(self, tmp_path):
        param = ContractParamType()
        spec = Product.to_spec()
        fp_expected = spec.fingerprint

        # Door 1: @name
        cls_at = param.convert('@Product', None, None)
        assert cls_at.to_spec().fingerprint == fp_expected

        # Door 2: file.json
        fpath = tmp_path / 'product.json'
        fpath.write_text(spec.model_dump_json())
        cls_file = param.convert(str(fpath), None, None)
        assert cls_file.to_spec().fingerprint == fp_expected

        # Door 3: inline JSON
        cls_inline = param.convert(spec.model_dump_json(), None, None)
        assert cls_inline.to_spec().fingerprint == fp_expected


class TestScrapeReplayOnly:
    """scrape --json returns needs_discovery on cache miss."""

    def test_scrape_json_needs_discovery_on_miss(self, runner, mocker, base_mocks, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        import yosoi.storage as _store_pkg

        storage_instance = mocker.MagicMock()
        storage_instance.load_selectors = mocker.AsyncMock(return_value=None)
        mocker.patch.object(_store_pkg, 'SelectorStorage', return_value=storage_instance)

        result = runner.invoke(main, ['scrape', 'https://example.com', '--json'])
        json_lines = [ln for ln in result.output.splitlines() if ln.strip().startswith('{')]
        assert len(json_lines) >= 1, f'Expected JSON output, got: {result.output!r} err={result.exception}'
        doc = json.loads(json_lines[0])
        assert doc['type'] == 'needs_discovery'
        assert result.exit_code == 2  # NEEDS_DISCOVERY
        storage_instance.load_selectors.assert_awaited_once_with(
            'example.com', contract_sig=NewsArticle.to_spec().fingerprint
        )


class TestCacheStatus:
    def test_cache_status_no_cache(self, runner, mocker, base_mocks):
        import yosoi.storage as _store_pkg

        storage_mock = mocker.MagicMock()
        storage_mock.load_snapshots = mocker.AsyncMock(return_value=None)
        mocker.patch.object(_store_pkg, 'SelectorStorage', return_value=storage_mock)
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)

        result = runner.invoke(main, ['cache', 'status', 'example.com'])
        assert result.exit_code == 0
        assert 'No cached' in result.output or 'example.com' in result.output

    def test_cache_status_with_cache(self, runner, mocker, base_mocks):
        from datetime import datetime, timezone

        import yosoi.storage as _store_pkg
        from yosoi.models.snapshot import SelectorSnapshot, SnapshotStatus

        snap = SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc), status=SnapshotStatus.ACTIVE)
        storage_mock = mocker.MagicMock()
        storage_mock.load_snapshots = mocker.AsyncMock(return_value={'headline': snap})
        mocker.patch.object(_store_pkg, 'SelectorStorage', return_value=storage_mock)
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)

        result = runner.invoke(main, ['cache', 'status', 'example.com'])
        assert result.exit_code == 0
        assert 'headline' in result.output


class TestContractsCLI:
    """Basic smoke tests for yosoi contracts verbs."""

    def test_contracts_list_empty(self, runner, tmp_path):
        result = runner.invoke(main, ['contracts', 'list', '--store', str(tmp_path / 'c')])
        assert result.exit_code == 0
        assert 'No contracts' in result.output

    def test_contracts_add_and_list(self, runner, tmp_path):
        spec = NewsArticle.to_spec()
        spec_file = tmp_path / 'news.json'
        spec_file.write_text(spec.model_dump_json())
        store_dir = str(tmp_path / 'store')

        result = runner.invoke(main, ['contracts', 'add', str(spec_file), '--store', store_dir])
        assert result.exit_code == 0, result.output
        assert 'Added' in result.output

        result2 = runner.invoke(main, ['contracts', 'list', '--store', store_dir])
        assert result2.exit_code == 0
        assert 'NewsArticle' in result2.output

    def test_contracts_show(self, runner, tmp_path):
        spec = NewsArticle.to_spec()
        spec_file = tmp_path / 'news.json'
        spec_file.write_text(spec.model_dump_json())
        store_dir = str(tmp_path / 'store')
        runner.invoke(main, ['contracts', 'add', str(spec_file), '--store', store_dir])

        result = runner.invoke(main, ['contracts', 'show', 'NewsArticle', '--store', store_dir])
        assert result.exit_code == 0
        assert 'NewsArticle' in result.output

    def test_contracts_lint_valid(self, runner, tmp_path):
        spec = NewsArticle.to_spec()
        spec_file = tmp_path / 'news.json'
        spec_file.write_text(spec.model_dump_json())

        result = runner.invoke(main, ['contracts', 'lint', str(spec_file)])
        assert result.exit_code == 0
        assert 'valid' in result.output.lower()

    def test_contracts_migrate_noop(self, runner, tmp_path):
        spec = NewsArticle.to_spec()
        spec_file = tmp_path / 'news.json'
        spec_file.write_text(spec.model_dump_json())

        result = runner.invoke(main, ['contracts', 'migrate', str(spec_file)])
        assert result.exit_code == 0

    def test_discover_help(self, runner):
        result = runner.invoke(main, ['discover', '--help'])
        assert result.exit_code == 0

    def test_collect_urls_limit_error(self, runner, mocker, base_mocks):
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
        result = runner.invoke(main, ['-u', 'https://example.com', '-l', '0'])
        assert result.exit_code != 0

    def test_cache_status_url_input(self, runner, mocker, base_mocks):
        """Cache status accepts full URLs, not just domain names."""
        import yosoi.storage as _store_pkg

        storage_mock = mocker.MagicMock()
        storage_mock.load_snapshots = mocker.AsyncMock(return_value=None)
        mocker.patch.object(_store_pkg, 'SelectorStorage', return_value=storage_mock)
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)

        result = runner.invoke(main, ['cache', 'status', 'https://example.com'])
        assert result.exit_code == 0

    def test_cache_status_with_contract_and_missing_fields(self, runner, mocker, base_mocks):
        """Cache status shows missing fields when a contract is provided."""
        from datetime import datetime, timezone

        import yosoi.storage as _store_pkg
        from yosoi.models.snapshot import SelectorSnapshot, SnapshotStatus

        snap = SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc), status=SnapshotStatus.ACTIVE)
        storage_mock = mocker.MagicMock()
        storage_mock.load_snapshots = mocker.AsyncMock(return_value={'headline': snap})
        mocker.patch.object(_store_pkg, 'SelectorStorage', return_value=storage_mock)
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)

        result = runner.invoke(main, ['cache', 'status', 'example.com', '-C', '@Product'])
        assert result.exit_code == 0
        assert 'fingerprint' in result.output.lower() or 'Missing' in result.output or 'cached' in result.output.lower()
