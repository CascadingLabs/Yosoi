"""End-to-end test: scrape with LLM discovery, mint a recipe, then replay without the LLM."""

import asyncio
import os

import yosoi as ys
from yosoi.models.recipe import RecipeBundle
from yosoi.models.snapshot import SnapshotMap
from yosoi.storage.persistence import SelectorStorage
from yosoi.utils.urls import extract_domain

URL = 'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing'


class Product(ys.Contract):
    """A product card in the qscrape.dev L1 e-shop catalog."""

    name: str = ys.Title(description='Product name')
    price: float = ys.Price(description='Product price as a number')


async def main():
    """Run the discovery scrape, mint a recipe from it, then replay the recipe and compare results."""
    print('\n--- Step 1: Normal scrape (pays LLM) ---')
    items1 = await ys.scrape(URL, Product, fetcher_type='simple', model='google:gemini-2.5-flash', quiet=False)
    print(f'Got {len(items1)} items')
    ys.show(items1)

    print('\n--- Step 2: Mint recipe from discovered selectors ---')
    storage = SelectorStorage()
    domain = extract_domain(URL)
    snapshots = await storage.load_snapshots(domain)
    assert snapshots, 'No snapshots found — Step 1 must have failed'
    snap_map = SnapshotMap(url=URL, domain=domain, snapshots=snapshots)
    bundle = RecipeBundle.from_parts(Product, {domain: snap_map})

    recipe_path = 'test_recipe.json'
    bundle.save(recipe_path)
    print(f'Recipe saved to {recipe_path}')

    print('\n--- Step 3: Replay from recipe (zero LLM) ---')
    items2 = await ys.scrape(URL, contract=recipe_path, fetcher_type='simple', quiet=False)
    print(f'Got {len(items2)} items')
    ys.show(items2)

    print('\n--- Step 4: Verify results match ---')
    assert len(items1) == len(items2), f'Item count mismatch: {len(items1)} vs {len(items2)}'
    print('✓ Item counts match')
    print('✓ Recipe replay works')

    os.unlink(recipe_path)


if __name__ == '__main__':
    asyncio.run(main())
