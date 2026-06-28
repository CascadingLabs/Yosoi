from __future__ import annotations

import io
import json
import subprocess
from datetime import datetime, timezone
from urllib.error import HTTPError

import pytest

from yosoi.models.recipe import Recipe, RecipeMetadata
from yosoi.models.snapshot import SelectorSnapshot, SnapshotMap
from yosoi.models.spec import ContractSpec, FieldSpec
from yosoi.storage.recipe_store import (
    _cli_auth_token,
    _fetch_https_text,
    _fetch_text,
    _github_branch_sha,
    _github_create_branch,
    _github_ensure_fork,
    _github_error_detail,
    _github_existing_pr,
    _github_existing_sha,
    _github_token,
    _github_user_login,
    _http_error_detail,
    _normalize_github_repo,
    _recipe_pr_branch,
    _request_json,
    install_recipe,
    load_recipe,
    parse_contract_file,
    parse_json_file,
    parse_selectors_file,
    publish_recipe_gist,
    publish_recipe_github,
    publish_recipe_github_pr,
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
    base = {
        'scope': {
            'scope_key': 'a3scope:v1:test',
            'domain': 'example.com',
            'page_profile': '/items',
            'intent': 'fetch',
            'browser_fingerprint': 'default',
        }
    }
    first = Recipe.model_validate(
        _recipe().model_dump(mode='json')
        | {'a3nodes': [base | {'acts': [{'kind': 'cookie', 'cycles': 1}, {'kind': 'load_more', 'cycles': 1}]}]}
    )
    second = Recipe.model_validate(
        _recipe().model_dump(mode='json')
        | {'a3nodes': [base | {'acts': [{'kind': 'load_more', 'cycles': 1}, {'kind': 'cookie', 'cycles': 1}]}]}
    )
    acts = json.loads(first.canonical_json())['a3nodes'][0]['acts']
    assert [act['kind'] for act in acts] == ['cookie', 'load_more']
    assert all('assert' in act and 'assert_' not in act for act in acts)
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


def _http_error(code: int, body: bytes = b'{"message":"boom"}') -> HTTPError:
    return HTTPError('https://api.github.com/test', code, 'reason', {}, io.BytesIO(body))


def _return(value):
    def _inner(*_args, **_kwargs):
        return value

    return _inner


def _raise_http(code: int, body: bytes = b'{"message":"boom"}'):
    def _inner(*_args, **_kwargs):
        raise _http_error(code, body)

    return _inner


def _token_or_default(token=None):
    return token or 'tok'


class _BytesResponse:
    def __init__(self, body: bytes, *, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


def test_resolve_recipe_ref_rejects_malformed_github_shorthand() -> None:
    with pytest.raises(ValueError, match='Expected gh:owner/repo'):
        resolve_recipe_ref('gh:owner/repo')
    assert resolve_recipe_ref('gh:owner/repo/path.json@dev') == (
        'https://raw.githubusercontent.com/owner/repo/dev/path.json'
    )


def test_load_recipe_rejects_invalid_json_non_object_and_id_mismatch(tmp_path) -> None:
    invalid = tmp_path / 'invalid.json'
    invalid.write_text('{nope', encoding='utf-8')
    with pytest.raises(ValueError, match='invalid JSON'):
        load_recipe(str(invalid))

    array = tmp_path / 'array.json'
    array.write_text('[]', encoding='utf-8')
    with pytest.raises(ValueError, match='must be a JSON object'):
        load_recipe(str(array))

    recipe = _recipe()
    source = tmp_path / 'recipe.json'
    source.write_text(recipe.canonical_json(), encoding='utf-8')
    with pytest.raises(ValueError, match='refusing install'):
        load_recipe(str(source), expected_recipe_id='v1:sha256:not-it')


def test_json_parsers_cover_domain_maps_contracts_and_errors(tmp_path) -> None:
    selectors = tmp_path / 'selectors.json'
    selectors.write_text(json.dumps({'example.com': _snap_map().model_dump(mode='json')}), encoding='utf-8')
    assert sorted(parse_selectors_file(selectors)) == ['example.com']

    contract = tmp_path / 'contract.json'
    contract.write_text(_contract().model_dump_json(), encoding='utf-8')
    assert parse_contract_file(contract).name == 'Product'
    assert parse_json_file(contract)['name'] == 'Product'

    empty = tmp_path / 'empty.json'
    empty.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='at least one domain'):
        parse_selectors_file(empty)

    bad_entry = tmp_path / 'bad-entry.json'
    bad_entry.write_text('{"example.com": 1}', encoding='utf-8')
    with pytest.raises(ValueError, match='must be an object'):
        parse_selectors_file(bad_entry)

    missing = tmp_path / 'missing.json'
    with pytest.raises(FileNotFoundError, match='Cannot read'):
        parse_json_file(missing)


def test_fetch_text_rejects_plain_http_and_missing_files() -> None:
    with pytest.raises(ValueError, match='Refusing plaintext'):
        _fetch_text('http://example.com/recipe.json')
    with pytest.raises(FileNotFoundError, match='Recipe file not found'):
        _fetch_text('/does/not/exist.json')


def test_fetch_https_text_enforces_declared_and_actual_size(monkeypatch) -> None:
    def _declared_too_large(request, timeout):
        return _BytesResponse(b'', headers={'content-length': str(6 * 1024 * 1024)})

    monkeypatch.setattr('yosoi.storage.recipe_store.urlopen', _declared_too_large)
    with pytest.raises(ValueError, match='too large'):
        _fetch_https_text('https://example.com/recipe.json')

    def _actual_too_large(request, timeout):
        return _BytesResponse(b'x' * (5 * 1024 * 1024 + 2))

    monkeypatch.setattr('yosoi.storage.recipe_store.urlopen', _actual_too_large)
    with pytest.raises(ValueError, match='exceeds'):
        _fetch_https_text('https://example.com/recipe.json')


def test_github_repo_and_token_helpers_cover_error_paths(monkeypatch) -> None:
    with pytest.raises(ValueError, match=r'github\.com'):
        _normalize_github_repo('https://gitlab.com/owner/repo')
    with pytest.raises(ValueError, match='owner/repo'):
        _normalize_github_repo('owner/repo/extra')

    assert _github_token('explicit') == 'explicit'
    monkeypatch.setenv('GH_TOKEN', 'env-token')
    assert _github_token() == 'env-token'
    monkeypatch.delenv('GH_TOKEN')
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)

    def _raise(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=['gh'], timeout=5)

    monkeypatch.setattr('yosoi.storage.recipe_store.subprocess.run', _raise)
    assert _cli_auth_token(['gh', 'auth', 'token']) is None
    assert _github_token() is None


def test_github_branch_and_user_helpers(monkeypatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def _fake_request(url, *, method, token, payload, auth_header='Authorization'):
        calls.append((url, method, token))
        if url.endswith('/user'):
            return {'login': 'octo'}
        return {'object': {'sha': 'abc123'}}

    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _fake_request)
    assert _github_user_login('tok') == 'octo'
    assert _github_branch_sha('owner/repo', branch='main', token='tok') == 'abc123'
    assert calls[0] == ('https://api.github.com/user', 'GET', 'tok')

    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _return({}))
    with pytest.raises(ValueError, match='authenticated user'):
        _github_user_login('tok')
    with pytest.raises(ValueError, match='did not return a SHA'):
        _github_branch_sha('owner/repo', branch='main', token='tok')


def test_github_fork_branch_pr_helpers(monkeypatch) -> None:
    seen: list[str] = []

    def _request_existing(url, *, method, token, payload, auth_header='Authorization'):
        seen.append(url)
        return {'ok': True}

    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _request_existing)
    assert _github_ensure_fork('owner/repo', login='me', token='tok') == 'me/repo'
    assert seen == ['https://api.github.com/repos/me/repo']

    attempts = {'fork': 0}

    def _request_create(url, *, method, token, payload, auth_header='Authorization'):
        if url == 'https://api.github.com/repos/me/repo' and attempts['fork'] == 0:
            attempts['fork'] += 1
            raise _http_error(404)
        seen.append(url)
        return {'ok': True}

    seen.clear()
    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _request_create)
    assert _github_ensure_fork('owner/repo', login='me', token='tok') == 'me/repo'
    assert 'https://api.github.com/repos/owner/repo/forks' in seen

    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _return([{'html_url': 'pr'}]))
    assert _github_existing_pr('owner/repo', head='me:branch', base='main', token='tok') == {'html_url': 'pr'}
    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _return([]))
    assert _github_existing_pr('owner/repo', head='me:branch', base='main', token='tok') is None


def test_github_create_branch_and_existing_sha_errors(monkeypatch) -> None:
    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _raise_http(422))
    _github_create_branch('owner/repo', branch='branch', sha='abc', token='tok')

    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _raise_http(500))
    with pytest.raises(HTTPError):
        _github_create_branch('owner/repo', branch='branch', sha='abc', token='tok')
    with pytest.raises(HTTPError):
        _github_existing_sha('https://api.github.com/repos/owner/repo/contents/r.json', branch='main', token='tok')

    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _raise_http(404))
    assert (
        _github_existing_sha('https://api.github.com/repos/owner/repo/contents/r.json', branch='main', token='tok')
        is None
    )
    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _return({'sha': 'abc'}))
    assert (
        _github_existing_sha('https://api.github.com/repos/owner/repo/contents/r.json', branch='main', token='tok')
        == 'abc'
    )


def test_request_json_builds_headers_and_handles_empty_response(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout):
        captured['auth'] = request.get_header('X-api-key')
        captured['method'] = request.get_method()
        captured['payload'] = request.data
        captured['timeout'] = timeout
        return _BytesResponse(b'')

    monkeypatch.setattr('yosoi.storage.recipe_store.urlopen', _fake_urlopen)
    assert (
        _request_json('https://api.example.test', method='POST', token='tok', payload={'a': 1}, auth_header='X-API-Key')
        == {}
    )
    assert captured == {'auth': 'tok', 'method': 'POST', 'payload': b'{"a": 1}', 'timeout': 30.0}


def test_github_error_detail_formats_structured_and_plain_errors() -> None:
    body = json.dumps({'message': 'Validation Failed', 'errors': [{'resource': 'PullRequest', 'field': 'head'}]})
    assert _github_error_detail(body) == 'Validation Failed: PullRequest head'
    assert _github_error_detail('[1]') == '[1]'
    assert _github_error_detail('plain text') == 'plain text'
    assert _http_error_detail(_http_error(422, body.encode('utf-8'))) == 'Validation Failed: PullRequest head'


def test_publish_recipe_gist_error_paths(monkeypatch) -> None:
    recipe = _recipe()
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('GH_TOKEN', raising=False)
    monkeypatch.setattr('yosoi.storage.recipe_store._cli_auth_token', _return(None))
    with pytest.raises(ValueError, match='Gist publish requires'):
        publish_recipe_gist(recipe)

    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _return([]))
    with pytest.raises(ValueError, match='not a JSON object'):
        publish_recipe_gist(recipe, token='tok')

    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _return({'files': {}}))
    with pytest.raises(ValueError, match='raw_url'):
        publish_recipe_gist(recipe, token='tok')


def test_publish_recipe_github_paths(monkeypatch) -> None:
    recipe = _recipe()
    monkeypatch.setattr('yosoi.storage.recipe_store._github_token', _return(None))
    with pytest.raises(ValueError, match='GitHub publish requires'):
        publish_recipe_github(recipe, repo='owner/repo', path='recipe.json')

    captured: dict[str, object] = {}
    monkeypatch.setattr('yosoi.storage.recipe_store._github_token', _token_or_default)
    monkeypatch.setattr('yosoi.storage.recipe_store._github_existing_sha', _return('sha123'))

    def _request(url, *, method, token, payload, auth_header='Authorization'):
        captured.update({'url': url, 'payload': payload, 'token': token})
        return {}

    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _request)
    assert publish_recipe_github(recipe, repo='owner/repo', path='/recipes/product.json', token='tok') == (
        'https://github.com/owner/repo/blob/main/recipes/product.json'
    )
    assert captured['payload']['sha'] == 'sha123'
    assert captured['payload']['branch'] == 'main'


def test_publish_recipe_github_pr_success_and_422_reuse(monkeypatch) -> None:
    recipe = _recipe()
    calls: list[str] = []
    monkeypatch.setattr('yosoi.storage.recipe_store._github_token', _token_or_default)
    monkeypatch.setattr('yosoi.storage.recipe_store._github_user_login', _return('me'))

    def _fork(_owner_repo, *, login, token):
        return f'{login}/repo'

    def _create_branch(_owner_repo, *, branch, sha, token):
        calls.append(f'branch:{branch}:{sha}')

    def _publish(*_args, **_kwargs):
        calls.append('publish')
        return 'url'

    monkeypatch.setattr('yosoi.storage.recipe_store._github_ensure_fork', _fork)
    monkeypatch.setattr('yosoi.storage.recipe_store._github_branch_sha', _return('base-sha'))
    monkeypatch.setattr('yosoi.storage.recipe_store._github_create_branch', _create_branch)
    monkeypatch.setattr('yosoi.storage.recipe_store.publish_recipe_github', _publish)
    monkeypatch.setattr(
        'yosoi.storage.recipe_store._request_json', _return({'html_url': 'https://github.com/owner/repo/pull/1'})
    )

    result = publish_recipe_github_pr(recipe, repo='owner/repo', path='recipes/product.json', pr_branch='recipe-branch')

    assert result.html_url == 'https://github.com/owner/repo/pull/1'
    assert result.branch == 'recipe-branch'
    assert result.fork_repo == 'me/repo'
    assert calls == ['branch:recipe-branch:base-sha', 'publish']

    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _raise_http(422))
    monkeypatch.setattr('yosoi.storage.recipe_store._github_existing_pr', _return({'html_url': 'existing-pr'}))
    assert publish_recipe_github_pr(recipe, repo='owner/repo', path='recipes/product.json').html_url == 'existing-pr'

    monkeypatch.setattr('yosoi.storage.recipe_store._github_existing_pr', _return(None))
    with pytest.raises(ValueError, match='GitHub PR publish failed'):
        publish_recipe_github_pr(recipe, repo='owner/repo', path='recipes/product.json')


def test_publish_recipe_github_pr_token_and_non_422_errors(monkeypatch) -> None:
    recipe = _recipe()
    monkeypatch.setattr('yosoi.storage.recipe_store._github_token', _return(None))
    with pytest.raises(ValueError, match='GitHub PR publish requires'):
        publish_recipe_github_pr(recipe, repo='owner/repo', path='recipes/product.json')

    monkeypatch.setattr('yosoi.storage.recipe_store._github_token', _return('tok'))
    monkeypatch.setattr('yosoi.storage.recipe_store._github_user_login', _return('me'))
    monkeypatch.setattr('yosoi.storage.recipe_store._github_ensure_fork', _return('me/repo'))
    monkeypatch.setattr('yosoi.storage.recipe_store._github_branch_sha', _return('sha'))
    monkeypatch.setattr('yosoi.storage.recipe_store._github_create_branch', _return(None))
    monkeypatch.setattr('yosoi.storage.recipe_store.publish_recipe_github', _return('url'))
    monkeypatch.setattr('yosoi.storage.recipe_store._request_json', _raise_http(500, b'plain'))
    with pytest.raises(ValueError, match='500'):
        publish_recipe_github_pr(recipe, repo='owner/repo', path='recipes/product.json')


def test_recipe_pr_branch_sanitizes_contract_name() -> None:
    recipe = _recipe().model_copy(update={'contract': _contract().model_copy(update={'name': 'Product Card!'})})
    assert _recipe_pr_branch(recipe).startswith('yosoi/product-card-')
