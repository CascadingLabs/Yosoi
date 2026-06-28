from __future__ import annotations

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
