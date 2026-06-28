from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from yosoi.models.recipe import Recipe, RecipeMetadata
from yosoi.models.snapshot import SelectorSnapshot, SnapshotMap
from yosoi.models.spec import ContractSpec, FieldSpec
from yosoi.storage.recipe_store import (
    _normalize_github_repo,
    install_recipe,
    load_recipe,
    parse_selectors_file,
    publish_recipe_gist,
    resolve_recipe_ref,
)


def _snapshot(selector: str) -> SelectorSnapshot:
    return SelectorSnapshot(primary=selector, discovered_at=datetime.now(timezone.utc))


def _snap_map() -> SnapshotMap:
    return SnapshotMap(
        url='https://example.com/products/1',
        domain='example.com',
        snapshots={'title': _snapshot('h1')},
    )


def _contract() -> ContractSpec:
    return ContractSpec(name='Product', fields={'title': FieldSpec(yosoi_type='title', description='Title')})


def _recipe() -> Recipe:
    return Recipe(
        contract=_contract(),
        selectors={'example.com': _snap_map()},
        metadata=RecipeMetadata(name='example/products', domain_scope=['example.com']),
    )


def test_recipe_id_is_stable_across_json_round_trip() -> None:
    recipe = _recipe()
    reloaded = Recipe.model_validate_json(recipe.canonical_json())
    assert reloaded.recipe_id == recipe.recipe_id
    reloaded.verify_integrity()


def test_recipe_json_starts_with_instructions_and_omits_redundant_shape_fields() -> None:
    payload = json.loads(_recipe().canonical_json())
    assert next(iter(payload)) == 'instructions'
    assert 'schema_version' not in payload
    assert 'artifact_kind' not in payload
    assert 'domain' not in payload['selectors']['example.com']
    assert 'url' not in payload['selectors']['example.com']
    assert any('yosoi recipe check' in line for line in payload['instructions'])


def test_recipe_id_ignores_provenance_metadata() -> None:
    first = _recipe()
    second = _recipe().model_copy(
        update={'metadata': RecipeMetadata(name='example/products', domain_scope=['example.com'], notes='different')}
    )
    assert second.compute_id() == first.recipe_id


def test_recipe_integrity_fails_when_tampered() -> None:
    recipe = _recipe()
    payload = json.loads(recipe.canonical_json())
    payload['contract']['name'] = 'Other'
    tampered = Recipe.model_validate(payload)
    with pytest.raises(ValueError, match='integrity'):
        tampered.verify_integrity()


def test_recipe_id_version_rejects_unknown() -> None:
    payload = json.loads(_recipe().canonical_json())
    payload['recipe_id'] = payload['recipe_id'].replace('v1:', 'v99:', 1)
    with pytest.raises(ValueError, match='recipe_id'):
        Recipe.model_validate(payload)


def test_load_recipe_requires_recipe_id(tmp_path) -> None:
    payload = json.loads(_recipe().canonical_json())
    payload.pop('recipe_id')
    source = tmp_path / 'recipe.json'
    source.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError, match='missing required recipe_id'):
        load_recipe(str(source))


def test_a3node_order_is_preserved_and_identity_sensitive() -> None:
    first = _recipe().model_copy(update={'a3nodes': [{'acts': [{'step': 'first'}, {'step': 'second'}]}]})
    second = _recipe().model_copy(update={'a3nodes': [{'acts': [{'step': 'second'}, {'step': 'first'}]}]})
    assert json.loads(first.canonical_json())['a3nodes'][0]['acts'] == [{'step': 'first'}, {'step': 'second'}]
    assert first.compute_id() != second.compute_id()


def test_resolve_recipe_ref_defaults_to_main() -> None:
    assert resolve_recipe_ref('gh:owner/repo/recipes/foo.json') == (
        'https://raw.githubusercontent.com/owner/repo/main/recipes/foo.json'
    )


def test_resolve_recipe_ref_rewrites_github_blob_url() -> None:
    assert resolve_recipe_ref('https://github.com/owner/repo/blob/main/recipes/foo.json') == (
        'https://raw.githubusercontent.com/owner/repo/main/recipes/foo.json'
    )


def test_parse_selectors_file_accepts_single_snapshot_map(tmp_path) -> None:
    path = tmp_path / 'selectors.json'
    path.write_text(_snap_map().model_dump_json(), encoding='utf-8')
    parsed = parse_selectors_file(path)
    assert sorted(parsed) == ['example.com']


def test_install_recipe_writes_hash_named_cache_file(tmp_path) -> None:
    recipe = _recipe()
    source = tmp_path / 'recipe.json'
    source.write_text(recipe.canonical_json(), encoding='utf-8')
    cache = tmp_path / 'cache'

    result = install_recipe(str(source), cache_dir=cache)

    assert result.recipe.recipe_id == recipe.recipe_id
    assert result.path == cache / f'{recipe.recipe_id.replace(":", "-")}.json'
    assert load_recipe(str(result.path)).recipe_id == recipe.recipe_id


def test_normalize_github_repo_accepts_url_and_shorthand() -> None:
    assert _normalize_github_repo('owner/repo') == 'owner/repo'
    assert _normalize_github_repo('https://github.com/CascadingLabs/YosoiRecipes') == 'CascadingLabs/YosoiRecipes'
    assert _normalize_github_repo('https://github.com/CascadingLabs/YosoiRecipes.git') == 'CascadingLabs/YosoiRecipes'


def test_publish_recipe_gist_posts_secret_unlisted_payload(monkeypatch) -> None:
    recipe = _recipe()
    captured = {}

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
        captured['url'] = request.full_url
        captured['method'] = request.get_method()
        captured['payload'] = json.loads(request.data.decode('utf-8'))
        captured['content_type'] = request.get_header('Content-type')
        captured['timeout'] = timeout
        return _Response()

    monkeypatch.setattr('yosoi.storage.recipe_store.urlopen', _fake_urlopen)

    result = publish_recipe_gist(recipe, filename='product.recipe.json', token='ghp_test')

    assert result.html_url == 'https://gist.github.com/user/abc123'
    assert result.raw_url == 'https://gist.githubusercontent.com/user/abc123/raw/product.recipe.json'
    assert result.public is False
    assert captured['url'] == 'https://api.github.com/gists'
    assert captured['method'] == 'POST'
    assert captured['payload']['public'] is False
    assert captured['content_type'] == 'application/json'
    assert 'product.recipe.json' in captured['payload']['files']
    assert recipe.recipe_id in captured['payload']['files']['product.recipe.json']['content']


def test_publish_recipe_github_uses_gh_auth_token(monkeypatch) -> None:
    recipe = _recipe()
    captured = {}

    def _fake_run(args, check, capture_output, text, timeout):
        captured['args'] = args

        class _Result:
            stdout = 'gh_auth_token\n'

        return _Result()

    def _fake_existing_sha(api_url, *, branch, token):
        captured['existing_token'] = token

    def _fake_request_json(url, *, method, token, payload, auth_header='Authorization'):
        captured['request_token'] = token
        captured['payload'] = payload
        return {'content': {'html_url': 'https://github.com/owner/repo/blob/main/recipe.json'}}

    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('GH_TOKEN', raising=False)
    monkeypatch.setattr('yosoi.storage.recipe_store.subprocess.run', _fake_run)
    monkeypatch.setattr('yosoi.storage.recipe_store._github_existing_sha', _fake_existing_sha)
    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _fake_request_json)

    from yosoi.storage.recipe_store import publish_recipe_github

    url = publish_recipe_github(recipe, repo='owner/repo', path='recipe.json')

    assert url == 'https://github.com/owner/repo/blob/main/recipe.json'
    assert captured['args'] == ['gh', 'auth', 'token']
    assert captured['existing_token'] == 'gh_auth_token'
    assert captured['request_token'] == 'gh_auth_token'


def test_publish_recipe_gist_rejects_tampered_in_memory_recipe(monkeypatch) -> None:
    def _fail_urlopen(request, timeout):
        raise AssertionError('network should not be called for a tampered recipe')

    monkeypatch.setattr('yosoi.storage.recipe_store.urlopen', _fail_urlopen)
    tampered = _recipe().model_copy(update={'contract': _contract().model_copy(update={'name': 'Tampered'})})

    with pytest.raises(ValueError, match='integrity'):
        publish_recipe_gist(tampered, filename='bad.recipe.json', token='ghp_test')
