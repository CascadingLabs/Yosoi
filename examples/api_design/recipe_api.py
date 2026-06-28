"""Ergonomic flat-recipe API demo.

Run:
    uv run python examples/api_design/recipe_api.py

Equivalent CLI:
    bash examples/api_design/recipe_cli_demo.sh

Design intent:
- contracts look like normal Yosoi contracts;
- recipe actions mirror the CLI as `ys.recipe.mint/load/install/run/publish`;
- recipe acceptance is deny-by-default for remote refs unless a tight trust policy
  is supplied;
- a recipe can be consumed as pieces: contract, selectors, A3Nodes, or URLs.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yosoi as ys


class Product(ys.Contract):
    """Product detail page."""

    title: str = ys.Title(description='Product title')
    price: str = ys.Price(description='Displayed product price')


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix='yosoi-recipe-api-'))
    recipe_path = workdir / 'product.recipe.json'
    cache_dir = workdir / 'cache'

    discovered_fields = ys.recipe.selector_map(
        'https://example.com/products/sku-1',
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        title='discovered-title-field',
        price='discovered-price-field',
    )

    recipe = ys.recipe.mint(
        Product,
        selectors=discovered_fields,
        out=recipe_path,
        name='example.com/products',
        domain_scope=['example.com'],
        source_urls=['https://example.com/products/sku-1'],
        url_patterns=['https://example.com/products/*'],
        a3nodes=[
            {
                'name': 'accept_cookie_banner',
                'acts': [
                    {'kind': 'click', 'selector': 'button.accept'},
                    {'kind': 'wait_for', 'selector': 'body.ready'},
                ],
            }
        ],
        validation=ys.recipe.Validation(
            fixture_urls=['https://example.com/products/sku-1'],
            expected_shape={'title': 'str', 'price': 'str'},
            summary={'status': 'example-only', 'field_count': 2},
        ),
    )
    print(f'minted: {recipe.recipe_id}')
    print(f'file:   {recipe_path}')

    # Local files are trusted by default; remote refs require explicit trust.
    loaded = ys.recipe.load(str(recipe_path), recipe_id=recipe.recipe_id)
    installed = ys.recipe.install(str(recipe_path), recipe_id=recipe.recipe_id, cache_dir=cache_dir)
    print(f'installed: {installed.path}')

    # Tight remote trust: owner AND contract fingerprint must match.
    recipe_policy = ys.Policy(recipe=ys.RecipePolicy.github('owner').contracts(Product))
    print(f'recipe policy: {recipe_policy.recipe}')
    print('remote install shape:')
    print("  ys.recipe.install('gh:owner/yosoi-recipes/recipes/example.com/products/v1/recipe.json@main',")
    print("                    policy=ys.Policy(recipe=ys.RecipePolicy.github('owner').contracts(Product)))")
    print('run shape:')
    print('  await ys.recipe.run(recipe, "https://example.com/products/sku-2")')
    print('publish shapes:')
    print("  ys.recipe.publish(recipe, repo='https://github.com/owner/yosoi-recipes')  # opens PR by default")
    print("  ys.recipe.publish(recipe, repo='owner/yosoi-recipes', direct=True)       # direct commit override")
    print("  ys.recipe.publish(recipe, gist=True, filename='product.recipe.json')")
    print("  ys.recipe.publish(recipe, repo='owner/yosoi-recipes', gist=True)       # multi-target")

    # Consume pieces instead of all-or-nothing replay.
    RecipeContract = loaded.to_contract()
    installed_map = loaded.selectors_for('www.example.com')
    actions = loaded.a3nodes
    urls = loaded.fixture_urls()

    print(f'piece: contract={RecipeContract.__name__}')
    print(f'piece: selector_fields={sorted(installed_map.snapshots) if installed_map else []}')
    print(f'piece: a3nodes={len(actions)} urls={urls}')

    print(json.dumps({'recipe_id': loaded.recipe_id, 'path': str(recipe_path)}, indent=2))


if __name__ == '__main__':
    main()
