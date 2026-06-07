# Examples

The examples are intentionally selector-free. They define data contracts and let
Yosoi discover selectors from the page structure.

## qscrape.dev

`qscrape.dev` is the maintained example target. Each level uses the same domain
with increasing rendering complexity:

- `l1/`: static HTML pages that can run with the simple fetcher.
- `l2/`: JavaScript-rendered pages that use the waterfall fetcher.
- `l3/`: island-rendered pages that use the waterfall fetcher.

Each level has examples for:

- `eshop/catalog.py`
- `news/articles.py`
- `scoretap/scores.py`
- `taxes/registry.py`

Run one directly, for example:

```bash
uv run python examples/qscrape.dev/l1/eshop/catalog.py
```

## Google Search

`google_search/google_search.py` is an offline replay example. It exercises
parametrized navigation, teleport settings, captcha recovery, and contract
signatures without making live Google traffic.

```bash
uv run python examples/google_search/google_search.py
```
