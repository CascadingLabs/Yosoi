"""Tests for CLI verb group: scrape / discover / cache status (CAS-121)."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
import rich_click as click
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

    def test_short_help_alias_is_global(self, runner):
        assert runner.invoke(main, ['-h']).exit_code == 0
        assert runner.invoke(main, ['scrape', '-h']).exit_code == 0
        assert runner.invoke(main, ['policy', 'validate', '-h']).exit_code == 0

    def test_json_help_is_machine_readable_without_removing_human_rich_help(self, runner):
        human = runner.invoke(main, ['-h'])
        assert human.exit_code == 0
        assert 'Options' in human.output

        result = runner.invoke(main, ['-h', '--json'])
        assert result.exit_code == 0
        doc = json.loads(result.output)
        assert doc['type'] == 'help'
        assert doc['format'] == 'yosoi.cli.command.v1'
        assert 'commands' in doc
        assert '\x1b' not in doc['usage']

        alias_result = runner.invoke(main, ['-h', '-j'])
        assert alias_result.exit_code == 0
        assert json.loads(alias_result.output)['type'] == 'help'

    def test_subcommand_json_help(self, runner):
        result = runner.invoke(main, ['cache', 'status', '-h', '--json'])
        assert result.exit_code == 0
        doc = json.loads(result.output)
        assert doc['command_path'].endswith('cache status')
        assert any(opt['name'] == 'json_output' for opt in doc['options'])

    def test_json_usage_errors_are_machine_readable(self, runner, base_mocks, monkeypatch):
        monkeypatch.setenv('GROQ_KEY', 'test-key')
        result = runner.invoke(main, ['--json'])
        assert result.exit_code != 0
        doc = json.loads(result.stdout)
        assert doc['type'] == 'error'
        assert 'No URLs provided' in doc['message']

    def test_discover_help(self, runner):
        result = runner.invoke(main, ['discover', '--help'])
        assert result.exit_code == 0

    def test_cache_help(self, runner):
        result = runner.invoke(main, ['cache', '--help'])
        assert result.exit_code == 0

    def test_contract_alias_help(self, runner):
        result = runner.invoke(main, ['contract', '--help'])
        assert result.exit_code == 0
        assert 'local content-addressed contracts store' in result.output.lower()

    def test_contract_alias_is_hidden_from_root_help(self, runner):
        result = runner.invoke(main, ['-h'])
        assert result.exit_code == 0
        assert 'contracts' in result.output
        assert '│ contract ' not in result.output

    def test_cache_status_help(self, runner):
        result = runner.invoke(main, ['cache', 'status', '--help'])
        assert result.exit_code == 0


class TestContractParamType:
    """Three doors — @name, file.json, inline JSON."""

    def test_at_name_resolves_builtin(self):
        param = ContractParamType()
        result = param.convert('@NewsArticle', None, None)
        assert result is NewsArticle

    def test_at_name_case_insensitive_suggests_without_resolving(self):
        param = ContractParamType()
        with pytest.raises(click.exceptions.BadParameter, match='Did you mean'):
            param.convert('@product', None, None)

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

    def test_at_name_resolves_local_contract_store_alias(self, tmp_path, monkeypatch):
        from yosoi.storage.contracts_store import ContractStore

        monkeypatch.chdir(tmp_path)
        ContractStore().add(Product.to_spec(), name='ArticleTest')

        result = ContractParamType().convert('@ArticleTest', None, None)
        assert result.to_spec().fingerprint == Product.to_spec().fingerprint


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


class TestScrapeOperationSurface:
    """scrape --json builds ScrapeRequest and runs the canonical operation."""

    def test_scrape_json_uses_operation_runner(self, runner, mocker, base_mocks):
        from yosoi.operations import ScrapeResult, ScrapeUnitResult

        run = mocker.patch(
            'yosoi.operations.run_scrape',
            mocker.AsyncMock(
                return_value=ScrapeResult(
                    results=[
                        ScrapeUnitResult(
                            url='https://example.com',
                            contract='NewsArticle',
                            contract_fingerprint=NewsArticle.to_spec().fingerprint,
                            records=[{'title': 'Example'}],
                        )
                    ]
                )
            ),
        )

        result = runner.invoke(main, ['scrape', 'https://example.com', '--json'])
        assert result.exit_code == 0, result.output
        doc = json.loads(next(ln for ln in result.output.splitlines() if ln.strip().startswith('{')))
        assert doc['status'] == 'ok'
        assert doc['results'][0]['url'] == 'https://example.com'
        request = run.await_args.args[0]
        assert request.urls == ['https://example.com']
        assert request.contract_classes() == [NewsArticle]

    def test_scrape_dump_request_preserves_url_contract_grid(self, runner, base_mocks):
        result = runner.invoke(
            main,
            ['scrape', 'https://example.com', '--contract', '@NewsArticle', '--contract', '@Product', '--dump-request'],
        )
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output[result.output.index('{') :])
        assert doc['urls'] == ['https://example.com']
        assert len(doc['contracts']) == 2


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

    def test_cache_status_json_no_cache(self, runner, mocker, base_mocks):
        import yosoi.storage as _store_pkg

        storage_mock = mocker.MagicMock()
        storage_mock.load_snapshots = mocker.AsyncMock(return_value=None)
        mocker.patch.object(_store_pkg, 'SelectorStorage', return_value=storage_mock)
        mocker.patch('yosoi.utils.files.is_initialized', return_value=True)

        result = runner.invoke(main, ['cache', 'status', 'example.com', '--json'])
        assert result.exit_code == 0
        assert json.loads(result.output) == {
            'cached': False,
            'domain': 'example.com',
            'fields': [],
            'target': 'example.com',
            'target_kind': 'domain',
            'type': 'cache.status',
        }

    def test_cache_status_contract_only_json(self, runner, mocker, base_mocks):
        from yosoi.storage.cache_metrics_sqlite import ContractCacheMetrics

        store_cls = mocker.patch('yosoi.storage.cache_metrics_sqlite.SQLiteCacheMetricsStore')
        store_cls.return_value.summarize_contract = mocker.AsyncMock(
            return_value=ContractCacheMetrics(
                contract_fingerprint=Product.to_spec().fingerprint,
                domains=[],
                routes=[],
                fields=[],
                field_metrics=[],
            )
        )

        result = runner.invoke(main, ['cache', 'status', '-C', '@Product', '-j'])
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        assert doc['target_kind'] == 'contract'
        assert doc['contract'] == 'Product'
        assert doc['cached'] is False
        assert doc['domains'] == []

    def test_cache_status_contract_target_json(self, runner, mocker, base_mocks):
        from yosoi.storage.cache_metrics_sqlite import CacheFieldMetric, ContractCacheMetrics

        store_cls = mocker.patch('yosoi.storage.cache_metrics_sqlite.SQLiteCacheMetricsStore')
        store_cls.return_value.summarize_contract = mocker.AsyncMock(
            return_value=ContractCacheMetrics(
                contract_fingerprint=Product.to_spec().fingerprint,
                domains=['example.com'],
                routes=['/products/'],
                fields=['name'],
                field_metrics=[
                    CacheFieldMetric(
                        contract_fingerprint=Product.to_spec().fingerprint,
                        field_name='name',
                        domain='example.com',
                        route_signature='/products/',
                        selector_level='all',
                        source_url='https://example.com/products/1',
                        status='active',
                        discovered_at=None,
                        last_verified_at=None,
                        last_failed_at=None,
                        failure_count=0,
                    )
                ],
            )
        )

        result = runner.invoke(main, ['cache', 'status', '@Product', '--json'])
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        assert doc['target_kind'] == 'contract'
        assert doc['contract'] == 'Product'
        assert doc['domains'] == ['example.com']
        assert doc['field_metrics'][0]['field_name'] == 'name'

    def test_cache_status_url_target_routes_to_domain_and_route(self, runner, mocker, base_mocks):
        import yosoi.storage as _store_pkg

        storage_mock = mocker.MagicMock()
        storage_mock.load_snapshots = mocker.AsyncMock(return_value=None)
        mocker.patch.object(_store_pkg, 'SelectorStorage', return_value=storage_mock)

        result = runner.invoke(main, ['cache', 'status', 'https://www.example.com/l1/news/article/?x=1', '--json'])
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        assert doc['target_kind'] == 'url'
        assert doc['domain'] == 'example.com'
        assert doc['route'] == '/l1/news/article/'
        storage_mock.load_snapshots.assert_awaited_once_with('example.com', contract_sig=None)

    def test_cache_status_ambiguous_target_requires_explicit_flag(self, runner, base_mocks):
        result = runner.invoke(main, ['cache', 'status', 'ArticleTest'])
        assert result.exit_code != 0
        assert '--contract/--domain/--url/--route' in result.output

    def test_cache_status_explicit_domain_fallback(self, runner, mocker, base_mocks):
        import yosoi.storage as _store_pkg

        storage_mock = mocker.MagicMock()
        storage_mock.load_snapshots = mocker.AsyncMock(return_value=None)
        mocker.patch.object(_store_pkg, 'SelectorStorage', return_value=storage_mock)

        result = runner.invoke(main, ['cache', 'status', '--domain', 'internal-host', '--json'])
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        assert doc['target_kind'] == 'domain'
        assert doc['domain'] == 'internal-host'

    def test_cache_status_rejects_positional_plus_explicit_target(self, runner, base_mocks):
        result = runner.invoke(main, ['cache', 'status', 'example.com', '--domain', 'example.com'])
        assert result.exit_code != 0
        assert 'Use either positional TARGET' in result.output

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

    def test_contracts_list_shows_builtins_without_local_store(self, runner, tmp_path):
        result = runner.invoke(main, ['contracts', 'list', '--store', str(tmp_path / 'c')])
        assert result.exit_code == 0
        assert 'Available contracts' in result.output
        assert 'NewsArticle' in result.output

    def test_contracts_list_json(self, runner, tmp_path):
        result = runner.invoke(main, ['contracts', 'list', '--store', str(tmp_path / 'c'), '--json'])
        assert result.exit_code == 0
        doc = json.loads(result.output)
        assert doc['type'] == 'contracts.list'
        assert any(item['name'] == 'NewsArticle' for item in doc['builtins'])

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


@dataclass
class _CrawlSummary:
    pages: int = 1
    records: int = 2


class TestCoverageSensitiveCliBranches:
    def test_crawl_dump_request_builds_axes(self, runner, base_mocks):
        result = runner.invoke(
            main,
            [
                'crawl',
                'https://a.example',
                '--url',
                'https://b.example',
                '-C',
                '@Product',
                '--limit',
                '1',
                '--dump-request',
            ],
        )
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output[result.output.index('{') :])
        assert doc['seeds'] == ['https://a.example', 'https://b.example']
        assert doc['limit'] == 1
        assert len(doc['contracts']) == 1

    def test_crawl_json_success_and_error(self, runner, mocker, base_mocks):
        from yosoi.operations import CrawlResult

        run = mocker.patch(
            'yosoi.operations.run_crawl', mocker.AsyncMock(return_value=CrawlResult(summary={'pages': 1}))
        )
        ok = runner.invoke(main, ['crawl', 'https://example.com', '--json'])
        assert ok.exit_code == 0, ok.output
        assert json.loads(ok.output)['summary'] == {'pages': 1}
        assert run.await_args.args[0].progress is False

        mocker.patch('yosoi.operations.run_crawl', mocker.AsyncMock(side_effect=RuntimeError('boom')))
        bad = runner.invoke(main, ['crawl', 'https://example.com', '--json'])
        assert bad.exit_code == 1
        assert json.loads(bad.output)['message'] == 'boom'

    def test_crawl_human_executes_and_request_file_errors(self, runner, mocker, base_mocks, tmp_path):
        execute = mocker.patch('yosoi.operations.execute_crawl', mocker.AsyncMock(return_value=_CrawlSummary()))
        ok = runner.invoke(main, ['crawl', 'https://example.com'])
        assert ok.exit_code == 0, ok.output
        assert 'pages' in ok.output
        assert execute.await_args.args[0].seeds == ['https://example.com']

        bad_request = tmp_path / 'request.json'
        bad_request.write_text('{bad')
        bad = runner.invoke(main, ['crawl', '--request', str(bad_request)])
        assert bad.exit_code != 0
        assert 'Cannot parse CrawlRequest' in bad.output

    def test_policy_commands_cover_success_and_error_json(self, runner, tmp_path):
        from yosoi.policy import Policy

        policy_file = tmp_path / 'policy.json'
        policy_file.write_text(Policy().model_dump_json())

        defaults = runner.invoke(main, ['policy', 'defaults', '--crawl'])
        assert defaults.exit_code == 0, defaults.output
        assert 'crawl' in defaults.output

        validate = runner.invoke(main, ['policy', 'validate', str(policy_file), '--json'])
        assert validate.exit_code == 0, validate.output
        assert json.loads(validate.output)['status'] == 'ok'

        inspect = runner.invoke(main, ['policy', 'inspect', str(policy_file)])
        assert inspect.exit_code == 0, inspect.output
        assert json.loads(inspect.output)['model'] is None

        bad_file = tmp_path / 'bad.json'
        bad_file.write_text('{bad')
        invalid = runner.invoke(main, ['policy', 'validate', str(bad_file), '--json'])
        assert invalid.exit_code == 1
        assert json.loads(invalid.output)['type'] == 'error'

    def test_cache_status_contract_conflict_route_and_all_fields(self, runner, mocker, base_mocks):
        from datetime import datetime, timezone

        import yosoi.storage as _store_pkg
        from yosoi.models.snapshot import SelectorSnapshot, SnapshotStatus

        conflict = runner.invoke(main, ['cache', 'status', '@Product', '-C', '@NewsArticle'])
        assert conflict.exit_code != 0
        assert 'conflicts' in conflict.output

        route = runner.invoke(main, ['cache', 'status', '--route', '/products'])
        assert route.exit_code == 0, route.output
        assert 'Route' in route.output

        snap = SelectorSnapshot(primary='x', discovered_at=datetime.now(timezone.utc), status=SnapshotStatus.ACTIVE)
        storage_mock = mocker.MagicMock()
        storage_mock.load_snapshots = mocker.AsyncMock(
            return_value=dict.fromkeys(Product.discovery_field_names(), snap)
        )
        mocker.patch.object(_store_pkg, 'SelectorStorage', return_value=storage_mock)
        cached = runner.invoke(main, ['cache', 'status', 'example.com', '-C', '@Product'])
        assert cached.exit_code == 0, cached.output
        assert 'All contract fields cached' in cached.output

    def test_contracts_json_alias_lint_and_migrate_branches(self, runner, mocker, tmp_path):
        spec = Product.to_spec()
        spec_file = tmp_path / 'product.json'
        spec_file.write_text(spec.model_dump_json())
        store_dir = str(tmp_path / 'store')

        added = runner.invoke(
            main, ['contracts', 'add', str(spec_file), '--name', 'LocalProduct', '--store', store_dir, '--json']
        )
        assert added.exit_code == 0, added.output
        assert json.loads(added.output)['alias'] == 'LocalProduct'

        listed = runner.invoke(main, ['contracts', 'list', '--store', store_dir])
        assert listed.exit_code == 0, listed.output
        assert 'Local aliases' in listed.output

        lint_ok = runner.invoke(main, ['contracts', 'lint', str(spec_file), '--json'])
        assert lint_ok.exit_code == 0, lint_ok.output
        assert json.loads(lint_ok.output)['status'] == 'ok'

        mocker.patch('yosoi.storage.contracts_store.ContractStore.lint', return_value=['bad selector'])
        lint_bad = runner.invoke(main, ['contracts', 'lint', str(spec_file), '--json'])
        assert lint_bad.exit_code == 1
        assert json.loads(lint_bad.output)['errors'] == ['bad selector']

        migrated = runner.invoke(main, ['contracts', 'migrate', str(spec_file), '--in-place', '--json'])
        assert migrated.exit_code == 0, migrated.output
        assert json.loads(migrated.output)['in_place'] is True

    def test_contracts_show_unknown_and_parse_errors(self, runner, tmp_path):
        missing = runner.invoke(main, ['contracts', 'show', 'NoSuchContract'])
        assert missing.exit_code != 0

        bad = tmp_path / 'bad.json'
        bad.write_text('{bad')
        for command in ('add', 'lint', 'migrate'):
            result = runner.invoke(main, ['contracts', command, str(bad)])
            assert result.exit_code != 0
            assert 'Cannot parse' in result.output
