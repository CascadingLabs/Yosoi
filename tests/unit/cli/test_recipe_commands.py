from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

import yosoi as ys
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


@pytest.mark.asyncio
async def test_recipe_selectors_from_cache_filters_by_source_url(monkeypatch) -> None:
    class Product(ys.Contract):
        title: str = ys.Title(description='Title')

    calls = []

    class _Storage:
        async def list_domains(self):
            return ['example.com', 'other.test']

        async def load_snapshots(self, domain, contract_sig=None, *, url=None):
            calls.append((domain, url))
            if domain == 'example.com' and url == 'https://example.com/products/1':
                return {'title': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))}
            if domain == 'example.com':
                return {'title': SelectorSnapshot(primary='.broad', discovered_at=datetime.now(timezone.utc))}
            return {'title': SelectorSnapshot(primary='.wrong-domain', discovered_at=datetime.now(timezone.utc))}

    monkeypatch.setattr('yosoi.storage.persistence.SelectorStorage', _Storage)
    cli_main_module = importlib.import_module('yosoi.cli.main')

    selectors = await cli_main_module._recipe_selectors_from_cache(
        contract=Product,
        source_urls=('https://example.com/products/1',),
    )

    assert list(selectors) == ['example.com']
    assert selectors['example.com'].url == 'https://example.com/products/1'
    assert selectors['example.com'].snapshots['title'].primary == 'h1'
    assert calls == [('example.com', 'https://example.com/products/1')]


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


def test_recipe_validate_cli_json_success_and_failure(tmp_path, monkeypatch) -> None:
    recipe_path = tmp_path / 'recipe.json'
    out_path = tmp_path / 'validated.recipe.json'
    contract = ContractSpec(name='Product', fields={'title': FieldSpec(yosoi_type='title')})
    snap_map = SnapshotMap(
        url='https://example.com/products/1',
        domain='example.com',
        snapshots={'title': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
    )
    from yosoi.models.recipe import Recipe, RecipeValidation
    from yosoi.recipe import RecipeValidateResult

    recipe = Recipe(contract=contract, selectors={'example.com': snap_map})
    recipe_path.write_text(recipe.canonical_json(), encoding='utf-8')

    def _fake_success(source, urls, **kwargs):
        updated = Recipe(
            contract=contract,
            selectors={'example.com': snap_map},
            validation=RecipeValidation(
                fixture_urls=list(urls),
                expected_shape={'title': 'str'},
                summary={'status': 'passed', 'record_count': 1},
            ),
        )
        out = Path(kwargs['out'])
        out.write_text(updated.canonical_json(), encoding='utf-8')
        return RecipeValidateResult(recipe=updated, validation=updated.validation, status='passed', path=out)

    monkeypatch.setattr('yosoi.recipe.validate_sync', _fake_success)
    ok = CliRunner().invoke(
        main,
        [
            'recipe',
            'validate',
            str(recipe_path),
            '--url',
            'https://example.com/products/1',
            '-o',
            str(out_path),
            '--json',
        ],
    )
    assert ok.exit_code == 0, ok.output
    assert json.loads(ok.output)['status'] == 'passed'
    assert out_path.exists()

    def _fake_failed(source, urls, **kwargs):
        failed = Recipe(
            contract=contract,
            selectors={'example.com': snap_map},
            validation=RecipeValidation(fixture_urls=list(urls), summary={'status': 'failed', 'record_count': 0}),
        )
        return RecipeValidateResult(recipe=failed, validation=failed.validation, status='failed')

    monkeypatch.setattr('yosoi.recipe.validate_sync', _fake_failed)
    bad = CliRunner().invoke(
        main, ['recipe', 'validate', str(recipe_path), '--url', 'https://example.com/products/1', '--json']
    )
    assert bad.exit_code == 1, bad.output
    assert json.loads(bad.output)['status'] == 'failed'

    recipe_path = tmp_path / 'recipe.json'
    contract_py = tmp_path / 'contract.py'
    compiled_json = tmp_path / 'contract.json'
    contract = ContractSpec(name='Product', fields={'title': FieldSpec(yosoi_type='title')})
    snap_map = SnapshotMap(
        url='https://example.com/products/1',
        domain='example.com',
        snapshots={'title': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
    )
    from yosoi.models.recipe import Recipe

    recipe = Recipe(contract=contract, selectors={'example.com': snap_map})
    recipe_path.write_text(recipe.canonical_json(), encoding='utf-8')

    runner = CliRunner()
    exported = runner.invoke(main, ['recipe', 'contract', 'export', str(recipe_path), '-o', str(contract_py), '--json'])
    assert exported.exit_code == 0, exported.output
    assert contract_py.exists()
    assert 'class Product(ys.Contract):' in contract_py.read_text(encoding='utf-8')

    compiled = runner.invoke(
        main,
        ['recipe', 'contract', 'compile', f'{contract_py}:Product', '-o', str(compiled_json), '--json'],
    )
    assert compiled.exit_code == 0, compiled.output
    assert compiled_json.exists()
    assert (
        ContractSpec.model_validate_json(compiled_json.read_text(encoding='utf-8')).fingerprint == contract.fingerprint
    )

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
        [
            'recipe',
            'publish',
            str(recipe_path),
            '--gist',
            '--filename',
            'product.recipe.json',
            '--allow-unvalidated',
            '--json',
        ],
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
        ['recipe', 'gist', str(recipe_path), '--filename', 'product.recipe.json', '--allow-unvalidated', '--json'],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload['url'] == 'https://gist.githubusercontent.com/user/abc123/raw/product.recipe.json'
    assert payload['raw_url'] == payload['url']
    assert payload['html_url'] == 'https://gist.github.com/user/abc123'
    assert payload['visibility'] == 'secret'


async def test_recipe_selectors_from_cache_domain_source_url_and_empty(monkeypatch) -> None:
    cli_main_module = importlib.import_module('yosoi.cli.main')

    class _Storage:
        async def list_domains(self):
            return ['listed.test']

        async def load_snapshots(self, domain, *, contract_sig=None, url=None):
            if domain == 'empty.test':
                return {}
            return {'title': SelectorSnapshot(primary=f'{domain} h1', discovered_at=datetime.now(timezone.utc))}

    monkeypatch.setattr('yosoi.storage.persistence.SelectorStorage', _Storage)

    class _Contract(ys.Contract):
        title: str = ys.Title()

    from_cache = await cli_main_module._recipe_selectors_from_cache(
        contract=_Contract,
        cache_url='https://example.com/products/1',
    )
    assert from_cache['example.com'].url == 'https://example.com/products/1'

    from_urls = await cli_main_module._recipe_selectors_from_cache(
        contract=_Contract,
        source_urls=('https://source.test/item',),
    )
    assert from_urls['source.test'].url == 'https://source.test/item'

    from_patterns = await cli_main_module._recipe_selectors_from_cache(
        contract=_Contract,
        domains=('pattern.test',),
        url_patterns=('https://pattern.test/products/*',),
    )
    assert from_patterns['pattern.test'].url == 'https://pattern.test/products'

    with pytest.raises(Exception, match='No cached selectors'):
        await cli_main_module._recipe_selectors_from_cache(contract=_Contract, domains=('empty.test',))


def test_recipe_path_picker_and_label_helpers(tmp_path, monkeypatch) -> None:
    cli_main_module = importlib.import_module('yosoi.cli.main')
    recipe = type(
        'RecipeLike',
        (),
        {
            'metadata': type('Meta', (), {'name': 'Product Cards!'})(),
            'contract': type('Spec', (), {'name': 'Product'})(),
            'recipe_id': 'v1:sha256:abcdef1234567890',
        },
    )()

    out_dir = tmp_path / 'recipes'
    out_dir.mkdir()
    assert cli_main_module._recipe_output_path(str(out_dir), recipe).name == 'product-cards-abcdef123456.recipe.json'
    assert cli_main_module._recipe_output_path(str(tmp_path / 'explicit.json'), recipe).name == 'explicit.json'
    assert cli_main_module._recipe_default_remote_path(recipe) == 'recipes/product-cards-abcdef123456.recipe.json'
    assert cli_main_module._recipe_source_url_for_domain('fallback.test', (), ()) == 'https://fallback.test/'

    good = tmp_path / '.yosoi' / 'recipes' / 'good.json'
    good.parent.mkdir(parents=True)
    contract = ContractSpec(name='Product', fields={'title': FieldSpec(yosoi_type='title')})
    snap_map = SnapshotMap(
        url='https://example.com/products/1',
        domain='example.com',
        snapshots={'title': SelectorSnapshot(primary='h1', discovered_at=datetime.now(timezone.utc))},
    )
    from yosoi.models.recipe import Recipe

    good.write_text(Recipe(contract=contract, selectors={'example.com': snap_map}).canonical_json(), encoding='utf-8')
    bad = good.parent / 'bad.json'
    bad.write_text('{nope', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    paths = cli_main_module._recipe_paths()
    assert paths == [Path('.yosoi/recipes/bad.json'), Path('.yosoi/recipes/good.json')]
    assert cli_main_module._recipe_summary(good)['contract'] == 'Product'
    assert cli_main_module._recipe_summary_or_error(bad)['status'] == 'error'
    assert cli_main_module._recipe_picker_label({'status': 'error', 'path': 'bad.json'}) == '(invalid) bad.json'
    label = cli_main_module._recipe_picker_label(
        {'contract': 'Product', 'domains': ['example.com'], 'recipe_id': 'v1:sha256:abcdef', 'path': 'good.json'}
    )
    assert 'Product [example.com]' in label


def test_recipe_source_pickers_json_noninteractive_and_publish_targets(monkeypatch) -> None:
    cli_main_module = importlib.import_module('yosoi.cli.main')
    monkeypatch.setattr(cli_main_module, '_recipe_paths', lambda: [Path('one.json'), Path('two.json')])
    monkeypatch.setattr(cli_main_module, '_render_recipe_picker', lambda _paths: None)
    monkeypatch.setattr(cli_main_module.sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(cli_main_module.click, 'prompt', lambda *_args, **_kwargs: 2)
    assert cli_main_module._pick_recipe_source() == 'two.json'

    with pytest.raises(Exception, match='SOURCE is required'):
        cli_main_module._pick_recipe_source(json_output=True)
    with pytest.raises(Exception, match='SOURCE is required'):
        cli_main_module._pick_recipe_sources(json_output=True)

    monkeypatch.setattr(cli_main_module, '_checkbox_picker', lambda _title, _options, _multi: [1, 0])
    assert cli_main_module._pick_publish_targets() == ['github', 'gist']
    assert cli_main_module._pick_recipe_sources() == ['two.json', 'one.json']

    monkeypatch.setattr(cli_main_module, '_recipe_paths', lambda: [])
    with pytest.raises(Exception, match='No local recipes'):
        cli_main_module._recipe_picker_paths()


def test_checkbox_picker_text_key_and_error_paths(monkeypatch) -> None:
    cli_main_module = importlib.import_module('yosoi.cli.main')
    text = cli_main_module._checkbox_picker_text('Pick', ['one', 'two'], {1}, 1, multi=True)
    assert '[x] 2. two' in text.plain
    assert 'a=all' in text.plain

    with pytest.raises(Exception, match='No options available'):
        cli_main_module._checkbox_picker('Pick', [], multi=True)
    monkeypatch.setattr(cli_main_module.sys.stdin, 'isatty', lambda: False)
    with pytest.raises(Exception, match='interactive terminal'):
        cli_main_module._checkbox_picker('Pick', ['one'], multi=True)

    chars = iter(['\x1b', '[', 'B'])
    monkeypatch.setattr(cli_main_module.click, 'getchar', lambda: next(chars))
    assert cli_main_module._recipe_picker_key() == '\x1b[B'
