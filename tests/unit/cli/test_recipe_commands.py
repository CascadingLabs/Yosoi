from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

from click.testing import CliRunner

from yosoi.cli.main import main
from yosoi.models.snapshot import SelectorSnapshot, SnapshotMap
from yosoi.models.spec import ContractSpec, FieldSpec


def test_recipe_mint_inspect_check_and_install(tmp_path) -> None:
    contract_path = tmp_path / 'contract.json'
    selectors_path = tmp_path / 'selectors.json'
    recipe_path = tmp_path / 'recipe.json'
    cache_dir = tmp_path / 'cache'

    contract = ContractSpec(name='Product', fields={'title': FieldSpec(yosoi_type='title')})
    contract_path.write_text(contract.model_dump_json(), encoding='utf-8')

    snap_map = SnapshotMap(
        url='https://example.com/products/1',
        domain='example.com',
        snapshots={'title': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
    )
    selectors_path.write_text(snap_map.model_dump_json(), encoding='utf-8')

    runner = CliRunner()
    mint = runner.invoke(
        main,
        [
            'recipe',
            'mint',
            '--contract',
            str(contract_path),
            '--selectors',
            str(selectors_path),
            '--out',
            str(recipe_path),
            '--json',
        ],
    )
    assert mint.exit_code == 0, mint.output
    minted = json.loads(mint.output)
    assert minted['recipe_id'].startswith('v1:sha256:')

    check = runner.invoke(main, ['recipe', 'check', str(recipe_path), '--recipe-id', minted['recipe_id'], '--json'])
    assert check.exit_code == 0, check.output

    inspect = runner.invoke(main, ['recipe', 'inspect', str(recipe_path), '--json'])
    assert inspect.exit_code == 0, inspect.output
    inspected = json.loads(inspect.output)
    assert inspected['contract'] == 'Product'
    assert inspected['domains'] == ['example.com']

    install = runner.invoke(main, ['recipe', 'install', str(recipe_path), '--cache-dir', str(cache_dir), '--json'])
    assert install.exit_code == 0, install.output
    installed = json.loads(install.output)
    assert installed['recipe_id'] == minted['recipe_id']


def test_recipe_mint_can_use_cached_selectors(tmp_path, monkeypatch) -> None:
    recipe_path = tmp_path / 'recipe.json'

    async def _fake_from_cache(*, contract, cache_url=None, domains=(), source_urls=(), url_patterns=()):
        return {
            'example.com': SnapshotMap(
                url=cache_url or 'https://example.com/',
                domain='example.com',
                snapshots={'title': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
            )
        }

    cli_main_module = importlib.import_module('yosoi.cli.main')
    monkeypatch.setattr(cli_main_module, '_recipe_selectors_from_cache', _fake_from_cache)

    result = CliRunner().invoke(
        main,
        [
            'recipe',
            'mint',
            '-C',
            '@NewsArticle',
            '--from-cache',
            'https://example.com/news/1',
            '-o',
            str(recipe_path),
            '--json',
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload['recipe_id'].startswith('v1:sha256:')
    assert recipe_path.exists()


def test_recipe_mint_out_can_be_directory(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / 'recipes'
    out_dir.mkdir()

    async def _fake_from_cache(*, contract, cache_url=None, domains=(), source_urls=(), url_patterns=()):
        return {
            'example.com': SnapshotMap(
                url='https://example.com/',
                domain='example.com',
                snapshots={'headline': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
            )
        }

    cli_main_module = importlib.import_module('yosoi.cli.main')
    monkeypatch.setattr(cli_main_module, '_recipe_selectors_from_cache', _fake_from_cache)

    result = CliRunner().invoke(
        main,
        ['recipe', 'mint', '-C', '@NewsArticle', '--domain', 'example.com', '-o', str(out_dir), '--json'],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    written = Path(payload['path'])
    assert written.parent == out_dir
    assert written.name.startswith('newsarticle-')
    assert written.name.endswith('.recipe.json')


def test_recipe_mint_can_auto_use_cache_by_domain(tmp_path, monkeypatch) -> None:
    recipe_path = tmp_path / 'recipe.json'
    seen = {}

    async def _fake_from_cache(*, contract, cache_url=None, domains=(), source_urls=(), url_patterns=()):
        seen['cache_url'] = cache_url
        seen['domains'] = domains
        seen['url_patterns'] = url_patterns
        return {
            'qscrape.dev': SnapshotMap(
                url='https://qscrape.dev/l1/news/article/',
                domain='qscrape.dev',
                snapshots={'headline': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
            )
        }

    cli_main_module = importlib.import_module('yosoi.cli.main')
    monkeypatch.setattr(cli_main_module, '_recipe_selectors_from_cache', _fake_from_cache)

    result = CliRunner().invoke(
        main,
        [
            'recipe',
            'mint',
            '-C',
            '@NewsArticle',
            '--domain',
            'qscrape.dev',
            '--url-pattern',
            'https://qscrape.dev/l1/news/article/*',
            '-o',
            str(recipe_path),
            '--json',
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen == {
        'cache_url': None,
        'domains': ('qscrape.dev',),
        'url_patterns': ('https://qscrape.dev/l1/news/article/*',),
    }
    assert recipe_path.exists()


def test_recipe_list_and_check_picker(tmp_path, monkeypatch) -> None:
    recipe_dir = tmp_path / '.yosoi' / 'recipes'
    recipe_dir.mkdir(parents=True)
    recipe_path = recipe_dir / 'product.recipe.json'
    contract = ContractSpec(name='Product', fields={'title': FieldSpec(yosoi_type='title')})
    snap_map = SnapshotMap(
        url='https://example.com/products/1',
        domain='example.com',
        snapshots={'title': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
    )
    from yosoi.models.recipe import Recipe

    recipe = Recipe(contract=contract, selectors={'example.com': snap_map})
    recipe_path.write_text(recipe.canonical_json(), encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    listed = CliRunner().invoke(main, ['recipe', 'list', '--json'])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)['recipes'][0]['path'] == '.yosoi/recipes/product.recipe.json'

    checked = CliRunner().invoke(main, ['recipe', 'check'], input='1\n')
    assert checked.exit_code == 0, checked.output
    assert 'Recipe OK' in checked.output


def test_recipe_install_remote_requires_recipe_id() -> None:
    result = CliRunner().invoke(main, ['recipe', 'install', 'gh:owner/repo/recipe.json@main'])

    assert result.exit_code != 0
    assert 'Remote recipe installs require --recipe-id' in result.output


def test_recipe_publish_gist_json_outputs_raw_and_html_urls(tmp_path, monkeypatch) -> None:
    recipe_path = tmp_path / 'recipe.json'
    contract = ContractSpec(name='Product', fields={'title': FieldSpec(yosoi_type='title')})
    snap_map = SnapshotMap(
        url='https://example.com/products/1',
        domain='example.com',
        snapshots={'title': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
    )
    from yosoi.models.recipe import Recipe

    recipe = Recipe(contract=contract, selectors={'example.com': snap_map})
    recipe_path.write_text(recipe.canonical_json(), encoding='utf-8')

    class _Response:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            return (
                b'{"html_url":"https://gist.github.com/user/abc123",'
                b'"files":{"product.recipe.json":'
                b'{"raw_url":"https://gist.githubusercontent.com/user/abc123/raw/product.recipe.json"}}}'
            )

    def _fake_urlopen(request, timeout):
        return _Response()

    monkeypatch.setenv('GITHUB_TOKEN', 'ghp_test')
    monkeypatch.setattr('yosoi.storage.recipe_store.urlopen', _fake_urlopen)

    result = CliRunner().invoke(
        main,
        ['recipe', 'publish', str(recipe_path), '--gist', '--filename', 'product.recipe.json', '--json'],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload['backend'] == 'gist'
    assert payload['url'] == 'https://gist.githubusercontent.com/user/abc123/raw/product.recipe.json'
    assert payload['raw_url'] == payload['url']
    assert payload['html_url'] == 'https://gist.github.com/user/abc123'
    assert payload['visibility'] == 'secret'


def test_recipe_gist_json_outputs_raw_and_html_urls(tmp_path, monkeypatch) -> None:
    recipe_path = tmp_path / 'recipe.json'
    contract = ContractSpec(name='Product', fields={'title': FieldSpec(yosoi_type='title')})
    snap_map = SnapshotMap(
        url='https://example.com/products/1',
        domain='example.com',
        snapshots={'title': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
    )
    from yosoi.models.recipe import Recipe

    recipe = Recipe(contract=contract, selectors={'example.com': snap_map})
    recipe_path.write_text(recipe.canonical_json(), encoding='utf-8')

    class _Response:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            return (
                b'{"html_url":"https://gist.github.com/user/abc123",'
                b'"files":{"product.recipe.json":'
                b'{"raw_url":"https://gist.githubusercontent.com/user/abc123/raw/product.recipe.json"}}}'
            )

    def _fake_urlopen(request, timeout):
        return _Response()

    monkeypatch.setenv('GITHUB_TOKEN', 'ghp_test')
    monkeypatch.setattr('yosoi.storage.recipe_store.urlopen', _fake_urlopen)

    result = CliRunner().invoke(
        main,
        ['recipe', 'gist', str(recipe_path), '--filename', 'product.recipe.json', '--json'],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload['url'] == 'https://gist.githubusercontent.com/user/abc123/raw/product.recipe.json'
    assert payload['raw_url'] == payload['url']
    assert payload['html_url'] == 'https://gist.github.com/user/abc123'
    assert payload['visibility'] == 'secret'
