from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from yosoi.models.recipe import Recipe, RecipeMetadata
from yosoi.models.snapshot import SelectorSnapshot, SnapshotMap
from yosoi.models.spec import ContractSpec, FieldSpec
from yosoi.storage.recipe_store import install_recipe, load_recipe, parse_selectors_file, resolve_recipe_ref


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


def test_recipe_schema_version_rejects_unknown() -> None:
    payload = json.loads(_recipe().canonical_json())
    payload['schema_version'] = 'yosoi.recipe.v99'
    with pytest.raises(ValueError, match='schema_version'):
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
    assert result.path == cache / f'{recipe.recipe_id.removeprefix("sha256:")}.json'
    assert load_recipe(str(result.path)).recipe_id == recipe.recipe_id
