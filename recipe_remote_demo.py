"""Demo: local contract + selectors shared from GitHub — zero LLM, no discovery.

Pairs a locally-defined contract with a SELECTOR SNAPSHOT published to GitHub.
The snapshot is a bare {domain: SnapshotMap} document (no contract bundled), so
it goes in `selectors=` while `contract=` stays local — the mix-and-match case.
"""

import asyncio

import yosoi as ys

URL = 'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing'

# A bare selector-snapshot document (SnapshotMaps only, no contract). Despite the
# 'recipe.json' filename in the repo, this is a SELECTOR source, hence selectors=.
SELECTOR_SNAPSHOT_REF = 'gh:CascadingLabs/Yosoi-Recipe/selectors_qscrape_product.json@main'


class Product(ys.Contract):
    """A product card in the qscrape.dev L1 e-shop catalog."""

    name: str = ys.Title(description='Product name')
    price: float = ys.Price(description='Product price as a number')


async def main():
    """Replay selectors from a shared GitHub snapshot without paying the LLM."""
    print('\n--- Using local contract + GitHub selectors ---')
    items = await ys.scrape(
        URL,
        contract=Product,
        selectors=SELECTOR_SNAPSHOT_REF,
        model='google:gemini-2.5-flash',
        fetcher_type='auto',
        quiet=False,
    )
    print(f'Got {len(items)} items')
    ys.show(items)


if __name__ == '__main__':
    asyncio.run(main())
