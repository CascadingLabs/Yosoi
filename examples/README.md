# Examples

The examples are intentionally selector-free. They define data contracts and let
Yosoi discover selectors from the page structure.

## qscrape.dev

`qscrape.dev` is the maintained example target. Each level uses the same domain
with increasing rendering complexity:

- `l1/`: static HTML pages that the default auto fetcher handles at L1.
- `l2/`: JavaScript-rendered pages that the default auto fetcher promotes as needed.
- `l3/`: island-rendered pages that the default auto fetcher promotes as needed.

The scripts build a small `ys.Policy` layer and cascade it with `ys.Policy.from_env()`.
That keeps provider/model, force, discovery mode, and telemetry env switches in one
place while each example only declares the behavior it needs.

L1 scripts set `ScrapePolicy(fetcher_type='simple')`. L2/L3 scripts use the default
auto fetcher and set `ScrapePolicy(selector_level=ys.SelectorLevel.XPATH)` because
those pages exercise rendered DOM structure.

Set `YOSOI_MODEL` to choose a provider/model, and set `YOSOI_FORCE=1` when you
want to force rediscovery instead of replaying a cached contract. The examples do
not pass those as loose kwargs; `Policy.from_env()` reads them.

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

## API Design

`api_design/policy_api_design.py` is a no-network showcase for the full public
policy tree: `ModelPolicy`, `ScrapePolicy`, `DiscoveryPolicy`, `TelemetryPolicy`,
`OutputPolicy`, `DownloadPolicy`, and `CrawlPolicy`, plus `SecretRef.env(...)`
and `ResolvedRunSpec`.

```bash
uv run python examples/api_design/policy_api_design.py
```
