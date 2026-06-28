from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

import yosoi as ys


class Product(ys.Contract):
    title: str = ys.Title(description='Title')


class OtherProduct(ys.Contract):
    name: str = ys.Title(description='Different')


def test_public_recipe_api_mints_and_consumes_pieces(tmp_path) -> None:
    selectors = ys.recipe.selector_map(
        'https://example.com/products/1',
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        title='h1',
    )
    path = tmp_path / 'recipe.json'

    recipe = ys.recipe.mint(Product, selectors=selectors, out=path, validation={'fixture_urls': [selectors.url]})
    loaded = ys.recipe.load(str(path), recipe_id=recipe.recipe_id)

    assert loaded.to_contract().__name__ == 'Product'
    assert loaded.selectors_for('www.example.com') is not None
    assert loaded.fixture_urls() == ['https://example.com/products/1']


def test_recipe_contract_python_renderer_round_trips(tmp_path) -> None:
    recipe = ys.recipe.mint(Product, selectors=ys.recipe.selector_map('https://example.com/1', title='h1'))
    contract_py = tmp_path / 'contract.py'
    contract_py.write_text(ys.recipe.render_contract_py(recipe), encoding='utf-8')

    compiled = ys.recipe.compile_contract(f'{contract_py}:Product')

    assert compiled.name == 'Product'
    assert compiled.fingerprint == recipe.contract.fingerprint
    assert 'class Product(ys.Contract):' in contract_py.read_text(encoding='utf-8')


def test_recipe_contract_python_renderer_preserves_root_doc_and_validators(tmp_path) -> None:
    spec = ys.ContractSpec(
        name='RootedProduct',
        doc='Doc with """ triple quotes',
        fields={'title': ys.recipe.compile_contract(Product).fields['title']},
        root=ys.SelectorEntry(type='css', value='main.product').model_dump(mode='json'),
        validators='tests.unit.test_recipe_api:Product',
    )
    contract_py = tmp_path / 'rooted_contract.py'
    contract_py.write_text(ys.recipe.render_contract_py(spec), encoding='utf-8')

    compiled = ys.recipe.compile_contract(f'{contract_py}:RootedProduct')

    assert compiled.fingerprint == spec.fingerprint
    rendered = contract_py.read_text(encoding='utf-8')
    assert 'root = ys.SelectorEntry.model_validate' in rendered
    assert '_validators_cls = _load_ref' in rendered


def test_recipe_a3node_provenance_does_not_affect_identity() -> None:
    node = {
        'scope': {
            'scope_key': 'a3scope:v1:test',
            'domain': 'example.com',
            'page_profile': '/products/',
            'intent': 'fetch',
            'browser_fingerprint': 'default',
            'route_signature': '/products/',
        },
        'acts': [{'kind': 'cookie', 'cycles': 1}],
        'provenance': {'replay_count': 1, 'discovered_at': '2026-01-01T00:00:00Z'},
    }
    other = node | {'provenance': {'replay_count': 99, 'discovered_at': '2026-02-01T00:00:00Z'}}

    first = ys.recipe.mint(
        Product, selectors=ys.recipe.selector_map('https://example.com/products/1', title='h1'), a3nodes=[node]
    )
    second = ys.recipe.mint(
        Product, selectors=ys.recipe.selector_map('https://example.com/products/1', title='h1'), a3nodes=[other]
    )

    assert first.recipe_id == second.recipe_id


@pytest.mark.asyncio
async def test_recipe_a3nodes_export_and_seed(monkeypatch) -> None:
    from yosoi.models.selectors import SelectorEntry
    from yosoi.storage.a3node import A3Node, ActRecord

    node = A3Node(
        domain='example.com',
        acts=[ActRecord(kind='cookie', cycles=1, target=SelectorEntry(type='css', value='button.accept'))],
        discovered_at='2026-01-01T00:00:00Z',
        scope_key='a3scope:v1:test',
        page_profile='/products/1',
        intent='sig:test',
        browser_fingerprint='headless:default',
        route_signature='/products/1',
    )
    other_route = A3Node(
        domain='example.com',
        acts=[ActRecord(kind='popup', cycles=1, target=SelectorEntry(type='css', value='button.close'))],
        discovered_at='2026-01-01T00:00:00Z',
        scope_key='a3scope:v1:other',
        page_profile='/news/',
        intent='sig:test',
        browser_fingerprint='headless:default',
        route_signature='/news/',
    )
    saved = {}

    class _Storage:
        async def load_all(self):
            return {node.scope_key: node, other_route.scope_key: other_route}

        async def save(self, scope, acts):
            saved['scope'] = scope
            saved['acts'] = acts

    monkeypatch.setattr('yosoi.storage.a3node.A3NodeStorage', lambda: _Storage())

    exported = await ys.recipe.export_a3nodes(source_urls=['https://example.com/products/1'])
    recipe = ys.recipe.mint(
        Product, selectors=ys.recipe.selector_map('https://example.com/products/1', title='h1'), a3nodes=exported
    )
    await ys.recipe._seed_recipe_a3nodes(recipe)

    assert len(exported) == 1
    assert exported[0].schema_version == 'yosoi.a3node.v1'
    assert exported[0].scope.route_signature == '/products/1'
    assert saved['scope'].scope_key == 'a3scope:v1:test'
    assert saved['acts'][0].target.value == 'button.accept'

    recipe = ys.recipe.mint(Product, selectors=ys.recipe.selector_map('https://example.com/1', title='h1'))
    captured = {}

    def _fake_pr(artifact, *, repo, path, branch='main', token=None, message=None, pr_branch=None):
        from yosoi.storage.recipe_store import GitHubPrPublishResult

        captured.update({'repo': repo, 'path': path, 'branch': branch, 'direct': False})
        return GitHubPrPublishResult(
            html_url='https://github.com/owner/repo/pull/1',
            branch='yosoi/product-abc',
            fork_repo='user/repo',
            path=path,
        )

    monkeypatch.setattr(ys.recipe, 'publish_recipe_github_pr', _fake_pr)

    results = ys.recipe.publish(recipe, repo='https://github.com/owner/repo', allow_unvalidated=True)

    assert results[0].backend == 'github'
    assert results[0].mode == 'pr'
    assert results[0].url == 'https://github.com/owner/repo/pull/1'
    assert captured['repo'] == 'https://github.com/owner/repo'
    assert captured['path'].startswith('recipes/example.com/product-')


def test_recipe_publish_can_target_gist_and_direct_github(monkeypatch) -> None:
    recipe = ys.recipe.mint(Product, selectors=ys.recipe.selector_map('https://example.com/1', title='h1'))

    def _fake_gist(artifact, *, filename=None, description=None, public=False, token=None):
        from yosoi.storage.recipe_store import GistPublishResult

        return GistPublishResult(
            raw_url='https://gist.githubusercontent.com/user/id/raw/product.recipe.json',
            html_url='https://gist.github.com/user/id',
            filename=filename or 'product.recipe.json',
            public=public,
        )

    def _fake_direct(artifact, *, repo, path, branch='main', token=None, message=None):
        return f'https://github.com/owner/repo/blob/{branch}/{path}'

    monkeypatch.setattr(ys.recipe, 'publish_recipe_gist', _fake_gist)
    monkeypatch.setattr(ys.recipe, 'publish_recipe_github', _fake_direct)

    results = ys.recipe.publish(
        recipe, repo='owner/repo', gist=True, direct=True, filename='product.recipe.json', allow_unvalidated=True
    )

    assert [result.backend for result in results] == ['gist', 'github']
    assert results[0].raw_url == 'https://gist.githubusercontent.com/user/id/raw/product.recipe.json'
    assert results[1].mode == 'direct'


@pytest.mark.asyncio
async def test_recipe_run_seeds_selectors_and_scrapes(monkeypatch) -> None:
    recipe = ys.recipe.mint(Product, selectors=ys.recipe.selector_map('https://example.com/1', title='h1'))
    captured = {}

    async def _fake_seed(artifact, urls):
        captured['seed'] = (artifact.recipe_id, urls)

    async def _fake_scrape(url, contract, **kwargs):
        captured['scrape'] = (url, contract.__name__, kwargs)
        return {'ok': True}

    monkeypatch.setattr(ys.recipe, '_seed_recipe_selectors', _fake_seed)
    monkeypatch.setattr('yosoi.api.scrape', _fake_scrape)

    result = await ys.recipe.run(recipe, 'https://example.com/2')

    assert result == {'ok': True}
    assert captured['seed'] == (recipe.recipe_id, ['https://example.com/2'])
    assert captured['scrape'][1] == 'Product'
    assert captured['scrape'][2]['allow_llm'] is False


@pytest.mark.asyncio
async def test_recipe_validate_builds_evidence_and_can_write(tmp_path, monkeypatch) -> None:
    recipe_path = tmp_path / 'recipe.json'
    ys.recipe.mint(
        Product,
        selectors=ys.recipe.selector_map('https://example.com/1', title='h1'),
        out=recipe_path,
    )

    @dataclass
    class _Unit:
        records: list[dict[str, object]]
        error: str | None = None

    @dataclass
    class _Result:
        status: str
        results: list[_Unit]

    async def _fake_run(*args, **kwargs):
        return _Result(status='ok', results=[_Unit(records=[{'title': 'Hello'}])])

    monkeypatch.setattr(ys.recipe, 'run', _fake_run)

    result = await ys.recipe.validate(str(recipe_path), ['https://example.com/1'], write=True)

    assert result.status == 'passed'
    assert result.path == recipe_path
    assert result.validation.summary['record_count'] == 1
    assert result.validation.expected_shape == {'title': 'str'}
    reloaded = ys.recipe.load(str(recipe_path))
    assert reloaded.validation.summary['status'] == 'passed'


@pytest.mark.asyncio
async def test_recipe_validate_empty_replay_fails_and_out_writes(tmp_path, monkeypatch) -> None:
    recipe_path = tmp_path / 'recipe.json'
    out_path = tmp_path / 'validated.recipe.json'
    ys.recipe.mint(Product, selectors=ys.recipe.selector_map('https://example.com/1', title='h1'), out=recipe_path)

    @dataclass
    class _Result:
        status: str
        results: list[object]

    async def _fake_run(*args, **kwargs):
        return _Result(status='ok', results=[])

    monkeypatch.setattr(ys.recipe, 'run', _fake_run)

    result = await ys.recipe.validate(str(recipe_path), 'https://example.com/1', out=out_path)

    assert result.status == 'failed'
    assert result.path == out_path
    assert out_path.exists()
    reloaded = ys.recipe.load(str(out_path))
    assert reloaded.validation.summary['status'] == 'failed'
    assert reloaded.validation.summary['missing_fields'] == ['title']


def test_recipe_publish_requires_passing_validation_by_default() -> None:
    recipe = ys.recipe.mint(Product, selectors=ys.recipe.selector_map('https://example.com/1', title='h1'))
    failed = ys.recipe.mint(
        Product,
        selectors=ys.recipe.selector_map('https://example.com/1', title='h1'),
        validation={'fixture_urls': ['https://example.com/1'], 'summary': {'status': 'failed'}},
    )

    with pytest.raises(ValueError, match='validation evidence'):
        ys.recipe.publish(recipe, gist=True)
    with pytest.raises(ValueError, match='validation evidence'):
        ys.recipe.gist(recipe)
    with pytest.raises(ValueError, match='validation evidence'):
        ys.recipe.publish(failed, gist=True)


@pytest.mark.asyncio
async def test_seed_recipe_selectors_overwrites_existing_cache(monkeypatch) -> None:
    recipe = ys.recipe.mint(Product, selectors=ys.recipe.selector_map('https://example.com/1', title='h1.recipe'))
    captured = {}

    class _Storage:
        async def save_snapshots(self, url, snapshots, contract_sig=None, contract=None):
            captured.setdefault('saves', []).append((url, snapshots, contract_sig, contract))

    monkeypatch.setattr('yosoi.storage.persistence.SelectorStorage', lambda: _Storage())

    await ys.recipe._seed_recipe_selectors(recipe, ['https://example.com/2'])

    assert captured['saves']
    assert all(save[1]['title'].primary == 'h1.recipe' for save in captured['saves'])


def test_recipe_trust_rejects_untrusted_remote_before_fetch() -> None:
    with pytest.raises(PermissionError, match='no trusted remote'):
        ys.recipe.load('gh:evil/repo/recipe.json@main')


def test_recipe_trust_can_bind_owner_and_contract() -> None:
    recipe = ys.recipe.mint(Product, selectors=ys.recipe.selector_map('https://example.com/1', title='h1'))

    ys.recipe.Trust.github('owner').contracts(Product).verify(
        'gh:owner/repo/recipe.json@main',
        recipe,
    )
    with pytest.raises(PermissionError, match='contract fingerprint'):
        ys.recipe.Trust.github('owner').contracts(OtherProduct).verify(
            'gh:owner/repo/recipe.json@main',
            recipe,
        )
    with pytest.raises(PermissionError, match='GitHub owner'):
        ys.recipe.Trust.github('trusted').contracts(Product).verify(
            'gh:owner/repo/recipe.json@main',
            recipe,
        )


def test_recipe_policy_can_supply_trust(tmp_path) -> None:
    recipe = ys.recipe.mint(Product, selectors=ys.recipe.selector_map('https://example.com/1', title='h1'))
    path = tmp_path / 'recipe.json'
    path.write_text(recipe.canonical_json(), encoding='utf-8')

    policy = ys.Policy(recipe=ys.RecipePolicy.local_only().contracts(Product))
    assert ys.recipe.load(str(path), policy=policy).recipe_id == recipe.recipe_id

    wrong_policy = ys.Policy(recipe=ys.RecipePolicy.local_only().contracts(OtherProduct))
    with pytest.raises(PermissionError, match='contract fingerprint'):
        ys.recipe.load(str(path), policy=wrong_policy)


def test_recipe_policy_github_owner_accepts_gist_raw_url() -> None:
    policy = ys.RecipePolicy.github('user').contracts(Product).to_trust()
    policy.verify_source('https://gist.githubusercontent.com/user/abc123/raw/product.recipe.json')

    with pytest.raises(PermissionError, match='GitHub owner'):
        ys.RecipePolicy.github('other').to_trust().verify_source(
            'https://gist.githubusercontent.com/user/abc123/raw/product.recipe.json'
        )


def test_recipe_trust_allowlists_and_aliases(tmp_path) -> None:
    selectors = ys.recipe.selector_map('https://example.com/products/1', title='h1')
    recipe_path = tmp_path / 'recipe.json'
    recipe = ys.recipe.mint(Product, selectors=selectors, out=recipe_path)

    with pytest.raises(PermissionError, match='local recipes are not trusted'):
        ys.recipe.Trust(allow_local=False).verify_source(str(recipe_path))
    with pytest.raises(PermissionError, match='trusted remote origin'):
        ys.recipe.Trust.local_only().verify_source('https://example.com/recipe.json')
    with pytest.raises(PermissionError, match='GitHub owner'):
        ys.recipe.Trust.github('trusted-owner').verify_source('gh:other/repo/recipe.json')
    with pytest.raises(PermissionError, match='Recipe host'):
        ys.recipe.Trust.hosts('recipes.example.com').verify_source('https://other.example.com/recipe.json')
    with pytest.raises(PermissionError, match='recipe id allowlist'):
        ys.recipe.Trust.local_only().recipe_ids('v1:sha256:not-it').verify_artifact(recipe)
    with pytest.raises(PermissionError, match='contract allowlist'):
        ys.recipe.Trust.local_only().contracts(OtherProduct).verify_artifact(recipe)

    trust = ys.recipe.Trust.hosts('raw.githubusercontent.com').recipe_ids(recipe.recipe_id).contracts(Product)
    trust.verify('https://raw.githubusercontent.com/owner/repo/main/recipe.json', recipe)

    assert ys.recipe.load_recipe(str(recipe_path), recipe_id=recipe.recipe_id).recipe_id == recipe.recipe_id
    assert ys.recipe.check(str(recipe_path)).recipe_id == recipe.recipe_id
    installed = ys.recipe.install_recipe(str(recipe_path), cache_dir=tmp_path / 'cache')
    assert installed.path.exists()


def test_recipe_render_contract_edge_cases_and_helpers(tmp_path) -> None:
    from yosoi.models.spec import FieldSpec

    spec = ys.ContractSpec(
        name='123 weird-name',
        fields={
            'class': FieldSpec(
                python_type='tuple[str]',
                yosoi_type='title',
                description='Keyword field',
                selector='h1',
                delimiter=',',
                frozen=True,
                required=False,
                action={'type': 'text'},
            )
        },
        nested={'child item': ys.ContractSpec(name='Child Item', fields={})},
    )
    rendered = ys.recipe.render_contract_py(spec)

    assert 'class RecipeContract(ys.Contract):' in rendered
    assert 'class Child Item' not in rendered
    assert 'class_field: str = ys.Field(' in rendered
    assert 'delimiter=' in rendered
    assert "'yosoi_action': {'type': 'text'}" in rendered

    contract_json = tmp_path / 'contract.json'
    contract_json.write_text(spec.model_dump_json(), encoding='utf-8')
    assert ys.recipe.compile_contract(contract_json).name == spec.name
    assert ys.recipe.render_contract_py(contract_json).startswith('from __future__ import annotations')

    empty = ys.ContractSpec(name='123')
    assert 'class RecipeContract(ys.Contract):' in ys.recipe.render_contract_py(empty)
    with pytest.raises(ValueError, match='normalized'):
        ys.recipe.render_contract_py(
            ys.ContractSpec(name='BadRoot', root={'type': 'css', 'value': 'main', 'attribute': None})
        )


def test_recipe_sync_wrappers_and_publish_validation_errors(monkeypatch) -> None:
    recipe = ys.recipe.mint(Product, selectors=ys.recipe.selector_map('https://example.com/1', title='h1'))

    with pytest.raises(ValueError, match='Choose at least one'):
        ys.recipe.publish(recipe, allow_unvalidated=True)
    with pytest.raises(ValueError, match='no validation evidence'):
        ys.recipe.gist(recipe)
    with pytest.raises(ValueError, match='no validation evidence'):
        ys.recipe.publish(recipe, gist=True)

    def _fake_gist(artifact, *, filename=None, description=None, public=False, token=None):
        from yosoi.storage.recipe_store import GistPublishResult

        return GistPublishResult(raw_url='raw', html_url='html', filename=filename or 'recipe.json', public=public)

    monkeypatch.setattr(ys.recipe, 'publish_recipe_gist', _fake_gist)
    result = ys.recipe.gist(recipe, allow_unvalidated=True, public=True)
    assert result.public is True

    async def _fake_validate(*args, **kwargs):
        return ys.recipe.RecipeValidateResult(recipe=recipe, validation=recipe.validation, status='passed')

    async def _fake_run(*args, **kwargs):
        return {'ok': True}

    async def _fake_export(*, domains=(), source_urls=()):
        return []

    monkeypatch.setattr(ys.recipe, 'validate', _fake_validate)
    monkeypatch.setattr(ys.recipe, 'run', _fake_run)
    monkeypatch.setattr(ys.recipe, 'export_a3nodes', _fake_export)

    assert ys.recipe.validate_sync(recipe, 'https://example.com/1').status == 'passed'
    assert ys.recipe.run_sync(recipe, 'https://example.com/1') == {'ok': True}
    assert ys.recipe.export_a3nodes_sync(domains=['example.com']) == []
