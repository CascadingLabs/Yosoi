"""Demo: replay a shared recipe from GitHub — zero LLM, no discovery."""

import asyncio

import yosoi as ys

URL = 'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing'
SELECTORS_REF = 'gh:HoustonMiles/yosoi-recipes/recipes/qscrape.dev/v1/recipe.json@main'


async def main():
    """Replay selectors from a shared GitHub recipe without paying the LLM."""
    print('\n--- Using local contract + GitHub selectors ---')
    items = await ys.scrape(
        URL,
        contract=ys.Product,
        selectors=SELECTORS_REF,
        model='google:gemini-2.5-flash',
        fetcher_type='auto',
        quiet=False,
    )
    print(f'Got {len(items)} items')
    ys.show(items)


if __name__ == '__main__':
    asyncio.run(main())
