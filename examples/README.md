# Examples

The examples are intentionally selector-free. They define data contracts and let
Yosoi discover selectors from the page structure.

## qscrape.dev

`qscrape.dev` is the maintained example target. Each level uses the same domain
with increasing rendering complexity:

- `l1/`: static HTML pages that the default auto fetcher handles at L1.
- `l2/`: JavaScript-rendered pages that the default auto fetcher promotes as needed.
- `l3/`: island-rendered pages that the default auto fetcher promotes as needed.

The scripts use Yosoi's default `fetcher_type='auto'`, so they stay close to the
recommended path: try plain HTTP first, then promote only when the page requires it.

Set `YOSOI_MODEL` to choose a provider/model, and set `YOSOI_FORCE=1` when you
want to force rediscovery instead of replaying a cached contract.

Each level has examples for:

- `eshop/catalog.py`
- `news/articles.py`
- `scoretap/scores.py`
- `taxes/registry.py`

Run one directly, for example:

```bash
YOSOI_MODEL=groq:llama-3.3-70b-versatile \
uv run python examples/qscrape.dev/l1/eshop/catalog.py
```

## Google Search

`google_search/google_search.py` is an offline replay example. It exercises
parametrized navigation, teleport settings, captcha recovery, and contract
signatures without making live Google traffic.

```bash
uv run python examples/google_search/google_search.py
```
