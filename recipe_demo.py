"""Demo: scrape with LLM discovery, mint a fingerprinted recipe, replay with validation.

Extends the basic recipe round-trip with page-fingerprint validation:
  - Step 2 captures the page's PageFingerprint and bundles it into the recipe.
  - Step 3 replays with recipe_match=FAIL, so a shape-drifted page would raise.
  - Step 5 proves the gate discriminates: replaying the recipe against a
    structurally different page is expected to raise RecipeFingerprintMismatch.
"""

import asyncio
import os

import httpx

import yosoi as ys
from yosoi.models.recipe import RecipeBundle
from yosoi.models.snapshot import SnapshotMap
from yosoi.policy import Policy
from yosoi.policy.fingerprint import FingerprintPolicy, RecipeMatchMode
from yosoi.storage.persistence import SelectorStorage
from yosoi.storage.recipe_fingerprint import RecipeFingerprintMismatch
from yosoi.utils.signatures import contract_signature
from yosoi.utils.urls import extract_domain

URL = 'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing'
# A structurally different page on the same site, used to prove the gate discriminates.
OTHER_SHAPE_URL = 'https://qscrape.dev/l1/blog/'

# Validate on replay and refuse a shape-drifted recipe.
VALIDATE = Policy(fingerprint=FingerprintPolicy(recipe_match=RecipeMatchMode.FAIL))


class Product(ys.Contract):
    """A product card in the qscrape.dev L1 e-shop catalog."""

    name: str = ys.Title(description='Product name')
    price: float = ys.Price(description='Product price as a number')


async def _page_fingerprint(url: str):
    """Fetch a page and compute its PageFingerprint via the public ys.fingerprint() entry."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    return ys.fingerprint(resp.text)


async def main():
    """Discovery scrape → mint fingerprinted recipe → validated replay → drift check."""
    print('\n--- Step 1: Normal scrape (pays LLM) ---')
    items1 = await ys.scrape(URL, Product, fetcher_type='simple', model='google:gemini-2.5-flash', quiet=False)
    print(f'Got {len(items1)} items')
    ys.show(items1)

    print('\n--- Step 2: Mint recipe WITH page fingerprint ---')
    storage = SelectorStorage()
    domain = extract_domain(URL)
    snapshots = await storage.load_snapshots(domain, contract_sig=contract_signature(Product))
    assert snapshots, 'No snapshots found — Step 1 must have failed'
    snap_map = SnapshotMap(url=URL, domain=domain, snapshots=snapshots)
    fp = await _page_fingerprint(URL)
    bundle = RecipeBundle.from_parts(Product, {domain: snap_map}, fingerprints={domain: fp})
    recipe_path = 'recipe.json'
    bundle.save(recipe_path)
    print(f'Recipe saved to {recipe_path} (fingerprinted domains: {list(bundle.fingerprints)})')

    print('\n--- Step 3: Replay with fingerprint validation (zero LLM) ---')
    items2 = await ys.scrape(URL, contract=recipe_path, fetcher_type='simple', quiet=False, policy=VALIDATE)
    print(f'Got {len(items2)} items')
    ys.show(items2)

    print('\n--- Step 4: Verify results match ---')
    assert len(items1) == len(items2), f'Item count mismatch: {len(items1)} vs {len(items2)}'
    print('✓ Item counts match')
    print('✓ Fingerprinted recipe replay works')

    print('\n--- Step 5: Drift check — replay recipe against a different-shaped page ---')
    try:
        await ys.scrape(OTHER_SHAPE_URL, contract=recipe_path, fetcher_type='simple', quiet=True, policy=VALIDATE)
        print('✗ Expected a fingerprint mismatch but none was raised')
    except RecipeFingerprintMismatch as e:
        print(f'✓ Gate correctly refused the shape-drifted page:\n    {e}')

    os.unlink(recipe_path)


if __name__ == '__main__':
    asyncio.run(main())
